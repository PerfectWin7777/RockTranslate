# src/ui/pdf_viewer.py

import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl, pyqtSignal


class PDFViewer(QWidget):
    """
    High-performance PDF Viewer utilizing the native Chromium engine.
    Allows text selection, zooming, copying, and native browser controls.
    """

    page_changed = pyqtSignal(int)  # Maintained for main_window compatibility

    def __init__(self):
        super().__init__()
        self.total_pages = 0
        self._current_path = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Initialize the Chromium web view
        self.view = QWebEngineView(self)
        
        # Enable PDF viewing and plugins in Chromium settings
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        layout.addWidget(self.view)

    def load_pdf(self, path: str, zoom: float = 1.0):
        """
        Loads the local PDF file directly into Chromium's PDF engine.
        """
        if not os.path.exists(path):
            raise FileNotFoundError(f"PDF file not found at: {path}")

        self._current_path = os.path.abspath(path)
        
        # Convert local system path to a proper file:// QUrl
        file_url = QUrl.fromLocalFile(self._current_path)
        self.view.load(file_url)

    def set_zoom(self, zoom_factor: float):
        """
        Sets the zoom factor of the WebEngine page (1.0 is 100%).
        """
        self.view.setZoomFactor(zoom_factor)

    def clear(self):
        """
        Clears the viewer by loading a blank page.
        """
        self.view.load(QUrl("about:blank"))
        self._current_path = None

    def get_current_page_idx(self) -> int:
        """
        Placeholder index to keep compatibility with main_window.
        Chromium's PDF reader handles navigation internally.
        """
        return 0

    def goto_page(self, page_index: int):
        """
        Navigates to a specific page.
        """
        # Chromium's native viewer manages scrolling internally.
        pass