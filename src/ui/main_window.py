# src/ui/main_window.py

import os
import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QSplitter, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QStackedWidget, QPushButton, QComboBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QAction
import fitz  # Import temporaire pour le worker de lecture

from dotenv import load_dotenv

# Charge les variables du fichier .env
load_dotenv()

# Core & Layout Imports
from core.fitz_extractor import FitzExtractor, page_has_table_lines 
from core.reading_order import ReadingOrderSorter
from core.domain import FitzDocument
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
            # Initialize Extractor and Sorter
            extractor = FitzExtractor(self.path)
            sorter = ReadingOrderSorter()
            
            # Open PDF in background thread
            pdf = fitz.open(self.path)
            total_pages = len(pdf)
            
            doc = FitzDocument(path=self.path)

            for page_num in range(total_pages):
                # 1. Extract raw blocks, paths, and generate base64 PNG
                page = pdf[page_num]
                fitz_page = extractor._extract_page(page, page_num + 1, extract_tables=False)
                
                # 2. Sort the reading order on the fly in the background
                fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)
                
                doc.pages.append(fitz_page)
                self.progress.emit(page_num + 1, total_pages)

            pdf.close()
            self.finished.emit(doc)
        except Exception as e:
            self.error.emit(str(e))



# ── Translation Thread Worker ───────────────────────────────────────────────
class TranslationWorker(QThread):
    """
    Handles API translation calls in the background to keep the UI perfectly responsive.
    Emits granular real-time block updates.
    """
    block_done = pyqtSignal(int, int, str)  # page_idx, block_idx, translated_text
    batch_progress = pyqtSignal(int, int)   # batches_done, total_batches
    finished = pyqtSignal()
    status_update = pyqtSignal(str)   # Informative feedback for status bar
    error = pyqtSignal(str)

    def __init__(self, blocks_to_translate,
                       document: FitzDocument, 
                       extractor: FitzExtractor, 
                       model: str, api_key: str, target_lang: str
                ):
        super().__init__()
        self.blocks = blocks_to_translate
        self.document = document
        self.extractor = extractor
        self.model = model
        self.api_key = api_key
        self.target_lang = target_lang
        self._stop = False

    def run(self):
        try:
            # We filter out noise (formulas, URLs, empty blocks) using our chunker logic
            valid_blocks = [b for b in self.blocks if should_translate(b)]
            
            # Map valid blocks to sequential tasks for the API
            tasks = [{"id": idx, "text": b.text, "block_ref": b} for idx, b in enumerate(valid_blocks)]

            # Open PDF in background thread
            pdf = fitz.open(self.document.path)
            total_pages = len(self.document.pages)

           
            client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                on_progress=lambda c, t: self.batch_progress.emit(c, t)
            )
            
            # Traitement page par page
            for page_idx in range(len(self.document.pages)):
                if self._stop:
                    break

                page_num = page_idx + 1
                page_obj = pdf[page_idx]

                # 1. Vérification rapide : y a-t-il un tableau potentiel sur cette page ?
                has_tables = page_has_table_lines(page_obj)

                if has_tables:
                    self.status_update.emit(f"Page {page_num}/{total_pages} : Extraction de la structure des tableaux...")
                    # On relance l'extraction en activant l'extracteur lourd uniquement sur cette page !
                    fitz_page = self.extractor._extract_page(page_obj, page_num, extract_tables=True)
                    
                    # On ré-applique l'ordre de lecture
                    
                    sorter = ReadingOrderSorter()
                    fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)
                    
                    # On remplace la page d'origine par la page enrichie de ses tableaux
                    self.document.pages[page_idx] = fitz_page
                else:
                    self.status_update.emit(f"Page {page_num}/{total_pages} : Analyse du texte...")
                    fitz_page = self.document.pages[page_idx]

                # 2. Collecte des blocs à traduire de cette page
                page_blocks = [b for b in fitz_page.blocks if should_translate(b)]
                if not page_blocks:
                    continue

                # 3. Traduction de la page
                self.status_update.emit(f"Page {page_num}/{total_pages} : Traduction des paragraphes...")
                batches = build_batches(page_blocks, self.model)


            # Build batches using our token estimation model
            batches = build_batches(valid_blocks, self.model)

            for i, batch in enumerate(batches):
                if self._stop:
                    break

                # Emission de la progression de batch de l'UI
                self.batch_progress.emit(i + 1, len(batches))

                # Prepare payload
                batch_data = []
                # Map batch blocks back to our task references
                block_map = {}
                for idx, block in enumerate(batch.paragraphs):
                    batch_data.append({"id": idx, "text": block.text})
                    block_map[idx] = block

                # Translate batch using the client
                results = client._call_llm(batch_data)
                if not results:
                    raise Exception(f"Failed to translate batch {i+1}")

                # Dispatch translations back to the UI in real-time
                for res in results:
                    idx = res.get("id")
                    translated = res.get("translated", "").strip()
                    if idx in block_map and translated:
                        block = block_map[idx]
                        page_idx = block.page_number - 1
                        self.block_done.emit(page_idx, block.block_id, translated)
            
            pdf.close()
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._stop = True


