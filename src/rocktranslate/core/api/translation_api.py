"""
RockTranslate — Asynchronous Extraction and Translation Web API Mixin
Path: src/rocktranslate/core/api/translation_api.py

Hosts background worker threads managing high-fidelity pdf2htmlEX parsing,
BeautifulSoup tag instrumentation, and eventually LiteLLM translation runs.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import json
import threading
import webview
from typing import Dict, List, Optional, Any
from loguru import logger

# Import your core layout-preserving parsing engines
from ..html_transformer import convert_pdf_to_html, instrument_html
from ..config_manager import config_db
from ..constants import DEFAULT_ASSETS_DIR


class TranslationApiMixin:
    """
    Mixin class driving the background document processing pipelines.
    Runs PyQt-free threading routines and communicates live with JS viewports.
    """
    def __init__(self) -> None:
        # In-memory session caches storing parsed text nodes for the translation pass
        self._active_pdf_path: Optional[str] = None
        self._active_html_path: Optional[str] = None
        self._original_texts: Dict[str, str] = {}
        self._tid_to_page: Dict[str, int] = {}

    def extract_pdf(self, file_path: str) -> None:
        """
        Triggers the asynchronous PDF-to-HTML conversion in a background thread.
        Invoked from JavaScript upon selecting or dropping a PDF file.
        """
        # Run as a background daemon thread to prevent freezing UI viewports
        thread = threading.Thread(
            target=self._run_extraction, 
            args=(file_path,), 
            daemon=True
        )
        thread.start()

    def _run_extraction(self, pdf_path: str) -> None:
        """
        Main execution loop for layout coordinates parsing and tag instrumentation.
        """
        try:
            self._send_status("High-fidelity PDF conversion in progress...")
            logger.info(f"Initiating background layout extraction for: {pdf_path}")

            # Thread-safe callback tracking pdf2htmlEX subprocess conversion cycles
            def on_pdf_progress(current: int, total: int):
                msg = f"Analyzing Document layout: Page {current}/{total}..."
                self._send_status(msg)

            # Resolve compiler asset paths override if configured
            assets_dir = config_db.get("SystemConfig", "pdf2htmlex_path_override", "")
            if not assets_dir or not os.path.exists(assets_dir):
                assets_dir = DEFAULT_ASSETS_DIR

            # Step A: Perform geometric HTML layout generation
            raw_html_path = convert_pdf_to_html(
                pdf_path,
                assets_dir,
                on_progress=on_pdf_progress
            )

            if not raw_html_path or not os.path.exists(raw_html_path):
                self._send_status("Geometric conversion by pdf2htmlEX failed.")
                self._send_toast("Geometric conversion by pdf2htmlEX failed.", "error")
                return

            self._send_status("Analyzing and instrumenting document...")
            logger.info("Executing BeautifulSoup semantic tag compilation...")

            # Step B: Inject translation tags and build translation coordinate mapping
            pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
            pdf_filename = os.path.basename(pdf_path)
            instrumented_html_path = os.path.join(
                pdf_dir,
                f"{os.path.splitext(pdf_filename)[0]}_workspace.html"
            )

            # Execute your highly-optimized BeautifulSoup DOM parser
            original_texts_map, tid_to_page = instrument_html(raw_html_path, instrumented_html_path)

            # Cache the extracted parameters in-memory on the API instance
            self._active_pdf_path = pdf_path
            self._active_html_path = instrumented_html_path
            self._original_texts = original_texts_map
            self._tid_to_page = tid_to_page

            # Save active page count in config_db for our dynamic Range Dialog selector
            total_pages = max(tid_to_page.values()) + 1 if tid_to_page else 1
            config_db.set("RecentFiles", "active_total_pages", total_pages)

            # Append the file path to recent history files list
            self._add_to_recent_files(pdf_path)

            self._send_status("Workspace configured successfully.")
            logger.info(f"Document successfully loaded: {total_pages} pages, {len(original_texts_map)} text segments.")

            # Step C: Dispatch completion event directly to JavaScript
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
            self._send_status(f"Extraction Error: {str(error)}")
            self._send_toast(f"Could not parse target document: {str(error)}", "error")

    # ── HELPER COMMUNICATION METHODS ──
    def _send_status(self, text: str):
        """Sends status text message to bottom bar in JS."""
        self._send_js(f"window.showStatusMessage({json.dumps(text)})")

    def _send_toast(self, message: str, type_str: str = "info"):
        """Pushes a temporary alert toast card in JS."""
        self._send_js(f"window.showToast({json.dumps(message)}, '{type_str}')")

    def _send_js(self, js_code: str):
        """Safely evaluates JavaScript inside the main browser page window."""
        if hasattr(self, "_window") and self._window:
            self._window.evaluate_js(js_code)

    def _add_to_recent_files(self, file_path: str):
        """Adds file path to history files registry safely."""
        try:
            recent_list = config_db.get("RecentFiles", "recent_list", [])
            if not isinstance(recent_list, list):
                recent_list = []

            abs_path = os.path.normpath(os.path.abspath(file_path))
            norm_target = os.path.normcase(abs_path)

            # Filter duplicates
            recent_list = [
                p for p in recent_list
                if os.path.normcase(os.path.normpath(p)) != norm_target
            ]

            # Prepend and limit size to 20
            recent_list.insert(0, abs_path)
            recent_list = recent_list[:20]

            config_db.set("RecentFiles", "recent_list", recent_list)
            
            # Fire refresh triggers to reload frontend dropdown menu cards
            self._send_js("window.dispatchEvent(new CustomEvent('refresh-menu-data'))")
        except Exception as e:
            print(f"[API] Error updating history registry: {e}")