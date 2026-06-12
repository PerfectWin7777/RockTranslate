"""
RockTranslate — Asynchronous Headless Chromium PDF Vector Exporter
Path: src/rocktranslate/ui_pyqt/utils/pdf_exporter.py

This module implements the high-fidelity PDF printing pipeline.
It extracts active translated DOM trees from the workspace viewer, writes 
them to standard temporary HTML nodes on disk, loads them in a headless 
Chromium instance, and exports print-ready vector PDF files.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import tempfile
from typing import Optional, Callable, Any
from PyQt6.QtCore import QObject, QUrl, QTimer
from PyQt6.QtWidgets import QWidget, QFileDialog, QMessageBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

# Safe fallback imports supporting both standard package modules and direct scripts
try:
    from src.rocktranslate.ui_pyqt.widget.workspace_viewer import WorkspaceViewer
except ImportError:
    from src.rocktranslate.ui_pyqt.widget.workspace_viewer import WorkspaceViewer


class PDFExporter(QObject):
    """
    Handles headless print-to-PDF asynchronous rendering, file selection dialogs,
    and temporary filesystem cleanup.
    """

    def __init__(
        self, 
        parent_widget: QWidget, 
        workspace_view: WorkspaceViewer,
        status_callback: Optional[Callable[[str], None]] = None
    ) -> None:
        """
        Initializes the PDF Exporter utility.

        Args:
            parent_widget: The parent QWidget window used to anchor dialogues and alerts.
            workspace_view: Active WorkspaceViewer viewport showing the translated DOM.
            status_callback: Optional callback to stream status logs (e.g. to status bars).
        """
        super().__init__(parent_widget)
        self.parent_widget: QWidget = parent_widget
        self.workspace_view: WorkspaceViewer = workspace_view
        self.status_callback: Optional[Callable[[str], None]] = status_callback
        
        # Asynchronous Chromium printing state machine variables
        self._print_view: Optional[QWebEngineView] = None
        self._temp_print_file: Optional[Any] = None

    def export_pdf(self, source_pdf_path: str) -> None:
        """
        Retrieves localized HTML, displays a file dialog, and triggers asynchronous printing.

        Args:
            source_pdf_path: The filesystem path of the original PDF document.
        """
        if not source_pdf_path:
            return

        # 1. Suggest a standardized output filename based on the original document
        original_filename: str = os.path.basename(source_pdf_path)
        base_name, extension = os.path.splitext(original_filename)
        suggested_filename: str = f"{base_name}_translated{extension}"

        default_dir: str = os.path.join(
            os.path.expanduser("~"), "Documents", suggested_filename
        )

        # 2. Display file dialog for the target export path
        destination_path, _ = QFileDialog.getSaveFileName(
            self.parent_widget,
            self.tr("Export Translated PDF"),
            default_dir,
            self.tr("PDF Documents (*.pdf)")
        )

        if not destination_path:
            return

        self._log_status(self.tr("Exporting translated vector PDF, please wait..."))

        # 3. Formulate the extraction JS query to retrieve translated HTML from the active frame
        js_get_translated_html: str = """
        (function() {
            var iframe = document.getElementById('html-iframe');
            if (iframe && iframe.contentWindow) {
                return iframe.contentWindow.document.documentElement.outerHTML;
            }
            return "";
        })();
        """

        # Asynchronous callback triggered when JavaScript finishes extracting the translated HTML
        def on_html_retrieved(translated_html: str) -> None:
            if not translated_html:
                self._log_status(self.tr("Error: Failed to retrieve translated document tree."))
                return

            try:
                # 4. Write the translated DOM into a temporary HTML template
                self._temp_print_file = tempfile.NamedTemporaryFile(
                    suffix=".html", delete=False, mode="w", encoding="utf-8"
                )
                self._temp_print_file.write(translated_html)
                self._temp_print_file.close()
            except Exception as e:
                self._log_status(self.tr("Error: Failed to write temporary files."))
                QMessageBox.critical(
                    self.parent_widget, 
                    self.tr("Export Failure"), 
                    f"{self.tr('Could not initialize temporary file write limits:')}\n{e}"
                )
                return

            # 5. Instantiate a headless Chromium page to run print actions
            self._print_view = QWebEngineView()
            self._print_view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
            )
            
            # Asynchronous callback when the headless page completes loading
            def on_load_finished(success: bool) -> None:
                if success and self._print_view:
                    self._log_status(self.tr("Generating final vector PDF layout..."))
                    # Execute Chromium print engine asynchronously
                    self._print_view.page().printToPdf(destination_path)
                else:
                    self._log_status(self.tr("Error: Headless document loading failed."))
                    self._cleanup_temp_resources()

            # Asynchronous callback when PDF printing finishes on disk
            def on_pdf_printed(printed_path: str) -> None:
                self._log_status(
                    self.tr("File exported successfully: {filename}").format(
                        filename=os.path.basename(printed_path)
                    )
                )
                QMessageBox.information(
                    self.parent_widget,
                    self.tr("Export Succeeded"),
                    f"{self.tr('The translated PDF was saved successfully at:')}\n{printed_path}"
                )
                self._cleanup_temp_resources()

            # Connect state triggers to the headless printing page
            self._print_view.loadFinished.connect(on_load_finished)
            self._print_view.page().pdfPrintingFinished.connect(on_pdf_printed)
            
            # Load the temporary HTML file to initiate the loop
            self._print_view.load(QUrl.fromLocalFile(self._temp_print_file.name))

        # Run extraction in the active frame and pipe results to callbacks
        self.workspace_view.page().runJavaScript(js_get_translated_html, on_html_retrieved)

    def _cleanup_temp_resources(self) -> None:
        """ Securely deletes temporary files and de-allocates headless memory slots. """
        if self._temp_print_file and os.path.exists(self._temp_print_file.name):
            try:
                os.unlink(self._temp_print_file.name)
            except OSError:
                pass
            self._temp_print_file = None
            
        self._print_view = None  # Releases headless browser allocation from memory

    def _log_status(self, message: str) -> None:
        """ Routes notification logs to active parent UI status slots. """
        if self.status_callback:
            self.status_callback(message)