# ── Welcome Dashboard (Drag & Drop Frame) ────────────────────────────────────
class WelcomeDashboard(QFrame):
    """
    Elegant landing screen displayed on startup. Handles PDF drops and basic language settings.
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

        # Status Dot (Zero-Config verification)
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

        self._pdf_path = None
        self._document = None
        self._worker = None
        
        # Default options
        self._current_model = SUPPORTED_MODELS["Google Gemini"][1]
        self._current_lang = "French"
        self._zoom = 1.0

        self._build_menu()
        self._build_ui()

    def _build_ui(self):
        # We use a Stacked Widget to support Page 0 (Dashboard) and Page 1 (Workspace)
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Page 0: Welcome dashboard
        self.welcome_screen = WelcomeDashboard(self)
        self.welcome_screen.file_dropped.connect(self._open_pdf_by_path)
        self.stacked_widget.addWidget(self.welcome_screen)

        # Page 1: Main workspace
        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)

        # Splitter Left (Original Chromium PDF) / Right (HTML Translation layer)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.pdf_viewer = PDFViewer()
        self.trans_panel = TranslationViewer()
        
        self.splitter.addWidget(self.pdf_viewer)
        self.splitter.addWidget(self.trans_panel)
        self.splitter.setSizes([720, 720])
        work_layout.addWidget(self.splitter, 1)

        # Real-time progress tracker panel
        self.progress_panel = ProgressPanel()
        work_layout.addWidget(self.progress_panel)

        self.stacked_widget.addWidget(workspace)

        # Status Bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready. Drop a PDF to begin.")

    def _build_menu(self):
        mb = self.menuBar()

        # ── Fichier ──
        m_file = mb.addMenu("Fichier")
        
        a_open = QAction("Ouvrir PDF…", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_pdf_dialog)
        m_file.addAction(a_open)

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

        # Target Language Menu
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

        # LLM Model Menu
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
    
    # ── Affichage ─────────────────────────────────────────
        m_view = mb.addMenu("Affichage")

        a_zoom_in = QAction("Zoom +", self)
        a_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        # a_zoom_in.triggered.connect(self._zoom_in)
        m_view.addAction(a_zoom_in)

        a_zoom_out = QAction("Zoom −", self)
        a_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        # a_zoom_out.triggered.connect(self._zoom_out)
        m_view.addAction(a_zoom_out)

        a_zoom_reset = QAction("Zoom 100%", self)
        a_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        # a_zoom_reset.triggered.connect(self._zoom_reset)
        m_view.addAction(a_zoom_reset)

        m_view.addSeparator()

        a_fullscreen = QAction("Plein écran", self, checkable=True)
        a_fullscreen.setShortcut(QKeySequence("F11"))
        # a_fullscreen.triggered.connect(self._toggle_fullscreen)
        m_view.addAction(a_fullscreen)

        # ── Aide ──────────────────────────────────────────────
        m_help = mb.addMenu("Aide")

        a_about = QAction("À propos de RockTranslate", self)
        # a_about.triggered.connect(self._show_about)
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

        # Disable main thread actions during transition
        self.a_open.setEnabled(False) if hasattr(self, 'a_open') else None

        # Start background extraction thread
        self._ext_worker = ExtractionWorker(path)
        self._ext_worker.progress.connect(self._on_extraction_progress)
        self._ext_worker.finished.connect(self._on_extraction_finished)
        self._ext_worker.error.connect(self._on_extraction_error)
        self._ext_worker.start()
    
    def _on_extraction_progress(self, current: int, total: int):
        self.status.showMessage(f"Analyse en cours : extraction de la page {current}/{total}...")

    def _on_extraction_finished(self, document):
        self._document = document
        
        # 1. On affiche d'abord l'espace de travail (les widgets prennent leurs dimensions réelles)
        self.stacked_widget.setCurrentIndex(1)
        self.a_close.setEnabled(True)
        self.a_start.setEnabled(True)

        # 2. On charge ensuite les documents (Chromium effectue le rendu instantanément !)
        self.pdf_viewer.load_pdf(self._pdf_path)
        self.trans_panel.init_pages(self._document.pages, self._document)
        self.pdf_viewer.view.loadFinished.connect(self._sync_page)

        self.status.showMessage(f"Chargement terminé : {os.path.basename(self._pdf_path)} ({len(self._document.pages)} pages)")
        
        # Re-enable standard menu controls
        self.a_open.setEnabled(True) if hasattr(self, 'a_open') else None


    def _sync_page(self, ok):
        # todo : Pour l'instant goto page 0 — on affinera la sync scroll plus tard
        self.trans_panel.goto_page(0)

    def _on_extraction_error(self, err_msg: str):
        QMessageBox.critical(self, "Erreur d'extraction", f"Impossible d'analyser le document :\n{err_msg}")
        self._close_document()
        self.a_open.setEnabled(True) if hasattr(self, 'a_open') else None


    def _close_document(self):
        self.pdf_viewer.clear()
        self.trans_panel.clear()
        self._pdf_path = None
        self._document = None
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

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not api_key and "ollama" not in self._current_model:
            QMessageBox.warning(self, "Configuration requise", "Clé API manquante dans votre environnement ou fichier .env")
            return

        # Prepare a flat list of blocks to translate across all pages
        blocks_to_translate = []
        for page in self._document.pages:
            for block in page.blocks:
                blocks_to_translate.append(block)

        valid_blocks = [b for b in blocks_to_translate if should_translate(b)]
        self.progress_panel.reset(len(valid_blocks))
        
        # Remove the blurred frosted-glass card to show real-time stream overlays
        self.trans_panel.set_translation_started(True)

        # Instantiate a dedicated extractor for lazy translation parsing
        extractor = FitzExtractor(self._pdf_path)

        self._worker = TranslationWorker(
            blocks_to_translate,
            self._document,
            extractor,
            self._current_model,
            api_key,
            self._current_lang
        )
        self._worker.block_done.connect(self._on_block_translated)
        self._worker.batch_progress.connect(self.progress_panel.set_batches)
        self._worker.finished.connect(self._on_translation_finished)
        self._worker.error.connect(self._on_translation_error)
        self._worker.status_update.connect(self.status.showMessage) # Dynamic feedback mapped to status bar
        
        self.a_start.setText("⏹  Arrêter la traduction")
        self._worker.start()

    def _on_block_translated(self, page_idx: int, block_idx: int, translated_text: str):
        # Update both local data model and the Chromium rendering panel dynamically
        if self._document and page_idx < len(self._document.pages):
            page = self._document.pages[page_idx]
            for b in page.blocks:
                if b.block_id == block_idx:
                    b.translated_text = translated_text
                    break
        
        self.trans_panel.update_block_translation(page_idx, block_idx, translated_text)
        self.progress_panel.increment()

    def _on_translation_finished(self):
        self.a_start.setText("▶  Démarrer la traduction")
        self.status.showMessage("Traduction terminée avec succès.")
        QMessageBox.information(self, "Terminé", "Le document a été entièrement traduit !")

    def _on_translation_error(self, err_msg: str):
        self.a_start.setText("▶  Démarrer la traduction")
        QMessageBox.critical(self, "Erreur API", f"La traduction a échoué :\n{err_msg}")

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