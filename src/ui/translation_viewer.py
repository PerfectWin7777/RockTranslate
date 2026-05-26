# src/ui/translation_viewer.py

import os
import tempfile
from typing import List, Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl, QTimer  

from core.domain import FitzPage, FitzBlock
from reconstruction.html_builder import HTMLBuilder


import os

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = \
    "--enable-features=Translate"

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = \
    "--translate-script-url="

class TranslationViewer(QWidget):
    """
    The right pane UI component. Handles HTML page rendering, 
    frosted-glass overlays, real-time block updates, and synchronized zooming.
    """

    def __init__(self):
        super().__init__()
        self.pages: List[FitzPage] = []
        self.current_page_idx: int = 0
        self.is_translation_started: bool = False
        self.zoom_factor: float = 1.0

        self._document_ref = None
        self._tmp_html_path = None

        # self._refresh_timer = QTimer(self)
        # self._refresh_timer.setSingleShot(True)  # S'exécute une seule fois
        # self._refresh_timer.timeout.connect(self.refresh_view)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Initialize the Chromium web view
        self.web_view = QWebEngineView(self)
        
        # Configure local permissions and plugins
        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        layout.addWidget(self.web_view)

    def init_pages(self, pages: List[FitzPage], document=None):
        """
        Receives the extracted document pages and resets the translation state.
        The initial view displays page 1 with a frosted-glass overlay.
        """
        self.pages = pages
        self._document_ref = document  # Store document reference
        self.current_page_idx = 0
        self.is_translation_started = False
        self.refresh_view()

    def set_translation_started(self, started: bool = True):
        """
        Toggles the blurred layout overlay.
        When True, the frosted-glass effect is removed so translated text is visible.
        """
        self.is_translation_started = started
        self.refresh_view()

    def goto_page(self, page_index: int):
        """
        Switches the current view to a specific page index.
        """
        if 0 <= page_index < len(self.pages):
            self.current_page_idx = page_index
            self.refresh_view()

    def set_zoom(self, zoom_factor: float):
        """
        Applies a zoom scale to match the left original PDF view.
        """
        self.zoom_factor = zoom_factor
        self.web_view.setZoomFactor(zoom_factor)

    def update_block_translation(self, page_idx: int, block_idx: int, translated_text: str):
        """
        Updates a specific block's text and queues a delayed UI paint 
        to prevent event-loop choking.
        """
        if 0 <= page_idx < len(self.pages):
            page = self.pages[page_idx]
            for block in page.blocks:
                if block.block_id == block_idx:
                    block.translated_text = translated_text
                    bg_css = block.bg_color
                    break
            
            # Échappement JSON ultra-sécurisé pour éviter de casser la chaîne de caractères JS
            # (gère les sauts de ligne, les guillemets et les caractères d'échappement)
            import json
            safe_text = json.dumps(translated_text)
            
            # Appel chirurgical asynchrone dans Chromium
            js_code = f"updateBlock({page_idx}, {block_idx}, {safe_text}, '{bg_css}');"
            self.web_view.page().runJavaScript(js_code)


            # # Si l'utilisateur regarde cette page, on planifie un rafraîchissement
            # if page_idx == self.current_page_idx:
            #     # Si le timer tourne déjà, il est réinitialisé à 150ms.
            #     # Cela regroupe (batch) toutes les mises à jour en un seul rendu.
            #     self._refresh_timer.start(150)



    def refresh_view(self):
        if not self._document_ref:
            self.web_view.load(QUrl("about:blank"))
            return

        # Génère le HTML complet de tout le document
        html_content = HTMLBuilder.build_document(
            self._document_ref,
            show_blurred_overlay=not self.is_translation_started
        )

        # Écrit sur disque — pas de limite de taille
        if self._tmp_html_path and os.path.exists(self._tmp_html_path):
            try:
                os.unlink(self._tmp_html_path)
            except PermissionError:
                pass  # Chromium lit encore le fichier — on le laisse, l'OS le nettoiera

        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.html',
            encoding='utf-8', delete=False
        )
        tmp.write(html_content)
        tmp.close()
        self._tmp_html_path = tmp.name

        self.web_view.load(QUrl.fromLocalFile(self._tmp_html_path))


    def clear(self):
        """
        Resets and clears the viewer.
        """
        self.pages = []
        self.current_page_idx = 0
        self.is_translation_started = False
        self.web_view.load(QUrl("about:blank"))