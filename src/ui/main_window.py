# src/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QSplitter, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QStackedWidget, QPushButton, QComboBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QKeySequence, QAction
import fitz  # Import temporaire pour le worker de lecture

from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# Core & Layout Imports
from core.fitz_extractor import FitzExtractor
from core.table_detector import  page_has_table
from core.reading_order import ReadingOrderSorter
from core.domain import FitzDocument, FitzPage, FitzBlock
from core.reading_order import ReadingOrderSorter

# UI Imports
from ui.pdf_viewer import PDFViewer
from ui.translation_viewer import TranslationViewer
from ui.progress_panel import ProgressPanel

# Translation Helpers
from translation.chunker import build_batches, should_translate
from translation.llm_client import LLMClient

# ── Configuration Constants ──────────────────────────────────────────────────
SUPPORTED_MODELS = {
    "Google Gemini": [
        "gemini/gemini-3.1-flash-lite",
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.0-flash",
        "gemini/gemini-1.5-pro",
    ],
    "OpenAI": [
        "gpt-4o",
        "gpt-4o-mini",
    ],
    "Ollama (local)": [
        "ollama/mistral",
        "ollama/llama3",
    ]
}

LANGUAGES = [
    ("Français", "French"),
    ("Español", "Spanish"),
    ("English", "English"),
    ("Deutsch", "German"),
    ("العربية", "Arabic"),
    ("中文", "Chinese (Simplified)"),
    ("Português", "Portuguese"),
    ("Italiano", "Italian"),
    ("日本語", "Japanese"),
    ("Русский", "Russian"),
]

# Nombre de paragraphes traduits conservés comme contexte glissant inter-pages
_SLIDING_CONTEXT_SIZE = 10


class ExtractionWorker(QThread):
    """
    Extracts, renders, and sorts PDF pages in a background thread
    to keep the main window perfectly smooth and eliminate flickering.
    """
    progress = pyqtSignal(int, int)  # current_page, total_pages
    finished = pyqtSignal(object)    # Returns the populated FitzDocument
    error = pyqtSignal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            extractor = FitzExtractor(self.path)

            pdf = fitz.open(self.path)
            total_pages = len(pdf)

            doc = FitzDocument(path=self.path)

            for page_num in range(total_pages):
                page = pdf[page_num]

                # Blank out all words before rendering the background PNG
                for word in page.get_text("words"):
                    page.draw_rect(
                        fitz.Rect(word[0], word[1], word[2], word[3]),
                        color=(1, 1, 1), fill=(1, 1, 1)
                    )
                png_b64 = extractor._generate_page_image_b64(page)

                fitz_page = FitzPage(
                    number=page_num + 1,
                    width=page.rect.width,
                    height=page.rect.height,
                    blocks=[],
                    paths=[],
                    png_b64=png_b64
                )

                doc.pages.append(fitz_page)
                self.progress.emit(page_num + 1, total_pages)

            pdf.close()
            self.finished.emit(doc)
        except Exception as e:
            self.error.emit(str(e))


