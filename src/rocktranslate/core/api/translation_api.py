"""
RockTranslate — Asynchronous Extraction and Translation Web API Mixin
Path: src/rocktranslate/core/api/translation_api.py

Hosts background worker threads managing high-fidelity pdf2htmlEX parsing,
BeautifulSoup tag instrumentation, and asynchronous LiteLLM streaming translations.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.2
"""

import os
import json
import threading
import webview
import tempfile
import re
import shutil
from typing import Dict, List, Optional, Any, Set
from loguru import logger
from ..renderer import resolve_pdf_renderer, apply_translations_offline, print_html_to_vector_pdf
from ..pdf_metadata import get_pdf_metadata

from ..html_transformer import convert_pdf_to_html, instrument_html
from ..config_manager import config_db
from ..constants import DEFAULT_ASSETS_DIR, DEFAULT_PROVIDERS
from ..chunker import build_batches
from ..llm_client import LLMClient


class TranslationApiMixin:
    """
    Mixin class driving background PDF parsing and LLM translation workers.
    Communicates live with frontend viewports via evaluate_js mappings.
    """
    def __init__(self) -> None:
        self._active_pdf_path: Optional[str] = None
        self._active_html_path: Optional[str] = None
        self._original_texts: Dict[str, str] = {}
        self._tid_to_page: Dict[str, int] = {}
        self._translated_texts: Dict[str, str] = {}

        self._stop_translation: bool = False
        self._current_translating_page: int = -1
        self._trans_thread: Optional[threading.Thread] = None

    # ==============================================================================
    # 1. BACKGROUND LAYOUT EXTRACTION WORKER
    # ==============================================================================

    def extract_pdf(self, file_path: str) -> None:
        thread = threading.Thread(
            target=self._run_extraction, 
            args=(file_path,), 
            daemon=True
        )
        thread.start()

    def _run_extraction(self, pdf_path: str) -> None:
        try:
            self._send_status_i18n("status_extraction_start")
            logger.info(f"Initiating background layout extraction for: {pdf_path}")

            def on_pdf_progress(current: int, total: int):
                self._send_status_i18n("status_extraction_pages", {"current": current, "total": total})

            assets_dir = config_db.get("SystemConfig", "pdf2htmlex_path_override", "")
            if not assets_dir or not os.path.exists(assets_dir):
                assets_dir = DEFAULT_ASSETS_DIR

            raw_html_path = convert_pdf_to_html(pdf_path, assets_dir, on_progress=on_pdf_progress)

            if not raw_html_path or not os.path.exists(raw_html_path):
                self._send_status_i18n("status_extraction_failed")
                self._send_toast_i18n("status_extraction_failed", "error")
                return

            self._send_status_i18n("status_extraction_instrumenting")
            logger.info("Executing BeautifulSoup semantic tag compilation...")

            pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
            pdf_filename = os.path.basename(pdf_path)
            instrumented_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_workspace.html")

            original_texts_map, tid_to_page = instrument_html(raw_html_path, instrumented_html_path)

            self._active_pdf_path = pdf_path
            self._active_html_path = instrumented_html_path
            self._original_texts = original_texts_map
            self._tid_to_page = tid_to_page
            self._translated_texts = {} 

            total_pages = max(tid_to_page.values()) + 1 if tid_to_page else 1
            config_db.set("RecentFiles", "active_total_pages", total_pages)
            self._add_to_recent_files(pdf_path)

            self._send_status_i18n("status_extraction_success")
            logger.info(f"Document successfully loaded: {total_pages} pages, {len(original_texts_map)} segments.")

            total_segments = len(original_texts_map)
            js_call = (
                f"window.dispatchEvent(new CustomEvent('document-ready', {{ "
                f"detail: {{ "
                f"pdfPath: {json.dumps(pdf_path)}, "
                f"htmlPath: {json.dumps(instrumented_html_path)}, "
                f"totalPages: {total_pages}, "
                f"totalSegments: {total_segments} "
                f"}} "
                f"}}))"
            )
            self._send_js(js_call)

        except Exception as error:
            logger.error(f"Critical exception raised during background document processing: {error}")
            self._send_status_i18n("status_extraction_error", {"error": str(error)})
            self._send_toast_i18n("toast_extraction_error", "error", variables={"error": str(error)})


    # ==============================================================================
    # 2. ASYNCHRONOUS TRANSLATION WORKER
    # ==============================================================================

    def start_full_translation(self) -> None:
        self.start_range_translation(None)

    def start_range_translation(self, range_str: Optional[str]) -> None:
        if not self._original_texts:
            self._send_toast("No translatable text elements found in this document.", "warning")
            return

        self.stop_translation()
        self._stop_translation = False

        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        target_pages: Optional[List[int]] = None
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
            if not target_pages:
                self._send_toast("Please enter a valid page range.", "warning")
                return

        # ── RE-TRANSLATION AND RESET CONFIRMATION LOGIC ──
        # Calculate untranslated segments targeting selected page boundaries
        untranslated_texts = {
            k: v for k, v in self._original_texts.items()
            if k not in self._translated_texts
        }
        if target_pages is not None:
            untranslated_texts = {
                k: v for k, v in untranslated_texts.items()
                if self._tid_to_page.get(k, 0) in target_pages
            }

        # If all pages in the selection are already translated, prompt the user
        if not untranslated_texts:
            user_confirmed = self._window.evaluate_js("confirm(Alpine.store('i18n').translate('retranslate_confirm_msg'))")
            
            if user_confirmed:
                # Clear translation caches in Python and reset DOM states instantly
                self.reset_all_translations()
                
                # Re-calculate untranslated blocks as full selections
                if target_pages is not None:
                    untranslated_texts = {
                        k: v for k, v in self._original_texts.items()
                        if self._tid_to_page.get(k, 0) in target_pages
                    }
                else:
                    untranslated_texts = self._original_texts.copy()
            else:
                self._send_status_i18n("status_export_cancelled")
                return

        # Start the background thread
        self._trans_thread = threading.Thread(
            target=self._run_translation,
            args=(untranslated_texts, target_pages),
            daemon=True
        )
        self._trans_thread.start()

    #
    def stop_translation(self) -> None:
        """
        Halts the active background translation thread and restores
        the currently translating page back to its waiting overlay state,
        exactly mirroring the Qt version's _on_translation_finished cancel branch.
        """
        self._stop_translation = True

        if self._trans_thread and self._trans_thread.is_alive():
            self._trans_thread.join(timeout=1.0)

        # Restore the page that was mid-translation back to its waiting state
        # This mirrors the Qt: if self._current_translating_page != -1: reset_page_to_waiting()
        current_page = getattr(self, "_current_translating_page", -1)
        if current_page != -1:
            self._send_js(
                f"window.dispatchEvent(new CustomEvent('reset-page', "
                f"{{ detail: {{ page: {current_page} }} }}))"
            )

        self._send_status_i18n("reset_success_msg")


    def reset_all_translations(self) -> None:
        """
        Clears local translation memory, resets DOM states to pristine English,
        resets the stop flag, and clears the progress panel.
        Mirrors the Qt version's _reset_translation_state() exactly:
        - self._translated_pages = {}
        - self._current_translating_page = -1
        - self.workspace_view.reset_translation_state()
        - self.progress_panel.clear()
        """
        # 1. Clear Python-side translation memory
        self._translated_texts = {}

        # 2. Reset stop flag so next translation starts cleanly
        self._stop_translation = False

        # 3. Reset current page tracker
        self._current_translating_page = -1

        # 4. Restore original English DOM in the workspace iframe
        self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-reset'))")

        # 5. Clear the progress panel bars and labels (mirrors progress_panel.clear())
        self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")

        self._send_status("Translation state reset cleanly.")


    def _run_translation(self, untranslated_texts: Dict[str, str], target_pages: Optional[List[int]]) -> None:
        try:
            self._send_status_i18n("status_trans_init")
            
            provider = config_db.get("APIConfig", "provider", "Google Gemini")
            keys_dict = config_db.get("APIConfig", "api_keys_by_provider", {})
            if isinstance(keys_dict, str):
                try:
                    keys_dict = json.loads(keys_dict)
                except Exception:
                    keys_dict = {}
            active_key = keys_dict.get(provider, "")

            config = DEFAULT_PROVIDERS[provider]
            fallback_model = config["models"][0]
            active_model = config_db.get("APIConfig", f"last_model_{provider}", fallback_model)

            llm_model_name = active_model
            prefix = config.get("prefix", "")
            if prefix and isinstance(prefix, str) and not llm_model_name.startswith(prefix):
                llm_model_name = f"{prefix}{llm_model_name}"

            use_custom_base = config_db.get("APIConfig", "use_custom_base", False)
            active_base_url = config_db.get("APIConfig", "custom_base_url", "") if use_custom_base else None

            if provider != "Ollama (Local)" and not active_key:
                self._send_toast_i18n("toast_trans_missing_key", "error", duration=8000, variables={"provider": provider})
                self._send_js("window.dispatchEvent(new CustomEvent('trigger-show-api-config'))")
                return

            client = LLMClient(
                model=llm_model_name,
                api_key=active_key,
                target_lang=config_db.get("SystemConfig", "target_lang", "French"),
                custom_base_url=active_base_url,
                all_keys=keys_dict,
                on_status=lambda msg: self._send_status(msg)
            )

            context_size = config_db.get("TranslationConfig", "sliding_context_size", 5)

            # Trigger unselected pages glass overlays hide immediately
            if target_pages is not None:
                total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
                unselected_pages = [p for p in range(total_pages) if p not in target_pages]
                if unselected_pages:
                    self._send_js(f"window.dispatchEvent(new CustomEvent('hide-glass-overlays', {{ detail: {{ pages: {unselected_pages} }} }}))")

            # Build optimized token batches
            self._send_status_i18n("status_trans_building_batches")
            batches = build_batches(untranslated_texts, llm_model_name)
            total_batches = len(batches)

            if not batches:
                self._send_status_i18n("status_trans_no_text")
                return

            # Initialize progress bar panel in JavaScript
            self._send_js(f"window.dispatchEvent(new CustomEvent('trigger-translation-start', {{ detail: {{ totalSegments: {len(untranslated_texts)}, totalPages: {total_pages if 'total_pages' in locals() else 1}, targetPages: {json.dumps(target_pages)} }} }}))")
            self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: 0, total: {total_batches} }} }}))")

            # ── INSTANTLY BYPASS FORMULAS AND DIGITS ──
            translatable_ids: Set[str] = set()
            for batch in batches:
                translatable_ids.update(batch.ids)
            
            skipped_ids = set(untranslated_texts.keys()) - translatable_ids
            logger.debug(f"Direct bypass triggered: {len(skipped_ids)} segments skipped.")
            
            for skipped_id in skipped_ids:
                orig_text = untranslated_texts[skipped_id]
                self._send_translation_stream(skipped_id, orig_text)
                self._translated_texts[skipped_id] = orig_text
            # ──────────────────────────────────────────

            sliding_context: List[str] = []
            current_translating_page = -1

            # Translate batches sequentially
            for idx, batch in enumerate(batches):
                if self._stop_translation:
                    break

                self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: {idx + 1}, total: {total_batches} }} }}))")
                self._send_status_i18n("status_trans_batch_progress", {"current": idx + 1, "total": total_batches})

                first_id = batch.segments[0]["id"]
                page_idx = self._tid_to_page.get(first_id, 0)
                if page_idx != current_translating_page:
                    current_translating_page = page_idx
                    self._current_translating_page = page_idx
                    self._send_js(f"window.dispatchEvent(new CustomEvent('prepare-page', {{ detail: {{ page: {page_idx} }} }}))")
                    self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-page', {{ detail: {{ page: {page_idx + 1} }} }}))")

                context_str = "\n".join(sliding_context) if sliding_context else None
                results = client.translate_batch(batch.segments, context=context_str)

                if self._stop_translation:
                    break

                if results is None:
                    self._send_toast_i18n("toast_api_connection_error", "error", duration=8000)
                    # self._send_toast("Connection failed. Check your API settings.", "error")
                
                    # Reset the page that was mid-translation back to waiting overlay
                    if current_translating_page != -1:
                        self._send_js(
                            f"window.dispatchEvent(new CustomEvent('reset-page', "
                            f"{{ detail: {{ page: {current_translating_page} }} }}))"
                        )
                    # Notify frontend that translation thread has stopped
                    self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
                    return

                # Stream translation segments sequentially
                for item in results:
                    seg_id = item.get("id")
                    translated_text = item.get("translated", "").strip()
                    
                    if seg_id and translated_text:
                        self._send_translation_stream(seg_id, translated_text)
                        self._translated_texts[seg_id] = translated_text
                        sliding_context.append(translated_text)

                if len(sliding_context) > context_size:
                    sliding_context = sliding_context[-context_size:]

            self._send_status("Document translation completed successfully.")
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
            self._send_toast_i18n("toast_trans_success", "success")

        except Exception as error:
            logger.error(f"Critical exception raised during background translation: {error}")
            self._send_status_i18n("status_trans_error", {"error": str(error)})
            self._send_toast_i18n("toast_trans_error", "error", duration=8000, variables={"error": str(error)})

            # Reset the page that was mid-translation back to waiting overlay
            # Mirrors Qt: if self._current_translating_page != -1: reset_page_to_waiting()
            if self._current_translating_page != -1:
                self._send_js(
                    f"window.dispatchEvent(new CustomEvent('reset-page', "
                    f"{{ detail: {{ page: {self._current_translating_page} }} }}))"
                )
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")



    def _send_translation_stream(self, trans_id: str, text: str):
        self._send_js("window.dispatchEvent(new CustomEvent('update-progress-segment'))")
        js_call = (
            f"window.dispatchEvent(new CustomEvent('stream-translation', {{ "
            f"detail: {{ id: '{trans_id}', text: {json.dumps(text)} }} "
            f"}}))"
        )
        self._send_js(js_call)

    def _parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        pages = set()
        parts = range_str.split(',')
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                sub_parts = part.split('-')
                if len(sub_parts) == 2:
                    try:
                        start_val = int(sub_parts[0].strip())
                        end_val = int(sub_parts[1].strip())
                        if 1 <= start_val <= max_pages and 1 <= end_val <= max_pages:
                            min_val = min(start_val, end_val)
                            max_val = max(start_val, end_val)
                            for p in range(min_val, max_val + 1):
                                pages.add(p - 1)
                    except ValueError:
                        continue
            else:
                try:
                    p = int(part)
                    if 1 <= p <= max_pages:
                        pages.add(p - 1)
                except ValueError:
                    continue
        return sorted(list(pages))

    # ── HELPER COMMUNICATION METHODS ──
    def _send_status(self, text: str):
        self._send_js(f"window.showStatusMessage({json.dumps(text)})")

    def _send_toast(self, message: str, type_str: str = "info", duration: int = 5000):
        """
        Sends a toast notification to the frontend UI.
        
        Args:
            message: The text to display in the toast card.
            type_str: Visual style type — 'info', 'success', 'warning', or 'error'.
            duration: Display duration in milliseconds (default: 5000ms).
        """
        self._send_js(f"window.showToast({json.dumps(message)}, '{type_str}', {duration})")

    def _send_js(self, js_code: str):
        if hasattr(self, "_window") and self._window:
            self._window.evaluate_js(js_code)
    
    def _send_status_i18n(self, key: str, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showStatusMessage_i18n('{key}', {json.dumps(variables or {})})")

    def _send_toast_i18n(self, key: str, type_str: str = "info", duration: int = 5000, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showToast_i18n('{key}', '{type_str}', {duration}, {json.dumps(variables or {})})")


    def _add_to_recent_files(self, file_path: str):
        try:
            recent_list = config_db.get("RecentFiles", "recent_list", [])
            if not isinstance(recent_list, list):
                recent_list = []

            abs_path = os.path.normpath(os.path.abspath(file_path))
            norm_target = os.path.normcase(abs_path)

            recent_list = [
                p for p in recent_list
                if os.path.normcase(os.path.normpath(p)) != norm_target
            ]

            recent_list.insert(0, abs_path)
            recent_list = recent_list[:20]

            config_db.set("RecentFiles", "recent_list", recent_list)
            self._send_js("window.dispatchEvent(new CustomEvent('refresh-menu-data'))")
        except Exception as e:
            print(f"[API] Error updating history registry: {e}")

    


     # ── EXPOSED PDF EXPORT ENDPOINT ──
    def export_translated_pdf(self) -> None:
        """
        Extracts the compiled translated DOM from the workspace frame,
        opens a native OS Save File dialog, and prints it into a high-fidelity
        vector PDF file using the resolved headless browser.
        """
        if not self._active_pdf_path or not self._window:
            self._send_toast_i18n("toast_export_no_doc", "warning")
            return

        self._send_status_i18n("status_export_requesting_layout")

        # 1. Extract the translated inner HTML directly from the active workspace iframe
        js_get_html = (
            "document.getElementById('html-iframe') ? "
            "document.getElementById('html-iframe').contentWindow.document.documentElement.outerHTML : ''"
        )
        translated_html = self._window.evaluate_js(js_get_html)

        if not translated_html:
            self._send_toast_i18n("toast_export_failed_extract", "error")
            return

        # 2. Offer a clean default filename matching the original PDF name
        original_name = os.path.basename(self._active_pdf_path)
        base_name, _ = os.path.splitext(original_name)
        suggested_name = f"{base_name}_translated.pdf"

        # 3. Trigger native OS file saving dialogues
        self._send_status_i18n("status_export_waiting_path")
        file_types = ("PDF Documents (*.pdf)", "All files (*.*)")
        destination_path = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            allow_multiple=False,
            file_types=file_types,
            save_filename=suggested_name
        )

        if not destination_path:
            self._send_status_i18n("status_export_cancelled")
            return

        # Handle formatting tuple returns on specific platforms
        if isinstance(destination_path, tuple) or isinstance(destination_path, list):
            if len(destination_path) > 0:
                destination_path = destination_path[0]
            else:
                return

        self._send_status_i18n("status_export_generating_pdf")

       
        # Resolve document page layout cm sizing
        try:
            metadata = get_pdf_metadata(self._active_pdf_path)
            page_size_raw = metadata.get("page_size", "")
     
            match = re.search(r'\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]', page_size_raw)
            page_size_css = f"{match.group(1)}cm {match.group(2)}cm" if match else "A4"
        except Exception:
            page_size_css = "A4"

        try:
            # 4. Write extracted DOM to a secure temporary HTML file on disk
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as temp_file:
                temp_file.write(translated_html)
                temp_html_path = temp_file.name

            # 5. Resolve our safe dual-layer browser print renderer
            browser_path = resolve_pdf_renderer()
            if not browser_path:
                self._send_toast_i18n("toast_export_no_chromium", "error")
                return

            # 6. Execute headless background print compiler
            success = print_html_to_vector_pdf(browser_path, temp_html_path, destination_path)

            # Clean temporary filesystem paths immediately
            try:
                os.unlink(temp_html_path)
            except OSError:
                pass

            if success:
                self._send_status_i18n("status_export_success", {"filename": os.path.basename(destination_path)})
                self._send_toast_i18n("toast_export_success", "success", duration=6000)
            else:
                self._send_toast_i18n("toast_export_failed", "error")
                self._send_status_i18n("status_export_failed")

        except Exception as e:
            logger.error(f"Error during PDF export pipeline: {e}")
            self._send_toast_i18n("toast_export_error", "error", variables={"error": str(e)})