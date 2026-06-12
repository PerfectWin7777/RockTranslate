"""
RockTranslate — Background Thread PDF Extractor and Instrumenter
Path: src/rocktranslate/ui_pyqt/workers/extraction_worker.py

This module implements the background processing thread (QThread) responsible
for executing pdf2htmlEX conversion and geometry-based BeautifulSoup packaging
without locking the main UI execution loops.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
from typing import Dict, Tuple
from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

# Safe imports supporting both standalone package modules and direct scripts
from ...core.constants import DEFAULT_ASSETS_DIR
from ...core.html_transformer import convert_pdf_to_html, instrument_html


class ExtractionWorker(QThread):
    """
    Asynchronous background worker thread executing layout conversions 
    and BeautifulSoup semantic instrumentation on PDF documents.
    """
    # UI status updates message signals (e.g., progress bar text)
    status_update = pyqtSignal(str)
    
    # Live page conversion counts (emits: active_page, total_pages)
    extraction_progress = pyqtSignal(int, int)
    
    # Successful completion output (emits: workspace_html_path, original_texts_map, tid_to_page_map)
    finished = pyqtSignal(str, dict, dict)
    
    # Critical extraction failure emission signals
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str, assets_dir: str = DEFAULT_ASSETS_DIR) -> None:
        """
        Initializes the background worker thread.

        Args:
            pdf_path: The filesystem path to the target PDF file.
            assets_dir: Assets folder storing the external pdf2htmlEX compiler.
        """
        super().__init__()
        self.pdf_path: str = pdf_path
        self.assets_dir: str = assets_dir

    def run(self) -> None:
        """
        Executes high-fidelity PDF-to-HTML compilation and runs geometric DOM
        restructuring. Emmits progressive state updates to the main thread.
        """
        try:
            self.status_update.emit(self.tr("High-fidelity PDF conversion in progress..."))
            logger.info(f"Initiating background layout extraction for: {self.pdf_path}")

            # Thread-safe conversion progress callback pipeline
            def on_pdf_progress(current: int, total: int) -> None:
                self.extraction_progress.emit(current, total)
            
            # Step A: Perform geometric HTML layout generation using compiled local engine
            raw_html_path: str = convert_pdf_to_html(
                self.pdf_path, 
                self.assets_dir, 
                on_progress=on_pdf_progress
            )
            
            if not raw_html_path or not os.path.exists(raw_html_path):
                self.error.emit(self.tr("Geometric conversion by pdf2htmlEX failed."))
                return

            self.status_update.emit(self.tr("Analyzing and instrumenting document..."))
            logger.info("Executing BeautifulSoup semantic tag compilation...")
            
            # Step B: Inject translation tags and build translation coordinate mapping
            pdf_dir: str = os.path.dirname(os.path.abspath(self.pdf_path))
            pdf_filename: str = os.path.basename(self.pdf_path)
            instrumented_html_path: str = os.path.join(
                pdf_dir, 
                f"{os.path.splitext(pdf_filename)[0]}_workspace.html"
            )
            
            original_texts_map, tid_to_page = instrument_html(raw_html_path, instrumented_html_path)
            
            self.status_update.emit(self.tr("Workspace configured successfully."))
            self.finished.emit(instrumented_html_path, original_texts_map, tid_to_page)

        except Exception as e:
            logger.error(f"Critical exception raised during background document processing: {e}")
            self.error.emit(str(e))