# ── Translation Thread Worker ───────────────────────────────────────────────
class TranslationWorker(QThread):
    """
    Handles API translation calls in the background.
    - Une seule passe page par page (extraction + traduction)
    - Contexte glissant : les N derniers paragraphes traduits sont passés
      au LLM pour assurer la cohérence terminologique inter-pages
    - Les erreurs rate-limit sont gérées silencieusement dans LLMClient ;
      seules les erreurs vraiment fatales remontent via error.emit()
    """
    block_done = pyqtSignal(int, int, int, str)  # page_idx, block_id, line_idx, translated
    batch_progress = pyqtSignal(int, int)        # batches_done, total_batches
    page_done      = pyqtSignal()               # une page entièrement traitée
    page_layout_ready = pyqtSignal(int)  # page_idx
    finished       = pyqtSignal()
    status_update  = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(
        self,
        blocks_to_translate,
        document: FitzDocument,
        extractor: FitzExtractor,
        model: str,
        api_key: str,
        target_lang: str,
    ):
        super().__init__()
        self.blocks        = blocks_to_translate
        self.document      = document
        self.extractor     = extractor
        self.model         = model
        self.api_key       = api_key
        self.target_lang   = target_lang
        self._stop         = False

    def run(self):
        try:
            pdf          = fitz.open(self.document.path)
            total_pages  = len(self.document.pages)
            sorter       = ReadingOrderSorter()

            client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                on_progress=lambda c, t: self.batch_progress.emit(c, t),
                on_status=lambda msg: self.status_update.emit(msg),
            )

            # ── Contexte glissant : derniers paragraphes traduits ─────────
            # On conserve les _SLIDING_CONTEXT_SIZE dernières traductions
            # pour les injecter dans le prochain batch et assurer la
            # cohérence terminologique et stylistique inter-pages.
            sliding_context: list[str] = []

            # ── Une seule passe : page par page ──────────────────────────
            for page_idx in range(total_pages):
                if self._stop:
                    break

                page_num = page_idx + 1
                page_obj = pdf[page_idx]

                self.status_update.emit(
                    f"Page {page_num}/{total_pages} : extraction en cours..."
                )

                # 1. Extract and sort the page
                fitz_page = self.extractor._extract_page(page_obj, page_num)

                fitz_page.blocks = sorter.process_page_layout(
                    fitz_page.blocks, fitz_page.width
                )

                self.document.pages[page_idx] = fitz_page

                self.page_layout_ready.emit(page_idx)

                # 2. Collect translatable lines (new unit — FitzLine, not FitzBlock)
                page_lines = [
                    (block, line_idx, line)
                    for block in fitz_page.blocks
                    if isinstance(block, FitzBlock)
                    for line_idx, line in enumerate(block.lines)
                    if should_translate(line)
                ]

                # On trie d'abord par position verticale (top), puis par position horizontale (left)
                page_lines.sort(key=lambda item: (item[2].top, item[2].left))
              

                if not page_lines:
                    self.page_done.emit()
                    continue

                # 3. Sliding context
                context_str: str | None = None
                if sliding_context:
                    context_str = "\n".join(sliding_context)

                # 4. Build batches and translate
                self.status_update.emit(
                    f"Page {page_num}/{total_pages} : traduction en cours..."
                )
                batches = build_batches(page_lines, self.model)

                for batch_idx, batch in enumerate(batches):
                    if self._stop:
                        break

                    self.batch_progress.emit(batch_idx + 1, len(batches))

                    batch_data = [
                        {"id": idx, "text": line.styled_text or line.text}
                        for idx, (block, line_idx, line) in enumerate(batch.lines)
                    ]
                    line_map = {
                        idx: (block, line_idx, line)
                        for idx, (block, line_idx, line) in enumerate(batch.lines)
                    }

                    ctx     = context_str if batch_idx == 0 else None
                    results = client._call_llm(batch_data, context=ctx)

                    if not results:
                        continue

                    # 5. Dispatch translations — one emit per line
                    for res in results:
                        idx        = res.get("id")
                        translated = res.get("translated", "").strip()
                        if idx in line_map and translated:
                            block, line_idx, line = line_map[idx]
                            line.translated_text = translated
                            self.block_done.emit(
                                page_idx, block.block_id, line_idx, translated
                            )

                            sliding_context.append(translated)

                    if len(sliding_context) > _SLIDING_CONTEXT_SIZE:
                        sliding_context = sliding_context[-_SLIDING_CONTEXT_SIZE:]

                self.page_done.emit()


            pdf.close()
            self.finished.emit()

        except Exception as e:
            err_msg = str(e).lower()
            import traceback
            traceback.print_exc()
            is_rate_limit = any(x in err_msg for x in [
                "rate_limit", "rate limit", "429", "overloaded",
                "resource_exhausted", "resource exhausted", "quota", "UNAVAILABLE"
            ])
            if is_rate_limit:
                # Ne remonte pas en QMessageBox — déjà géré dans LLMClient
                self.status_update.emit(
                    "⏳ Limite API atteinte — la traduction reprendra automatiquement."
                )
            else:
                # Erreur vraiment fatale → QMessageBox dans MainWindow
                self.error.emit(str(e))

    def stop(self):
        self._stop = True


