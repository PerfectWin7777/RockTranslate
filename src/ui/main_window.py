# src/ui/main_window.py

import os, re
import sys, base64
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
from core.table_detectors import  page_has_table
from core.reading_order import ReadingOrderSorter
from core.domain import FitzDocument, FitzPage, FitzBlock
from reconstruction.html_builder import HTMLBuilder
from reconstruction.latex_builder import build_page_pdf, fitzpage_to_lines_data
from reconstruction.pdf_builder import merge_pdfs

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




def redistribute_translated_lines(
    batch_lines: list,
    results: list[dict],
    page_width: float,
    geo: dict = None,
) -> None:

    page_center = page_width / 2.0

    # ── 1. Calcul des max_chars pour chaque ligne ─────────────────────────
    id_to_item = {}
    for idx, (block, line_idx, line) in enumerate(batch_lines):
        original_chars = max(len(re.sub(r'\s+', ' ', line.text).strip()), 1)
        is_last = (line_idx == len(block.lines) - 1)

        if is_last:
            # Dernière ligne : absorbe le surplus MAIS reste dans sa colonne
            if geo:
                avail_width = HTMLBuilder._effective_col_width(line, geo)
                max_chars = int(avail_width / max(line.right - line.left, 10.0) * original_chars * 3)
            else:
                max_chars = 999
        else:
            char_budget = int(original_chars * 1.30)
            if geo:
                avail_width = HTMLBuilder._effective_col_width(line, geo)
                avail_chars = int(avail_width / max(line.right - line.left, 10.0) * original_chars)
                max_chars = min(char_budget, avail_chars)
            else:
                max_chars = char_budget

        id_to_item[idx] = (block, line_idx, line, max_chars, is_last)

    # ── 2. Résultats LLM indexés par id ──────────────────────────────────
    id_to_result = {r["id"]: r.get("translated", "") for r in results}

    # ── 3. Regroupement par block_id ─────────────────────────────────────
    block_ids_seen: dict[int, list[int]] = {}
    for idx, (block, line_idx, line, max_chars, is_last) in id_to_item.items():
        bid = block.block_id
        if bid not in block_ids_seen:
            block_ids_seen[bid] = []
        block_ids_seen[bid].append(idx)

    # ── 4. Redistribution bloc par bloc ──────────────────────────────────
    for bid, indices in block_ids_seen.items():

        widths = [id_to_item[i][2].right - id_to_item[i][2].left for i in indices]
        if max(widths) / max(min(widths), 1) > 2.5:
            for i in indices:
                _, _, line, _, _ = id_to_item[i]
                line.translated_text = id_to_result.get(i, "") or " "
            continue

        if len(indices) == 1:
            _, _, single_line, _, _ = id_to_item[indices[0]]
            single_line.translated_text = id_to_result.get(indices[0], "") or " "
            continue

        left_indices  = [i for i in indices if id_to_item[i][2].left < page_center]
        right_indices = [i for i in indices if id_to_item[i][2].left >= page_center]

        for col_indices in [left_indices, right_indices]:
            if not col_indices:
                continue

            tops = [id_to_item[i][2].top for i in col_indices]
            max_gap = max(tops[j+1] - tops[j] for j in range(len(tops)-1)) if len(tops) > 1 else 0
            if max_gap > 30.0:
                for i in col_indices:
                    _, _, line, _, _ = id_to_item[i]
                    line.translated_text = id_to_result.get(i, "") or " "
                continue

            first_max_chars = id_to_item[col_indices[0]][3]
            if first_max_chars <= 3:
                for i in col_indices:
                    _, _, line, _, _ = id_to_item[i]
                    line.translated_text = id_to_result.get(i, "") or " "
                continue

            if len(col_indices) == 1:
                _, _, single_line, _, _ = id_to_item[col_indices[0]]
                single_line.translated_text = id_to_result.get(col_indices[0], "") or " "
                continue

            full_text = " ".join(
                id_to_result.get(i, "") for i in col_indices
            ).strip()

            if not full_text:
                for i in col_indices:
                    _, _, line, _, _ = id_to_item[i]
                    line.translated_text = " "
                continue

            words    = full_text.split()
            word_idx = 0

            for i in col_indices:
                _, _, line, max_chars, _ = id_to_item[i]
                is_last_in_col = (i == col_indices[-1])

                if is_last_in_col or word_idx >= len(words):
                    # Dernière ligne — absorbe le reste MAIS respecte max_chars
                    remaining = " ".join(words[word_idx:])
                    remaining_plain = re.sub(r'<[^>]+>', '', remaining)
                    if len(remaining_plain) > max_chars:
                        current = ""
                        while word_idx < len(words):
                            candidate = (current + " " + words[word_idx]).strip()
                            if len(re.sub(r'<[^>]+>', '', candidate)) <= max_chars:
                                current   = candidate
                                word_idx += 1
                            else:
                                break
                        line.translated_text = current or " "
                    else:
                        line.translated_text = remaining or " "
                    word_idx = len(words)

                else:
                    current = ""
                    while word_idx < len(words):
                        candidate = (current + " " + words[word_idx]).strip()
                        candidate_plain = re.sub(r'<[^>]+>', '', candidate)
                        if len(candidate_plain) <= max_chars:
                            current   = candidate
                            word_idx += 1
                        else:
                            break
                    line.translated_text = current if current else " "


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
    page_pdf_ready = pyqtSignal(int, str)  # page_idx, pdf_path
    finished       = pyqtSignal()
    document_pdf_ready = pyqtSignal(str)  # Émet le chemin du PDF final complet
    status_update  = pyqtSignal(str)
    error          = pyqtSignal(str)
    page_incomplete = pyqtSignal(int, int)  # page_idx, nb_lignes_manquantes

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
                    if should_translate(line) and not line.translated_text
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

                    # 5. Stocke les traductions en mémoire — pas d'émission ligne par ligne
                    for res in results:
                        idx        = res.get("id")
                        translated = res.get("translated", "").strip()
                        if idx in line_map and translated:
                            block, line_idx, line = line_map[idx]
                            line.translated_text = translated
                            sliding_context.append(translated)

                    if len(sliding_context) > _SLIDING_CONTEXT_SIZE:
                        sliding_context = sliding_context[-_SLIDING_CONTEXT_SIZE:]
                

                # Vérifie les lignes manquantes
                missing = [
                    line
                    for block in fitz_page.blocks
                    if isinstance(block, FitzBlock)
                    for line in block.lines
                    if should_translate(line) and not line.translated_text
                ]

                if missing:
                    self.page_incomplete.emit(page_idx, len(missing))
                    self.status_update.emit(
                        f"Page {page_num} : {len(missing)} lignes non traduites."
                    )

                # 6. Page entièrement traduite → compilation LaTeX
                self.status_update.emit(
                    f"Page {page_num}/{total_pages} : compilation PDF..."
                )

                

                output_dir = os.path.join(
                    os.path.dirname(self.document.path), "rocktranslate_output"
                )
                os.makedirs(output_dir, exist_ok=True)

                bg_path = os.path.join(output_dir, f"bg_{page_num:03d}.png")
                with open(bg_path, "wb") as f:
                    f.write(base64.b64decode(fitz_page.png_b64))

                lines_data = fitzpage_to_lines_data(fitz_page)
                pdf_path   = build_page_pdf(
                    bg_image_path=bg_path,
                    page_w=fitz_page.width,
                    page_h=fitz_page.height,
                    lines_data=lines_data,
                    output_dir=output_dir,
                    page_number=page_num,
                )

                if pdf_path:
                    self.page_pdf_ready.emit(page_idx, pdf_path)
                    self.status_update.emit(
                        f"Page {page_num}/{total_pages} : PDF prêt."
                    )
                else:
                    self.status_update.emit(
                        f"Page {page_num}/{total_pages} : échec compilation."
                    )

                self.page_done.emit()


            pdf.close()

            # --- ASSEMBLAGE FINAL DE TOUTES LES PAGES TRADUITES ---
            if not self._stop:
                self.status_update.emit("Génération et assemblage du document final complet...")
                
                # Reconstruction ordonnée de la liste des chemins des pages compilées
                compiled_paths = []
                for p_num in range(1, total_pages + 1):
                    p_path = os.path.join(output_dir, f"page_{p_num:03d}.pdf")
                    if os.path.exists(p_path):
                        compiled_paths.append(p_path)
                
                # Définition du nom du document traduit complet (ex: original_translated.pdf)
                base_name = os.path.splitext(os.path.basename(self.document.path))[0]
                final_output_pdf = os.path.join(output_dir, f"{base_name}_translated.pdf")
                
                # Appel du builder d'assemblage
                success = merge_pdfs(compiled_paths, final_output_pdf)
                
                if success:
                    # Émission du signal avec le chemin du document final unifié
                    self.document_pdf_ready.emit(final_output_pdf)
                    self.status_update.emit("Traduction et assemblage final terminés.")
                else:
                    self.status_update.emit("Traduction terminée, mais échec de l'assemblage final.")

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

        self._incomplete_pages: list[int] = []

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
        self.trans_panel.init_pages(self._document.pages, self._document)
        self.pdf_viewer.load_pdf(self._pdf_path)

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
        
        #  reset les pages incomplètes au démarrage
        self._incomplete_pages.clear()

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
        self._worker.page_pdf_ready.connect(self._on_page_pdf_ready)
        self._worker.document_pdf_ready.connect(self._on_final_pdf_ready)
        self._worker.error.connect(self._on_translation_error)
        self._worker.page_done.connect(self.progress_panel.increment)
        self._worker.status_update.connect(self.status.showMessage)
        self._worker.page_incomplete.connect(self._on_page_incomplete)

        self.a_start.setText("⏹  Arrêter la traduction")
        self._worker.start()

    def _on_block_translated(self, page_idx: int, block_id: int, line_idx: int, translated_text: str):
            """
            Receives a translated line and forwards it to the TranslationViewer
            for surgical JS injection into Chromium.
            """
            if not (self._document and page_idx < len(self._document.pages)):
                return
            
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
            fitz_page = self._document.pages[page_idx]
            # 1. Retire le glass de cette page
            self.trans_panel.remove_glass(page_idx)

            # 2. Injecte les skeletons chirurgicalement
            self.trans_panel.inject_skeletons(page_idx, fitz_page)

    
    def _on_page_pdf_ready(self, page_idx: int, pdf_path: str):
        """Affiche le PDF compilé à la place du skeleton."""
        self.trans_panel.show_page_pdf(page_idx, pdf_path)

    def _on_translation_finished(self):
        print("[TRANSLATION_FINISHED]")
        self.a_start.setText("▶  Démarrer la traduction")
    
        if self._incomplete_pages:
            pages_str = ", ".join(str(p+1) for p in self._incomplete_pages)
            reply = QMessageBox.question(
                self,
                "Pages incomplètes",
                f"Les pages {pages_str} ont des lignes non traduites.\n"
                f"Voulez-vous les retraduire ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self._incomplete_pages.clear()
                self._start_translation()
                return

        self.status.showMessage("Traduction terminée.")
        QMessageBox.information(self, "Terminé", "Le document a été traduit !")


    def _on_final_pdf_ready(self, final_pdf_path: str):
        """
        Appelé quand l'assemblage final de toutes les pages est terminé.
        Remplace l'affichage fragmenté HTML par la visionneuse PDF unique complète.
        """
        # On charge le document PDF unifié final dans l'interface de droite
        self.trans_panel.show_final_pdf(final_pdf_path)

    def _on_translation_error(self, err_msg: str):
        self.a_start.setText("▶  Démarrer la traduction")
        QMessageBox.critical(
            self, "Erreur",
            f"La traduction a été interrompue :\n{err_msg}"
        )
    
    def _on_page_incomplete(self, page_idx: int, missing: int):
        self._incomplete_pages.append(page_idx)
        self.status.showMessage(
            f"Page {page_idx+1} incomplète — {missing} lignes manquantes."
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