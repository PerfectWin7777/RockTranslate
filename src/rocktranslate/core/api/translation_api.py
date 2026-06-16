"""
RockTranslate — Asynchronous Extraction and Translation Web API Mixin
Path: src/rocktranslate/core/api/translation_api.py

Hosts background worker threads managing high-fidelity pdf2htmlEX parsing,
BeautifulSoup tag instrumentation, and asynchronous LiteLLM streaming translations.
Provides robust thread synchronization, page-by-page progress validation, 
graceful error/cancel recoveries, and complete internationalization (i18n) support.

Author: RockTranslate Contributors
License: MIT License
Version: 1.1.0
"""

import os
import json
import threading
import tempfile
import re
from typing import Dict, List, Optional, Any, Set
from loguru import logger

import webview
from ..html_transformer import convert_pdf_to_html, instrument_html
from ..config_manager import config_db
from ..constants import DEFAULT_ASSETS_DIR, DEFAULT_PROVIDERS
from ..chunker import build_batches
from ..llm_client import LLMClient
from ..renderer import resolve_pdf_renderer, print_html_to_vector_pdf
from ..pdf_metadata import get_pdf_metadata


class TranslationApiMixin:
    """
    Mixin class driving background PDF layout parsing and LLM translation workers.
    Communicates dynamically with Alpine.js UI controllers using evaluate_js.
    """
    def __init__(self) -> None:
        # File paths tracking current active workspace files
        self._active_pdf_path: Optional[str] = None
        self._active_html_path: Optional[str] = None
        
        # Mapped original document data structures
        self._original_texts: Dict[str, str] = {}
        self._tid_to_page: Dict[str, int] = {}
        
        # Structured validation cache: { page_index: { segment_id: translated_text } }
        self._translated_pages: Dict[int, Dict[str, str]] = {}

        # Thread synchronization and cancel indicators
        self._stop_translation: bool = False
        self._current_translating_page: int = -1
        self._trans_thread: Optional[threading.Thread] = None
        
        # Mutual exclusion lock to prevent concurrent overlapping translation runs
        self._thread_lock = threading.Lock()

    # ==============================================================================
    # 1. BACKGROUND LAYOUT EXTRACTION WORKER
    # ==============================================================================

    # ==============================================================================
    # 1. BACKGROUND LAYOUT EXTRACTION WORKER
    # ==============================================================================

    def extract_pdf(self, file_path: str) -> None:
        """
        Launches a background daemon thread to convert, parse, and instrument
        the layout structure of a target PDF document. This prevents the main
        GUI thread from freezing during complex compilation runs.

        Args:
            file_path: Absolute filesystem path to the target PDF document.
        """
        thread = threading.Thread(
            target=self._run_extraction, 
            args=(file_path,), 
            daemon=True
        )
        thread.start()


    def _run_extraction(self, pdf_path: str) -> None:
        """
        Executes layout-preserving geometric extraction using local pdf2htmlEX engines,
        applies BeautifulSoup parsing to instrument the DOM tree, and updates
        the frontend viewport through state triggers.
        """
        try:
            # ── DEFENSIVE CHECK (Anti-Crash Guard for Drag and Drop Sandbox limits) ──
            if not pdf_path or not isinstance(pdf_path, str):
                logger.error("Extraction aborted: Received an invalid or empty file path (NoneType).")
                self._send_status_i18n("status_extraction_failed")
                self._send_toast_i18n("toast_extraction_failed", "error")
                # Cleanly return the UI state back to the welcome dashboard
                self._send_js("window.dispatchEvent(new CustomEvent('trigger-close-document'))")
                return

            self._send_status_i18n("status_extraction_start")
            logger.info(f"Initiating background layout extraction for: {pdf_path}")

            # Define a thread-safe progress report callback for pdf2htmlEX compilation
            def on_pdf_progress(current: int, total: int):
                self._send_status_i18n("status_extraction_pages", {"current": current, "total": total})

            # Check for custom system overrides, falling back to default directories
            assets_dir = str(config_db.get("SystemConfig", "pdf2htmlex_path_override", "") or "").strip()
            if not assets_dir or not os.path.exists(assets_dir):
                assets_dir = DEFAULT_ASSETS_DIR

            # Compile PDF to a temporary raw geometric HTML document
            raw_html_path = convert_pdf_to_html(pdf_path, assets_dir, on_progress=on_pdf_progress)

            if not raw_html_path or not os.path.exists(raw_html_path):
                self._send_status_i18n("status_extraction_failed")
                self._send_toast_i18n("status_extraction_failed", "error")
                return

            self._send_status_i18n("status_extraction_instrumenting")
            logger.info("Executing BeautifulSoup semantic tag compilation...")

            # Define and configure the final instrumented workspace output path
            pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
            pdf_filename = os.path.basename(pdf_path)
            instrumented_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_workspace.html")

            # Execute BeautifulSoup instrumentation and build translation mapping tables
            original_texts_map, tid_to_page = instrument_html(raw_html_path, instrumented_html_path)

            # Store fresh parsed states into the API session
            self._active_pdf_path = pdf_path
            self._active_html_path = instrumented_html_path
            self._original_texts = original_texts_map
            self._tid_to_page = tid_to_page
            
            # Wipes any active page cache for fresh documents
            self._translated_pages = {} 

            # Register document bounds into configurations and recent documents
            total_pages = max(tid_to_page.values()) + 1 if tid_to_page else 1
            config_db.set("RecentFiles", "active_total_pages", total_pages)
            self._add_to_recent_files(pdf_path)

            self._send_status_i18n("status_extraction_success")
            logger.info(f"Document successfully loaded: {total_pages} pages, {len(original_texts_map)} segments.")

            # Trigger workspace view transitions on the frontend Web SPA
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
        """
        Initiates a translation workflow spanning all pages of the document.
        """
        self.start_range_translation(None)

    def start_range_translation(self, range_str: Optional[str]) -> None:
        """
        Orchestrates page-range validation and begins the translation run.
        Assumes target checks have already been cleanly handled by the frontend.

        Args:
            range_str: Custom page range input parsed from UI dialogues (e.g., '1-3, 5').
        """
        if not self._original_texts:
            self._send_toast("No translatable text elements found in this document.", "warning")
            return

        # Secure Lock Check: Silently ignore start triggers if a thread is already running
        if not self._thread_lock.acquire(blocking=False):
            self._send_toast_i18n("status_trans_is_running", "warning")
            return
        self._thread_lock.release()

        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        target_pages: Optional[List[int]] = None
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
            if not target_pages:
                self._send_toast_i18n("enter_valid_page_range", "warning")
                return

        # Gather already translated IDs from page caches
        already_translated_ids = set()
        for page_data in self._translated_pages.values():
            already_translated_ids.update(page_data.keys())

        # Filter out segment IDs belonging to already translated blocks
        untranslated_texts = {
            k: v for k, v in self._original_texts.items()
            if k not in already_translated_ids
        }
        if target_pages is not None:
            untranslated_texts = {
                k: v for k, v in untranslated_texts.items()
                if self._tid_to_page.get(k, 0) in target_pages
            }

        # Safe fallback check if called with fully translated documents
        if not untranslated_texts:
            self._send_status_i18n("status_trans_completed")
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
            return

        self._stop_translation = False

        # Start the exclusive background processing thread
        self._trans_thread = threading.Thread(
            target=self._run_translation,
            args=(untranslated_texts, target_pages),
            daemon=True
        )
        self._trans_thread.start()


    def stop_translation(self, quiet: bool = False) -> None:
        """
        Halts the active background translation thread and restores the currently
        translating page back to its waiting state, preventing UI display freezes.

        Args:
            quiet: If True, halts the thread without overwriting the status bar message.
        """
        self._stop_translation = True

        if self._trans_thread and self._trans_thread.is_alive():
            self._trans_thread.join(timeout=1.0)

        # Restore the page that was mid-translation back to its waiting state
        current_page = self._current_translating_page
        if current_page != -1:
            self._send_js(
                f"window.dispatchEvent(new CustomEvent('reset-page', "
                f"{{ detail: {{ page: {current_page} }} }}))"
            )

        if not quiet:
            self._send_status_i18n("status_trans_cancelled")


    def reset_all_translations(self) -> None:
        """Wipes all active translation caches and resets state trackers."""
        self._stop_translation = False
        self._current_translating_page = -1
        self.reset_translation_range(None)
        self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")


    def _run_translation(self, untranslated_texts: Dict[str, str], target_pages: Optional[List[int]]) -> None:
        """
        Primary execution thread looping through batch allocations, managing sliding
        context boundaries, communicating results, and committing progress page-by-page.
        """
        # Acquire thread lock to enforce single-instance runs
        acquired = self._thread_lock.acquire(blocking=False)
        if not acquired:
            return

        try:
            self._send_status_i18n("status_trans_init")
            
            # Resolve AI provider configuration details
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
            total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
            if target_pages is not None:
                unselected_pages = [p for p in range(total_pages) if p not in target_pages]
                if unselected_pages:
                    self._send_js(f"window.dispatchEvent(new CustomEvent('hide-glass-overlays', {{ detail: {{ pages: {unselected_pages} }} }}))")

            # Build optimized token-budget batches
            self._send_status_i18n("status_trans_building_batches")
            batches = build_batches(untranslated_texts, llm_model_name)
            total_batches = len(batches)

            if not batches:
                self._send_status_i18n("status_trans_no_text")
                return

            # Retrieve count of segments already translated in other pages
            already_translated_count = 0
            for p_data in self._translated_pages.values():
                already_translated_count += len(p_data)

            # Initialize progress bar panels in Alpine.js
            self._send_js(f"window.dispatchEvent(new CustomEvent('trigger-translation-start', {{ detail: {{ totalSegments: {len(untranslated_texts)}, totalPages: {total_pages}, targetPages: {json.dumps(target_pages)} }} }}))")
            self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: 0, total: {total_batches} }} }}))")

            # Set segment count offset during translation resumption (Uplifting UX)
            if already_translated_count > 0:
                self._send_js(f"window.dispatchEvent(new CustomEvent('set-progress-segments', {{ detail: {{ done: {already_translated_count} }} }}))")

            # ── INSTANTLY BYPASS FORMULAS, NUMERICS, AND CITATIONS ──
            translatable_ids: Set[str] = set()
            for batch in batches:
                translatable_ids.update(batch.ids)
            
            skipped_ids = set(untranslated_texts.keys()) - translatable_ids
            logger.debug(f"Direct bypass triggered: {len(skipped_ids)} segments skipped.")
            
            # Map bypassed elements directly into page cache dictionary
            for skipped_id in skipped_ids:
                orig_text = untranslated_texts[skipped_id]
                self._send_translation_stream(skipped_id, orig_text)
                
                p_idx = self._tid_to_page.get(skipped_id, 0)
                if p_idx not in self._translated_pages:
                    self._translated_pages[p_idx] = {}
                self._translated_pages[p_idx][skipped_id] = orig_text
            # ──────────────────────────────────────────

            sliding_context: List[str] = []

            # Translate batches sequentially
            for idx, batch in enumerate(batches):
                if self._stop_translation:
                    break

                self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-batches', {{ detail: {{ done: {idx + 1}, total: {total_batches} }} }}))")
                self._send_status_i18n("status_trans_batch_progress", {"current": idx + 1, "total": total_batches})

                first_id = batch.segments[0]["id"]
                page_idx = self._tid_to_page.get(first_id, 0)
                
                if page_idx != self._current_translating_page:
                    self._current_translating_page = page_idx
                    self._send_js(f"window.dispatchEvent(new CustomEvent('prepare-page', {{ detail: {{ page: {page_idx} }} }}))")
                    self._send_js(f"window.dispatchEvent(new CustomEvent('update-progress-page', {{ detail: {{ page: {page_idx + 1} }} }}))")

                context_str = "\n".join(sliding_context) if sliding_context else None
                results = client.translate_batch(batch.segments, context=context_str)

                if self._stop_translation:
                    break

                if results is None:
                    self._send_toast_i18n("toast_api_connection_error", "error", duration=8000)
                    
                    # Reset the page that was mid-translation back to waiting overlay
                    if self._current_translating_page != -1:
                        self._send_js(
                            f"window.dispatchEvent(new CustomEvent('reset-page', "
                            f"{{ detail: {{ page: {self._current_translating_page} }} }}))"
                        )
                    # Notify frontend that thread completed
                    self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
                    return

                # Record results page-by-page and stream translations
                for item in results:
                    seg_id = item.get("id")
                    translated_text = item.get("translated", "").strip()
                    
                    if seg_id and translated_text:
                        self._send_translation_stream(seg_id, translated_text)
                        
                        p_idx = self._tid_to_page.get(seg_id, 0)
                        if p_idx not in self._translated_pages:
                            self._translated_pages[p_idx] = {}
                        self._translated_pages[p_idx][seg_id] = translated_text
                        
                        sliding_context.append(translated_text)

                if len(sliding_context) > context_size:
                    sliding_context = sliding_context[-context_size:]

            # ── SECURE INTERRUPT VERIFICATION ──
            # Prevents emission of standard success labels on cancelled runs
            if self._stop_translation:
                self._send_status_i18n("reset_success_msg")
                if self._current_translating_page != -1:
                    self._send_js(
                        f"window.dispatchEvent(new CustomEvent('reset-page', "
                        f"{{ detail: {{ page: {self._current_translating_page} }} }}))"
                    )
                return

            self._send_status("Document translation completed successfully.")
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
            self._send_toast_i18n("toast_trans_success", "success")

        except Exception as error:
            logger.error(f"Critical exception raised during background translation: {error}")
            self._send_status_i18n("status_trans_error", {"error": str(error)})
            self._send_toast_i18n("toast_trans_error", "error", duration=8000, variables={"error": str(error)})

            # Reset the page that was mid-translation back to waiting overlay
            if self._current_translating_page != -1:
                self._send_js(
                    f"window.dispatchEvent(new CustomEvent('reset-page', "
                    f"{{ detail: {{ page: {self._current_translating_page} }} }}))"
                )
            self._send_js("window.dispatchEvent(new CustomEvent('trigger-translation-finished'))")
            
        finally:
            # Enforce lock release regardless of crash outcomes
            self._thread_lock.release()

    def _send_translation_stream(self, trans_id: str, text: str):
        """
        Increments segment progress counters and streams single text allocations.
        """
        self._send_js("window.dispatchEvent(new CustomEvent('update-progress-segment'))")
        js_call = (
            f"window.dispatchEvent(new CustomEvent('stream-translation', {{ "
            f"detail: {{ id: '{trans_id}', text: {json.dumps(text)} }} "
            f"}}))"
        )
        self._send_js(js_call)
    

    def is_document_translated(self) -> bool:
        """
        Fast, non-blocking check returning True if all original text segments
        have already been translated in the active session.
        """
        if not self._original_texts:
            return False
        
        already_translated_ids = set()
        for page_data in self._translated_pages.values():
            already_translated_ids.update(page_data.keys())
            
        return len(already_translated_ids) >= len(self._original_texts)
    

    def is_range_translated(self, range_str: Optional[str]) -> bool:
        """
        Checks if any of the target pages in the range (or the entire document
        if range_str is None) have already been translated in the active session.
        """
        if not self._translated_pages:
            return False

        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
        else:
            target_pages = list(range(total_pages))

        for p_idx in target_pages:
            if p_idx in self._translated_pages and self._translated_pages[p_idx]:
                return True

        return False

    def reset_translation_range(self, range_str: Optional[str]) -> None:
        """
        Clears translation caches for the target range (or the entire document
        if range_str is None) and triggers selective DOM restoration in JS.
        """
        total_pages = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1
        
        if range_str:
            target_pages = self._parse_page_range(range_str, total_pages)
        else:
            target_pages = list(range(total_pages))

        for p_idx in target_pages:
            if p_idx in self._translated_pages:
                del self._translated_pages[p_idx]

        # Trigger DOM restoration on the frontend specifically for these pages
        self._send_js(
            f"window.dispatchEvent(new CustomEvent('trigger-translation-reset', "
            f"{{ detail: {{ pages: {target_pages} }} }}))"
        )
        self._send_status_i18n("status_trans_reset")



    def _parse_page_range(self, range_str: str, max_pages: int) -> List[int]:
        """
        Parses page ranges using commas, hyphens, and integer values.
        """
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
        Sends standard toast notifications.
        """
        self._send_js(f"window.showToast({json.dumps(message)}, '{type_str}', {duration})")

    def _send_js(self, js_code: str):
        """
        Sends a JavaScript command to the frontend.
        Gracefully ignores errors if the window is closing or already destroyed.
        """
        if hasattr(self, "_window") and self._window:
            try:
                self._window.evaluate_js(js_code)
            except Exception:
                # The window might be in the process of closing or already destroyed
                pass
    
    def _send_status_i18n(self, key: str, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showStatusMessage_i18n('{key}', {json.dumps(variables or {})})")

    def _send_toast_i18n(self, key: str, type_str: str = "info", duration: int = 5000, variables: Optional[dict] = None) -> None:
        self._send_js(f"window.showToast_i18n('{key}', '{type_str}', {duration}, {json.dumps(variables or {})})")

    def _add_to_recent_files(self, file_path: str):
        """
        Registers opened files to history.
        """
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
    
    def get_total_pages(self) -> int:
        """
        Returns the total number of pages in the currently active document.
        Exposed to the frontend range settings controller.
        """
        if hasattr(self, "_tid_to_page") and self._tid_to_page:
            return max(self._tid_to_page.values()) + 1
        return 1

        
    # ==============================================================================
    # 3. EXPOSED PDF EXPORT ENDPOINT
    # ==============================================================================

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

        # Extract translated HTML directly from workspace iframe
        js_get_html = (
            "document.getElementById('html-iframe') ? "
            "document.getElementById('html-iframe').contentWindow.document.documentElement.outerHTML : ''"
        )
        translated_html = self._window.evaluate_js(js_get_html)

        if not translated_html:
            self._send_toast_i18n("toast_export_failed_extract", "error")
            return

        # Offer default output filename
        original_name = os.path.basename(self._active_pdf_path)
        base_name, _ = os.path.splitext(original_name)
        suggested_name = f"{base_name}_translated.pdf"

        # Open native OS save file dialog
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

        # Support formatting tuples across platforms
        if isinstance(destination_path, tuple) or isinstance(destination_path, list):
            if len(destination_path) > 0:
                destination_path = destination_path[0]
            else:
                return

        self._send_status_i18n("status_export_generating_pdf")

        # Resolve page dimensions (cm layout rules)
        try:
            metadata = get_pdf_metadata(self._active_pdf_path)
            page_size_raw = metadata.get("page_size", "")
     
            match = re.search(r'\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]', page_size_raw)
            page_size_css = f"{match.group(1)}cm {match.group(2)}cm" if match else "A4"
        except Exception:
            page_size_css = "A4"

        # Write extracted DOM to temporary HTML on disk
        # Define physical document print margins layout rules
        page_size_style = f"""
        <style>
        @page {{
            size: {page_size_css};
            margin: 0;
        }}
        body {{
            margin: 0;
            padding: 0;
        }}
        </style>
        """
        
        # Inject physical layout boundaries to prevent Chromium from fallback-printing to default Letter size
        if "</head>" in translated_html:
            translated_html = translated_html.replace("</head>", f"{page_size_style}\n</head>")

        try:
            # 4. Write extracted DOM to a secure temporary HTML file on disk
            with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as temp_file:
                temp_file.write(translated_html)
                temp_html_path = temp_file.name

            # Resolve local browser printer
            browser_path = resolve_pdf_renderer()
            if not browser_path:
                self._send_toast_i18n("toast_export_no_chromium", "error")
                return

            # Print PDF vector
            success = print_html_to_vector_pdf(browser_path, temp_html_path, destination_path)

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


    
    def _cleanup_workspace_files(self) -> None:
        """
        Physically deletes temporary html workspace and raw layout files
        if the clear_cache_on_exit user setting is set to True.
        """
        if config_db.get("SystemConfig", "clear_cache_on_exit", True):
            # 1. Delete workspace HTML
            if self._active_html_path and os.path.exists(self._active_html_path):
                try:
                    os.remove(self._active_html_path)
                    logger.info(f"Cleaned up temporary workspace HTML: {self._active_html_path}")
                except OSError as e:
                    logger.warning(f"Could not delete temporary workspace file: {e}")
            
            # 2. Delete raw HTML compiled by pdf2htmlEX
            if self._active_pdf_path:
                pdf_dir = os.path.dirname(os.path.abspath(self._active_pdf_path))
                pdf_filename = os.path.basename(self._active_pdf_path)
                raw_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_raw.html")
                if os.path.exists(raw_html_path):
                    try:
                        os.remove(raw_html_path)
                        logger.info(f"Cleaned up raw HTML layout file: {raw_html_path}")
                    except OSError as e:
                        logger.warning(f"Could not delete raw HTML file: {e}")

    
    def close_document(self) -> None:
        """
        Safely stops any active threads, purges temporary cache files
        if requested, and resets the document state registers.
        """
        self.stop_translation()
        self._cleanup_workspace_files()
        
        # Reset local document states
        self._active_pdf_path = None
        self._active_html_path = None
        self._original_texts = {}
        self._tid_to_page = {}
        self._translated_pages  = {}
        self._send_status_i18n("status_ready")