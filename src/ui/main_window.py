"""
main_window.py — Fenêtre principale RockTranslate v3
Chemin : D:/Projets/RockTranslate/src/ui/main_window.py

Nouveautés v3 :
- Menu bar classique (plus de TopBar)
- Zoom synchronisé gauche/droite (+/- et raccourcis clavier)
- Scroll synchronisé gauche/droite
- Panneau droit = clone PDF avec textes traduits positionnés exactement
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from dotenv import load_dotenv
load_dotenv()

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QSplitter, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QMenuBar, QMenu,QAbstractScrollArea
)
from PyQt6.QtCore  import Qt, QThread, pyqtSignal
from PyQt6.QtGui   import QFont, QKeySequence, QAction

from ui.pdf_viewer        import PDFViewer
from ui.translation_viewer import TranslationViewer
from ui.progress_panel    import ProgressPanel

from translation.llm_client import LLMClient
from translation.chunker    import build_batches, filter_noise

from core.pdf_extractor     import PDFExtractor
from core.spatial_clusterer import SpatialClusterer

# ── Modèles classés par provider ─────────────────────────────────────────────
MODELS = {
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
        "gpt-4-turbo",
    ],
    "Anthropic": [
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
    "Ollama (local)": [
        "ollama/mistral",
        "ollama/llama3",
        "ollama/phi3",
    ],
}

LANGUAGES = [
    ("Français",  "French"),
    ("Español",   "Spanish"),
    ("English",   "English"),
    ("Deutsch",   "German"),
    ("العربية",   "Arabic"),
    ("中文",      "Chinese (Simplified)"),
    ("Português", "Portuguese"),
    ("Italiano",  "Italian"),
    ("日本語",    "Japanese"),
    ("Русский",   "Russian"),
]


# ── Worker traduction ─────────────────────────────────────────────────────────
class TranslationWorker(QThread):
    paragraph_done = pyqtSignal(int, str)
    batch_progress = pyqtSignal(int, int)
    finished       = pyqtSignal()
    error          = pyqtSignal(str)

    def __init__(self, paragraphs, model, api_key, target_lang):
        super().__init__()
        self.paragraphs  = paragraphs
        self.model       = model
        self.api_key     = api_key
        self.target_lang = target_lang
        self._stop       = False

    def run(self):
        try:
        
            clean = filter_noise(self.paragraphs)
            original_indices = {id(p): i for i, p in enumerate(self.paragraphs)}

            client = LLMClient(
                model=self.model,
                api_key=self.api_key,
                target_lang=self.target_lang,
                on_progress=lambda c, t: self.batch_progress.emit(c, t),
            )

            for batch in build_batches(clean, self.model):
                if self._stop:
                    break
                client._translate_batch_with_retry(batch)
                for para in batch.paragraphs:
                    if self._stop:
                        break
                    idx = original_indices.get(id(para), -1)
                    if idx >= 0:
                        self.paragraph_done.emit(idx, para.translated_text or "")

            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self._stop = True


# ── Fenêtre principale ────────────────────────────────────────────────────────
class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockTranslate")
        self.resize(1440, 880)
        self.setMinimumSize(900, 600)

        self._pdf_path    = None
        self._paragraphs  = []
        self._worker      = None
        self._current_model = list(MODELS["Google Gemini"])[1]
        self._current_lang  = "French"
        self._zoom          = 0.8   # zoom partagé gauche/droite

        self._build_menu()
        self._build_ui()
        self._connect_scroll_sync()

    # ── Menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        # ── Fichier ──────────────────────────────────────────
        m_file = mb.addMenu("Fichier")

        a_open = QAction("Ouvrir PDF…", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_pdf)
        m_file.addAction(a_open)

        a_close = QAction("Fermer", self)
        a_close.setShortcut(QKeySequence("Ctrl+W"))
        a_close.triggered.connect(self._close_pdf)
        m_file.addAction(a_close)

        m_file.addSeparator()

        a_quit = QAction("Quitter", self)
        a_quit.setShortcut(QKeySequence("Ctrl+Q"))
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # ── Traduction ────────────────────────────────────────
        m_trans = mb.addMenu("Traduction")

        self.a_start = QAction("▶  Démarrer", self)
        self.a_start.setShortcut(QKeySequence("Ctrl+Return"))
        self.a_start.setEnabled(False)
        self.a_start.triggered.connect(self._toggle_translation)
        # self.a_start.triggered.connect(self._test_simulation)
        m_trans.addAction(self.a_start)

        a_export = QAction("💾  Exporter PDF traduit…", self)
        a_export.setShortcut(QKeySequence("Ctrl+E"))
        a_export.triggered.connect(self._export_pdf)
        m_trans.addAction(a_export)

        m_trans.addSeparator()

        # Sous-menu Langue
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

        # Sous-menu Modèle (classé par provider)
        m_model = m_trans.addMenu("Modèle LLM")
        self._model_actions = {}
        first = True
        for provider, models in MODELS.items():
            # Séparateur + titre provider
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
        a_zoom_in.triggered.connect(self._zoom_in)
        m_view.addAction(a_zoom_in)

        a_zoom_out = QAction("Zoom −", self)
        a_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        a_zoom_out.triggered.connect(self._zoom_out)
        m_view.addAction(a_zoom_out)

        a_zoom_reset = QAction("Zoom 100%", self)
        a_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        a_zoom_reset.triggered.connect(self._zoom_reset)
        m_view.addAction(a_zoom_reset)

        m_view.addSeparator()

        a_fullscreen = QAction("Plein écran", self, checkable=True)
        a_fullscreen.setShortcut(QKeySequence("F11"))
        a_fullscreen.triggered.connect(self._toggle_fullscreen)
        m_view.addAction(a_fullscreen)

        # ── Aide ──────────────────────────────────────────────
        m_help = mb.addMenu("Aide")

        a_about = QAction("À propos de RockTranslate", self)
        a_about.triggered.connect(self._show_about)
        m_help.addAction(a_about)

        a_github = QAction("GitHub →", self)
        a_github.triggered.connect(
            lambda: __import__("webbrowser").open(
                "https://github.com/PerfectWin7777/RockTranslate"
            )
        )
        m_help.addAction(a_github)

    # ── UI principale ─────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Splitter gauche (PDF original) / droite (traduction clone)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.pdf_viewer = PDFViewer()
        self.pdf_viewer.page_changed.connect(self._on_page_changed)
        self.splitter.addWidget(self.pdf_viewer)

        self.trans_panel = TranslationViewer()
        self.splitter.addWidget(self.trans_panel)
        self.splitter.setSizes([720, 720])

        root.addWidget(self.splitter, 1)

        # Barre de progression
        self.progress_panel = ProgressPanel()
        root.addWidget(self.progress_panel)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(
            "⟁ RockTranslate  —  Fichier › Ouvrir PDF  pour commencer"
        )

    def _connect_scroll_sync(self):
        """Synchronise le scroll vertical gauche ↔ droite."""
        left_scroll = self.pdf_viewer.view.findChild(QAbstractScrollArea)
        right_scroll = self.trans_panel.view.findChild(QAbstractScrollArea)
        
        if left_scroll and right_scroll:
            left_scroll.verticalScrollBar().valueChanged.connect(
                right_scroll.verticalScrollBar().setValue
            )

    # ── Actions menu ──────────────────────────────────────────────────────────

    def _on_lang_selected(self):
        a = self.sender()
        self._current_lang = a.data()
        for act in self._lang_actions.values():
            act.setChecked(False)
        a.setChecked(True)
        self.status.showMessage(f"Langue cible : {a.text()}")

    def _on_model_selected(self):
        a = self.sender()
        self._current_model = a.data()
        for act in self._model_actions.values():
            act.setChecked(False)
        a.setChecked(True)
        self.status.showMessage(f"Modèle : {self._current_model}")

    def _zoom_in(self):
        self._zoom = min(self._zoom + 0.2, 4.0)
        self._apply_zoom()

    def _zoom_out(self):
        self._zoom = max(self._zoom - 0.2, 0.4)
        self._apply_zoom()

    def _zoom_reset(self):
        self._zoom = 1.0
        self._apply_zoom()

    def _apply_zoom(self):
        """Applique le zoom aux deux panneaux simultanément."""
        self.pdf_viewer.set_zoom(self._zoom)
        self.trans_panel.set_zoom(self._zoom)
        self.status.showMessage(f"Zoom : {int(self._zoom * 100)}%")

    def _toggle_fullscreen(self, checked):
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _show_about(self):
        QMessageBox.about(
            self, "À propos de RockTranslate",
            "<b>RockTranslate</b><br>"
            "Traducteur de documents scientifiques PDF.<br><br>"
            "Extraction spatiale → LLM → Reconstruction fidèle<br><br>"
            "Open source — MIT License"
        )

    # ── PDF ───────────────────────────────────────────────────────────────────

    def _open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un PDF", "", "Fichiers PDF (*.pdf)"
        )
        if not path:
            return
        self._pdf_path = path
        self.status.showMessage(f"Chargement : {os.path.basename(path)}…")
        try:
            self.pdf_viewer.load_pdf(path, zoom=self._zoom)
            self._extract_paragraphs(path)
            self.a_start.setEnabled(True)
            self.status.showMessage(
                f"{os.path.basename(path)}  ·  "
                f"{self.pdf_viewer.total_pages} pages  ·  "
                f"{len(self._paragraphs)} paragraphes détectés"
            )

            self.trans_panel.init_shadow(path)
        except Exception as e:
            QMessageBox.critical(self, "Erreur ouverture", str(e))

    def _close_pdf(self):
        self.pdf_viewer.clear()
        self.trans_panel.clear()
        self._pdf_path   = None
        self._paragraphs = []
        self.a_start.setEnabled(False)
        self.status.showMessage("Document fermé")

    def _extract_paragraphs(self, path: str):
        

        # 1. Extraction et Analyse (Le "Cerveau")
        extractor = PDFExtractor(path)
        document  = extractor.extract()
        sc        = SpatialClusterer()

        # Détection de la gouttière globale (pour les 2 colonnes)
        all_raw = [p.raw_objects for p in document.pages]
        gutter  = sc.find_document_gutter(all_raw, document.pages[0].width)

        all_blocks = []
        for page in document.pages:
            # Traitement spatial page par page
            blocks = sc.process_page(
                page.raw_objects, page.width,
                page.number, page.height,
                forced_gutter=gutter,
            )
            all_blocks.append(blocks)

        # Gestion des coupures de phrases entre pages
        for i in range(len(all_blocks) - 1):
            all_blocks[i], all_blocks[i + 1] = sc.merge_cross_page(
                all_blocks[i], all_blocks[i + 1]
            )

        # 2. Création des paragraphes finaux (Source de vérité pour le LLM)
        # flat = [b for pb in all_blocks for b in pb]
        # self._paragraphs = sc.build_paragraphs(flat)
        

        # debug rapide 
        from core.domain import Paragraph

        flat = [b for pb in all_blocks for b in pb]

        # 1 block = 1 paragraph (mode test)
        self._paragraphs = []
        for block in flat:
            if "Introduction" in block.text or "introduction" in block.text:
                 print(f"TROUVÉ: '{block.text}' | page={block.page_number} | h={block.top-block.bottom:.1f}")

            if not block.text.strip():
                continue
            p = Paragraph(
                blocks=[block],
                text=block.text,
                left=block.left,
                bottom=block.bottom,
                right=block.right,
                top=block.top,
                column=block.column,
                page_number=block.page_number,

            )
            self._paragraphs.append(p)

        # Marque les paragraphes après "References" comme non-traduisibles
        in_references = False
        for para in self._paragraphs:
            t = para.text.strip().lower()
            
            # Détecte le titre "References" / "Bibliography" / "Références"
            if t in ["references", "bibliography", "références", "référence"]:
                in_references = True
                continue
            
            if in_references:
                para.skip_translation = True
                # para.translated_text= None  # force skip
                # On marque avec un flag pour ne pas écraser dans le PDF
                # para.text = ""  # ← vide = filter_noise le skipera


        # 3. Initialisation du Shadow PDF (Vue de droite)
        # On passe le chemin original pour qu'il crée sa copie de travail
        self.trans_panel.init_shadow(path)
        
        # 4. Synchronisation visuelle
        self._apply_zoom()
        
        # On affiche le nombre de paragraphes dans la barre d'état
        self.status.showMessage(f"Analyse terminée : {len(self._paragraphs)} paragraphes détectés.")

    # ── Traduction ────────────────────────────────────────────────────────────

    def _toggle_translation(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait()
            self.a_start.setText("▶  Démarrer")
            self.status.showMessage("Traduction arrêtée")
            return
        self._start_translation()

    def _start_translation(self):
        if not self._paragraphs:
            return

        api_key = (
            os.getenv("GEMINI_API_KEY") or
            os.getenv("OPENAI_API_KEY")  or
            os.getenv("ANTHROPIC_API_KEY") or ""
        )
        if not api_key:
            QMessageBox.warning(
                self, "Clé API manquante",
                "Définissez GEMINI_API_KEY dans votre fichier .env"
            )
            return

        self.a_start.setText("⏹  Arrêter")
        self.trans_panel.clear_translations()
        self.progress_panel.reset(len(self._paragraphs))

        self._worker = TranslationWorker(
            self._paragraphs,
            self._current_model,
            api_key,
            self._current_lang,
        )
        self._worker.paragraph_done.connect(self._on_paragraph_done)
        self._worker.batch_progress.connect(self.progress_panel.set_batches)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

        self.status.showMessage(
            f"Traduction en cours → {self._current_lang} "
            f"via {self._current_model}  "
            f"({len(self._paragraphs)} paragraphes)"
        )

    def _on_paragraph_done(self, idx: int, text: str):
        # On stocke la traduction dans notre "Source de Vérité"
        if idx < len(self._paragraphs):
            self._paragraphs[idx].translated_text = text
        # On met à jour l'UI (Barre de progression uniquement)
        self.progress_panel.increment()

    def _on_page_changed(self, page_idx: int):
        """Synchronise la page affichée dans le panneau de traduction."""
        self.trans_panel.goto_page(page_idx)

    def _on_finished(self):
        self.status.showMessage("Traduction terminée. Reconstruction du PDF...")
        
        # On lance la reconstruction du Shadow PDF
        self.trans_panel.apply_all_translations(self._paragraphs)
        self.a_start.setText("▶  Démarrer")
        self.status.showMessage(
            f"Traduction terminée ✓  —  {len(self._paragraphs)} paragraphes"
        )

    def _on_error(self, msg: str):
        self.a_start.setText("▶  Démarrer")
        QMessageBox.critical(self, "Erreur de traduction", msg)
        self.status.showMessage(f"Erreur : {msg[:100]}")

    def _export_pdf(self):
        if not self._pdf_path:
            QMessageBox.information(self, "Export", "Ouvrez d'abord un PDF.")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "Exporter PDF traduit", "", "PDF (*.pdf)"
        )
        if not out:
            return
        try:
            from reconstruction.pdf_builder import PDFBuilder
            PDFBuilder(self._pdf_path).rebuild(self._paragraphs, out)
            self.status.showMessage(f"Exporté : {out}")
            QMessageBox.information(self, "Export réussi", f"Fichier :\n{out}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))
    

    def _test_simulation(self):
        """Simule une traduction pour tester la reconstruction visuelle."""
        if not self._paragraphs:
            QMessageBox.warning(self, "Erreur", "Ouvrez d'abord un PDF.")
            return

        self.status.showMessage("Simulation de traduction en cours...")
        
        for para in self._paragraphs:
            # On simule une traduction en répétant le texte ou en mettant un préfixe
            # Cela permet de voir si le wrapping (retour à la ligne) fonctionne
            para.translated_text = f"TRADUIT ({para.page_number}): " + para.text

        # On applique au viewer de droite
        self.trans_panel.apply_translations(self._paragraphs)
        self.status.showMessage("Simulation terminée. Vérifiez le panneau de droite.")

# ── Entrée ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())