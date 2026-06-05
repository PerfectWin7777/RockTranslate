# src/ui/translation_viewer.py

import json
import os
import tempfile
from typing import List, Optional
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl

from core.domain import FitzPage, FitzBlock
from reconstruction.html_builder import HTMLBuilder


os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--translate-script-url="


class TranslationViewer(QWidget):
    """
    Panneau droit — rendu HTML pixel-perfect du document traduit.

    Gestion du cycle de chargement Chromium :
    - Quand loadStarted fire, on passe en mode "loading" et on met les
      appels JS en file d'attente (_pending_js).
    - Quand loadFinished fire, on vide la file d'attente dans Chromium.
    Cela évite que les premières traductions arrivent avant que la page
    soit prête et tombent dans le vide.
    """

    def __init__(self):
        super().__init__()
        self.pages: List[FitzPage] = []
        self.current_page_idx: int = 0
        self.is_translation_started: bool = False
        self.zoom_factor: float = 1.0

        self._document_ref   = None
        self._tmp_html_path  = None

        # File d'attente JS pour les appels arrivant pendant le chargement
        self._pending_js: list[str] = []
        self._page_loading: bool    = False

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.web_view = QWebEngineView(self)

        settings = self.web_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        # Suivi du cycle de chargement pour la file d'attente JS
        self.web_view.loadStarted.connect(self._on_load_started)
        self.web_view.loadFinished.connect(self._on_load_finished)

        layout.addWidget(self.web_view)

    # ── Cycle de chargement ──────────────────────────────────────────────────

    def _on_load_started(self):
        self._page_loading = True
        print(f"[LOAD_STARTED] url={self.web_view.url().toString()}")
        # self._pending_js.clear()  # La page repart de zéro, on vide l'ancienne file

    def _on_load_finished(self, ok: bool):
        self._page_loading = False
        print(f"[LOAD_FINISHED] url={self.web_view.url().toString()}")
        # Injecte tous les appels JS mis en attente pendant le chargement
        for js in self._pending_js:
            self.web_view.page().runJavaScript(js)
        self._pending_js.clear()

    def _run_js(self, js: str):
        """
        Exécute du JS immédiatement si Chromium est prêt,
        sinon le met en file d'attente.
        """
        # print(f"[RUN_JS] loading={self._page_loading} js={js[:60]}")

        if self._page_loading:
            self._pending_js.append(js)
        else:
            self.web_view.page().runJavaScript(js)

    # ── API publique ─────────────────────────────────────────────────────────

    def init_pages(self, pages: List[FitzPage], document=None):
        """
        Reçoit les pages extraites et initialise l'état de traduction.
        L'overlay frosted-glass est actif au départ.
        """
        self.pages           = pages
        self._document_ref   = document
        self.current_page_idx = 0
        self.is_translation_started = False
        self.refresh_view()

    def set_translation_started(self, started: bool = True):
        """
        Retire l'overlay flou et rend les blocs traduits visibles au fur et à mesure.
        """
        print(f"[SET_TRANSLATION_STARTED] started={started}")
        self.is_translation_started = started
        # if started:
        #     self._run_js(
        #         "document.querySelectorAll('.glass-overlay').forEach(e=>e.remove());"
        #         "document.querySelectorAll('.blurred-layout').forEach(e=>e.classList.remove('blurred-layout'));"
        #     )
        # else:
        self.refresh_view()

    def goto_page(self, page_index: int):
        if 0 <= page_index < len(self.pages):
            self.current_page_idx = page_index
            self.refresh_view()

    def set_zoom(self, zoom_factor: float):
        self.zoom_factor = zoom_factor
        self.web_view.setZoomFactor(zoom_factor)

    def update_block_translation(
    self, page_idx: int, block_id: int, line_idx: int, translated_text: str
):
        """
        Receives a translated line and injects its div directly into Chromium.
        Finds the exact FitzLine by block_id + line_id (Python object id).
        """
        if not (0 <= page_idx < len(self.pages)):
           return

        page = self.pages[page_idx]

        # Find block by block_id
        target_block = None
        for block in page.blocks:
            if block.block_id == block_id and hasattr(block, "lines"):
                target_block = block
                break

        if not target_block or line_idx >= len(target_block.lines):
            return

        # Get line by stable index
        target_line = target_block.lines[line_idx]
        target_line.translated_text = translated_text

        col_left_max, col_right_min, page_right_max = HTMLBuilder._compute_column_boundaries(
            page.blocks, page.width
        )

        line_html = HTMLBuilder._generate_line_div(
            line=target_line,
            block=target_block,
            page_width=page.width,
            col_left_max=col_left_max,
            col_right_min=col_right_min,
            page_right_max=page_right_max,
            page_idx=page_idx,
            show_skeletons=self.is_translation_started, # Conserve l'état squelette pour les autres lignes
        )

        safe_html = json.dumps(line_html)
        js_code   = f"updateBlock({page_idx}, {block_id}, {line_idx}, {safe_html});"
        self._run_js(js_code)
    

    def refresh_view(self):
       
        # if self.is_translation_started:  # ← garde de sécurité
        #    return
        if not self._document_ref:
            self.web_view.load(QUrl("about:blank"))
            return

        html_content = HTMLBuilder.build_document(
            self._document_ref,
            show_blurred_overlay=not self.is_translation_started,
            show_skeletons=self.is_translation_started
        )

        # Nettoyage de l'ancien fichier temporaire
        if self._tmp_html_path and os.path.exists(self._tmp_html_path):
            try:
                os.unlink(self._tmp_html_path)
            except PermissionError:
                pass  # Chromium lit encore le fichier — l'OS le nettoiera

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", encoding="utf-8", delete=False
        )
        tmp.write(html_content)
        tmp.close()
        self._tmp_html_path = tmp.name

        self.web_view.load(QUrl.fromLocalFile(self._tmp_html_path))

    def clear(self):
        self.pages                  = []
        self.current_page_idx       = 0
        self.is_translation_started = False
        self._pending_js.clear()
        self.web_view.load(QUrl("about:blank"))