# ── Welcome Dashboard (Drag & Drop Frame) ────────────────────────────────────
class WelcomeDashboard(QFrame):
    """
    Elegant landing screen displayed on startup.
    """
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("""
            WelcomeDashboard {
                background-color: #1e202c;
                border: 2px dashed #4f5b66;
                border-radius: 12px;
                margin: 40px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = QLabel("RockTranslate 1.0", self)
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Drag & Drop your scientific PDF here to begin", self)
        subtitle.setFont(QFont("Segoe UI", 12))
        subtitle.setStyleSheet("color: #a0aec0;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_status = QLabel(self)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._check_api_keys()

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self.lbl_status)

    def _check_api_keys(self):
        gemini = os.getenv("GEMINI_API_KEY")
        openai = os.getenv("OPENAI_API_KEY")
        if gemini or openai:
            self.lbl_status.setText("● API Key Detected (Zero-Config Ready)")
            self.lbl_status.setStyleSheet("color: #48bb78; font-weight: bold; font-size: 11px;")
        else:
            self.lbl_status.setText("○ No API Key Found (Please set GEMINI_API_KEY in your .env)")
            self.lbl_status.setStyleSheet("color: #f56565; font-size: 11px;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(".pdf"):
                self.file_dropped.emit(file_path)
                break


# ── MainWindow Orchestrator ──────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockTranslate")
        self.resize(1440, 900)

        self._pdf_path       = None
        self._document       = None
        self._worker         = None
        self._current_model  = SUPPORTED_MODELS["Google Gemini"][0]
        self._current_lang   = "French"
        self._zoom           = 1.0

        self._scroll_sync_timer = QTimer(self)
        self._scroll_sync_timer.setInterval(100)
        self._scroll_sync_timer.timeout.connect(self._sync_scroll_tick)

        self._build_menu()
        self._build_ui()

    def _build_ui(self):
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Page 0 : écran d'accueil
        self.welcome_screen = WelcomeDashboard(self)
        self.welcome_screen.file_dropped.connect(self._open_pdf_by_path)
        self.stacked_widget.addWidget(self.welcome_screen)

        # Page 1 : espace de travail
        workspace   = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)

        self.splitter   = QSplitter(Qt.Orientation.Horizontal)
        self.pdf_viewer = PDFViewer()
        self.trans_panel = TranslationViewer()

        self.splitter.addWidget(self.pdf_viewer)
        self.splitter.addWidget(self.trans_panel)
        self.splitter.setSizes([720, 720])
        work_layout.addWidget(self.splitter, 1)

        self.progress_panel = ProgressPanel()
        work_layout.addWidget(self.progress_panel)

        self.stacked_widget.addWidget(workspace)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready. Drop a PDF to begin.")

    def _build_menu(self):
        mb = self.menuBar()

        # ── Fichier ──
        m_file = mb.addMenu("Fichier")

        self.a_open = QAction("Ouvrir PDF…", self)
        self.a_open.setShortcut(QKeySequence("Ctrl+O"))
        self.a_open.triggered.connect(self._open_pdf_dialog)
        m_file.addAction(self.a_open)

        self.a_close = QAction("Fermer le document", self)
        self.a_close.setEnabled(False)
        self.a_close.triggered.connect(self._close_document)
        m_file.addAction(self.a_close)

        m_file.addSeparator()

        a_quit = QAction("Quitter", self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # ── Traduction ──
        m_trans = mb.addMenu("Traduction")

        self.a_start = QAction("▶  Démarrer la traduction", self)
        self.a_start.setShortcut(QKeySequence("Ctrl+Return"))
        self.a_start.setEnabled(False)
        self.a_start.triggered.connect(self._toggle_translation)
        m_trans.addAction(self.a_start)

        m_trans.addSeparator()

        m_lang = m_trans.addMenu("Langue cible")
        self._lang_actions = {}
        for display, code in LANGUAGES:
            a = QAction(display, self, checkable=True)
            a.setData(code)
            a.triggered.connect(self._on_lang_selected)
            if code == "French":
                a.setChecked(True)
            m_lang.addAction(a)
            self._lang_actions[code] = a

        m_model = m_trans.addMenu("Modèle LLM")
        self._model_actions = {}
        first = True
        for provider, models in SUPPORTED_MODELS.items():
            if not first:
                m_model.addSeparator()
            first = False
            title = QAction(f"── {provider} ──", self)
            title.setEnabled(False)
            m_model.addAction(title)

            for model in models:
                a = QAction(model, self, checkable=True)
                a.setData(model)
                a.triggered.connect(self._on_model_selected)
                if model == self._current_model:
                    a.setChecked(True)
                m_model.addAction(a)
                self._model_actions[model] = a

        # ── Affichage ──
        m_view = mb.addMenu("Affichage")

        a_zoom_in = QAction("Zoom +", self)
        a_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        m_view.addAction(a_zoom_in)

        a_zoom_out = QAction("Zoom −", self)
        a_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        m_view.addAction(a_zoom_out)

        a_zoom_reset = QAction("Zoom 100%", self)
        a_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        m_view.addAction(a_zoom_reset)

        a_zoom_in.triggered.connect(lambda: self._adjust_zoom(0.1))
        a_zoom_out.triggered.connect(lambda: self._adjust_zoom(-0.1))
        a_zoom_reset.triggered.connect(lambda: self._adjust_zoom(0.0))

        m_view.addSeparator()

        a_fullscreen = QAction("Plein écran", self, checkable=True)
        a_fullscreen.setShortcut(QKeySequence("F11"))
        m_view.addAction(a_fullscreen)

        # ── Aide ──
        m_help = mb.addMenu("Aide")

        a_about = QAction("À propos de RockTranslate", self)
        m_help.addAction(a_about)

        a_github = QAction("GitHub →", self)
        a_github.triggered.connect(
            lambda: __import__("webbrowser").open(
                "https://github.com/PerfectWin7777/RockTranslate"
            )
        )
        m_help.addAction(a_github)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", "", "PDF (*.pdf)")
        if path:
            self._open_pdf_by_path(path)

    def _open_pdf_by_path(self, path: str):
        self.status.showMessage("Analyse du document et extraction en cours...")
        self._pdf_path = path
        self.a_open.setEnabled(False)

        self._ext_worker = ExtractionWorker(path)
        self._ext_worker.progress.connect(self._on_extraction_progress)
        self._ext_worker.finished.connect(self._on_extraction_finished)
        self._ext_worker.error.connect(self._on_extraction_error)
        self._ext_worker.start()

    def _on_extraction_progress(self, current: int, total: int):
        self.status.showMessage(
            f"Analyse en cours : extraction de la page {current}/{total}..."
        )

    def _on_extraction_finished(self, document):
        self._document = document

        self.stacked_widget.setCurrentIndex(1)
        self.a_close.setEnabled(True)
        self.a_start.setEnabled(True)

         # 1. Chargement initial
        self.pdf_viewer.load_pdf(self._pdf_path) # Charge le vrai PDF Chrome
        self.trans_panel.init_pages(self._document.pages, self._document)

        # 2. Réinitialisation des variables de suivi
        self._last_trans_y = 0
        self._last_pdf_y = 0
        self._is_syncing_scroll = False
        
        # 3. Démarrage de la boucle de synchronisation de défilement
        self._scroll_sync_timer.start()

        self.status.showMessage(
            f"Chargement terminé : {os.path.basename(self._pdf_path)} "
            f"({len(self._document.pages)} pages)"
        )
        self.a_open.setEnabled(True)



    def _adjust_zoom(self, delta: float):
        """Ajuste le niveau de zoom de manière synchrone sur le PDF Chrome et le texte traduit."""
        if delta == 0.0:
            self._zoom = 1.0
        else:
            self._zoom = max(0.5, min(2.5, self._zoom + delta))
        
        self.pdf_viewer.set_zoom(self._zoom)
        self.trans_panel.set_zoom(self._zoom)
        self.status.showMessage(f"Zoom appliqué : {int(self._zoom * 100)}%")

    def _sync_scroll_tick(self):
        """Vérifie périodiquement si l'un des deux volets a défilé et synchronise l'autre."""
        if getattr(self, "_is_syncing_scroll", False):
            return

        # 1. On demande la position actuelle de la traduction (HTML classique)
        self.trans_panel.web_view.page().runJavaScript("window.scrollY", self._on_trans_scroll_received)

    def _on_trans_scroll_received(self, trans_y):
        if trans_y is None:
            return

        # Si la traduction a défilé de manière significative
        if abs(trans_y - getattr(self, "_last_trans_y", 0)) > 3:
            self._last_trans_y = trans_y
            self._is_syncing_scroll = True
            
            # On force le défilement du PDF Chrome via son Viewport interne
            js_scroll_pdf = f"if(window.viewer && window.viewer.viewport_) window.viewer.viewport_.position = {{x: 0, y: {trans_y}}};"
            self.pdf_viewer.view.page().runJavaScript(
                js_scroll_pdf, 
                lambda _: setattr(self, "_is_syncing_scroll", False)
            )
            return

        # 2. Si la traduction n'a pas bougé, on vérifie si le PDF Chrome a défilé
        js_get_pdf_y = "window.viewer && window.viewer.viewport_ ? window.viewer.viewport_.position.y : null"
        self.pdf_viewer.view.page().runJavaScript(js_get_pdf_y, self._on_pdf_scroll_received)

    def _on_pdf_scroll_received(self, pdf_y):
        if pdf_y is None:
            return

        # Si le PDF Chrome a défilé de manière significative
        if abs(pdf_y - getattr(self, "_last_pdf_y", 0)) > 3:
            self._last_pdf_y = pdf_y
            self._is_syncing_scroll = True
            
            # On force le défilement de la page traduite HTML
            self.trans_panel.web_view.page().runJavaScript(
                f"window.scrollTo(0, {pdf_y});",
                lambda _: setattr(self, "_is_syncing_scroll", False)
            )


    def _on_extraction_error(self, err_msg: str):
        QMessageBox.critical(
            self, "Erreur d'extraction",
            f"Impossible d'analyser le document :\n{err_msg}"
        )
        self._close_document()
        self.a_open.setEnabled(True)

    def _close_document(self):
 
        self._scroll_sync_timer.stop()

        self.pdf_viewer.clear()
        self.trans_panel.clear()
        self._pdf_path  = None
        self._document  = None
        self.a_close.setEnabled(False)
        self.a_start.setEnabled(False)
        self.stacked_widget.setCurrentIndex(0)
        self.status.showMessage("Document clos.")

    def _toggle_translation(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()
            self.a_start.setText("▶  Démarrer la traduction")
            return
        self._start_translation()

    def _start_translation(self):
        if not self._document:
            return

        api_key = (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        if not api_key and "ollama" not in self._current_model:
            QMessageBox.warning(
                self, "Configuration requise",
                "Clé API manquante dans votre environnement ou fichier .env"
            )
            return

        blocks_to_translate = [
            b for page in self._document.pages for b in page.blocks
        ]

        # Reset de la barre sur le nombre de pages
        self.progress_panel.reset(len(self._document.pages))

        self.trans_panel.set_translation_started(True)

        extractor = FitzExtractor(self._pdf_path)

        self._worker = TranslationWorker(
            blocks_to_translate,
            self._document,
            extractor,
            self._current_model,
            api_key,
            self._current_lang,
        )
        self._worker.block_done.connect(self._on_block_translated)
        self._worker.page_layout_ready.connect(self._on_page_layout_ready)
        self._worker.batch_progress.connect(self.progress_panel.set_batches)
        self._worker.finished.connect(self._on_translation_finished)
        self._worker.error.connect(self._on_translation_error)
        self._worker.page_done.connect(self.progress_panel.increment)
        self._worker.status_update.connect(self.status.showMessage)

        self.a_start.setText("⏹  Arrêter la traduction")
        self._worker.start()

    def _on_block_translated(self, page_idx: int, block_id: int, line_idx: int, translated_text: str):
            """
            Receives a translated line and forwards it to the TranslationViewer
            for surgical JS injection into Chromium.
            """
            if not (self._document and page_idx < len(self._document.pages)):
                return

            # Update the in-memory model
            # page = self._document.pages[page_idx]
            # for block in page.blocks:
            #     if block.block_id == block_id and hasattr(block, "lines"):
            #         for line in block.lines:
            #             if id(line) == line_idx:
            #                 line.translated_text = translated_text
            #                 break
            
            # Sync viewer pages with the document updated by the worker
            self.trans_panel.pages = self._document.pages

            # Forward to viewer for JS injection
            self.trans_panel.update_block_translation(
                page_idx, block_id, line_idx, translated_text
            )

    def _on_page_layout_ready(self, page_idx: int):
        """
        Appelé dès que la géométrie d'une page est extraite en mémoire.
        Met à jour les références et force l'affichage à dessiner les squelettes de cette page.
        """
        if self._document:
            # On synchronise les pages en mémoire
            self.trans_panel.pages = self._document.pages
            # On demande au visualiseur de recharger l'HTML complet
            # build_document() va dessiner instantanément tous les squelettes de la page extraite
            self.trans_panel.refresh_view()

    def _on_translation_finished(self):
        print("[TRANSLATION_FINISHED]")
        self.a_start.setText("▶  Démarrer la traduction")
        self.status.showMessage("Traduction terminée avec succès.")
        
        QMessageBox.information(self, "Terminé", "Le document a été entièrement traduit !")

    def _on_translation_error(self, err_msg: str):
        self.a_start.setText("▶  Démarrer la traduction")
        QMessageBox.critical(
            self, "Erreur",
            f"La traduction a été interrompue :\n{err_msg}"
        )

    def _on_lang_selected(self):
        a = self.sender()
        self._current_lang = a.data()
        for act in self._lang_actions.values():
            act.setChecked(False)
        a.setChecked(True)

    def _on_model_selected(self):
        a = self.sender()
        self._current_model = a.data()
        for act in self._model_actions.values():
            act.setChecked(False)
        a.setChecked(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())