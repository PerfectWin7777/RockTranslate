# ui_pyqt/main_window.py

import os
import sys
import shutil
import tempfile
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QFileDialog, QMessageBox, QLabel, QStatusBar, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont, QKeySequence, QAction, QActionGroup
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView

from dotenv import load_dotenv

# Charge les variables d'environnement (.env)
load_dotenv()

# Importations de notre nouvelle architecture découplée
from ui_pyqt.workspace_viewer import WorkspaceViewer
from ui_pyqt.progress_panel import ProgressPanel
from ui_pyqt.workers.extraction_worker import ExtractionWorker
from ui_pyqt.workers.translation_worker import TranslationWorker
from utils.downloader import check_and_download_pdfjs, check_and_download_pdf2htmlex, DEFAULT_ASSETS_DIR

# ── Configuration Constants ──────────────────────────────────────────────────
SUPPORTED_MODELS = {
    "Google Gemini": [
        "gemini/gemini-3.1-flash-lite",
        "gemini/gemini-2.5-flash-lite",
        "gemini/gemini-3-flash-preview",
        "gemini/gemini-2.5-flash",
        "gemini/gemini-2.5-pro",
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


# ── Welcome Dashboard (Drag & Drop Frame) ────────────────────────────────────
class WelcomeDashboard(QFrame):
    """Écran d'accueil élégant affiché au démarrage."""
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

        subtitle = QLabel("Glissez-déposez votre PDF scientifique ici pour commencer", self)
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
            self.lbl_status.setText("● Clé API détectée (Zéro-Configuration active)")
            self.lbl_status.setStyleSheet("color: #48bb78; font-weight: bold; font-size: 11px;")
        else:
            self.lbl_status.setText("○ Aucune clé API trouvée (Veuillez configurer GEMINI_API_KEY dans votre .env)")
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
        self._instrumented_html_path = None
        self._original_texts = {}
        self._zoom = 0.8

        self._ext_worker = None
        self._trans_worker = None
        
        self._current_model = SUPPORTED_MODELS["Google Gemini"][0]
        self._current_lang = "French"

        self._tid_to_page = {}
        self._current_translating_page = -1

        # Sécurité : Vérification et téléchargement des moteurs web en tâche de fond au démarrage
        check_and_download_pdfjs()
        check_and_download_pdf2htmlex()

        self._build_menu()
        self._build_ui()

    def _build_ui(self):
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Page 0 : Écran d'accueil
        self.welcome_screen = WelcomeDashboard(self)
        self.welcome_screen.file_dropped.connect(self._open_pdf_by_path)
        self.stacked_widget.addWidget(self.welcome_screen)

        # Page 1 : Espace de travail unifié
        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)

        # Remplacement de l'ancien splitter PyQt par notre WorkspaceViewer unifié à colonne unique Chromium !
        self.workspace_view = WorkspaceViewer(self)
        self.workspace_view.set_zoom(self._zoom)
        work_layout.addWidget(self.workspace_view, 1)

        # Intégration de votre barre de progression intacte
        self.progress_panel = ProgressPanel()
        work_layout.addWidget(self.progress_panel)

        self.stacked_widget.addWidget(workspace)

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Prêt. Glissez-déposez un PDF pour commencer.")

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

        self.a_export = QAction("Exporter le PDF traduit…", self)
        self.a_export.setShortcut(QKeySequence("Ctrl+S"))
        self.a_export.setEnabled(False)
        self.a_export.triggered.connect(self._export_pdf_dialog)
        m_file.addAction(self.a_export)

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

        self.a_fullscreen = QAction("Plein écran", self, checkable=True)
        self.a_fullscreen.setShortcut(QKeySequence("F11"))
        self.a_fullscreen.triggered.connect(self.toggle_fullscreen)
        m_view.addAction(self.a_fullscreen)

        m_view.addSeparator()

        # Groupe d'actions mutuellement exclusives (Boutons radio) pour la disposition
        self.layout_group = QActionGroup(self)

        self.a_layout_both = QAction("Afficher les deux côte-à-côte", self, checkable=True)
        self.a_layout_both.setShortcut(QKeySequence("Ctrl+3"))
        self.a_layout_both.setChecked(True)
        self.a_layout_both.triggered.connect(self._apply_layout_both)
        self.layout_group.addAction(self.a_layout_both)
        m_view.addAction(self.a_layout_both)

        self.a_layout_pdf = QAction("Afficher uniquement l'original (PDF)", self, checkable=True)
        self.a_layout_pdf.setShortcut(QKeySequence("Ctrl+1"))
        self.a_layout_pdf.triggered.connect(self._apply_layout_pdf_only)
        self.layout_group.addAction(self.a_layout_pdf)
        m_view.addAction(self.a_layout_pdf)

        self.a_layout_trans = QAction("Afficher uniquement la traduction", self, checkable=True)
        self.a_layout_trans.setShortcut(QKeySequence("Ctrl+2"))
        self.a_layout_trans.triggered.connect(self._apply_layout_trans_only)
        self.layout_group.addAction(self.a_layout_trans)
        m_view.addAction(self.a_layout_trans)

    # ── LOGIQUE DES ACTIONS D'OUVERTURE ET DE SÉLECTION ──
    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", "", "PDF (*.pdf)")
        if path:
            self._open_pdf_by_path(path)

    def _open_pdf_by_path(self, path: str):
        self.status.showMessage("Analyse du document et extraction en cours...")
        self._pdf_path = path
        self.a_open.setEnabled(False)

        # Lancement du nouveau worker découplé d'extraction
        self._ext_worker = ExtractionWorker(path)
        self._ext_worker.status_update.connect(self.status.showMessage)
        self._ext_worker.finished.connect(self._on_extraction_finished)
        self._ext_worker.error.connect(self._on_extraction_error)
        self._ext_worker.start()

    def _on_extraction_progress(self, message: str):
        self.status.showMessage(message)

    def _on_extraction_finished(self, instrumented_html_path: str, original_texts_map: dict, tid_to_page: dict):
        self._instrumented_html_path = instrumented_html_path
        self._original_texts = original_texts_map
        self._tid_to_page = tid_to_page

        # Basculement sur l'espace de travail principal
        self.stacked_widget.setCurrentIndex(1)
        self.a_close.setEnabled(True)
        self.a_start.setEnabled(True)

        # Initialisation et chargement de notre double-vue Chromium synchronisée !
        pdfjs_absolute_path = os.path.join(DEFAULT_ASSETS_DIR, "pdfjs")
        self.workspace_view.load_document(self._pdf_path, self._instrumented_html_path, pdfjs_absolute_path)

        self.status.showMessage(f"Document chargé : {os.path.basename(self._pdf_path)} ({len(original_texts_map)} segments textuels identifiés)")
        self.a_open.setEnabled(True)

    def _on_extraction_error(self, err_msg: str):
        QMessageBox.critical(self, "Erreur d'extraction", f"Impossible d'analyser le document :\n{err_msg}")
        self._close_document()
        self.a_open.setEnabled(True)

    # ── LOGIQUE DE TRADUCTION IA ──
    def _toggle_translation(self):
        if self._trans_worker and self._trans_worker.isRunning():
            self.status.showMessage("Arrêt de la traduction en cours...")
            self._trans_worker.stop()
            # self.a_start.setText("▶  Démarrer la traduction")
            self.a_start.setEnabled(False)  # Désactive temporairement le bouton
            return
        self._start_translation()

    def _start_translation(self):
        if not self._original_texts:
            return

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        if not api_key and "ollama" not in self._current_model:
            QMessageBox.warning(self, "Configuration requise", "Clé API manquante dans votre environnement ou fichier .env")
            return

        self.a_export.setEnabled(False)

        # Réinitialisation de votre barre de progression sur le nombre exact de segments à traduire !
        self.progress_panel.reset(len(self._original_texts))

        # Initialisation et démarrage du nouveau worker de traduction asynchrone
        self._trans_worker = TranslationWorker(
            self._original_texts,
            self._current_model,
            api_key,
            self._current_lang
        )
        self._trans_worker.status_update.connect(self.status.showMessage)
        self._trans_worker.batch_progress.connect(self.progress_panel.set_batches)
        self._trans_worker.segment_translated.connect(self._on_segment_translated)
        self._trans_worker.finished.connect(self._on_translation_finished)
        self._trans_worker.error.connect(self._on_translation_error)
        
        self.a_start.setText("⏹  Arrêter la traduction")
        self._current_translating_page = -1
        self.workspace_view.prepare_page(0) 
        self._trans_worker.start()

    def _on_segment_translated(self, trans_id: str, translated_text: str):
        """Reçoit une traduction progressive et l'injecte en temps réel dans l'HTML de droite."""
        page_idx = self._tid_to_page.get(trans_id, 0)
        if page_idx != self._current_translating_page:
            self._current_translating_page = page_idx
            print(f"🔔 prepare_page appelé pour page {page_idx}") 
            self.workspace_view.prepare_page(page_idx)

        self.workspace_view.stream_translation(trans_id, translated_text)
        self.progress_panel.increment()

    def _on_translation_finished(self):
        self.a_start.setText("▶  Démarrer la traduction")
        self.a_start.setEnabled(True)
        
        # ── NETTOYAGE ULTRA-PROPRE DES SQUELETTES RESTANTS ──
        self.workspace_view.clean_up_all_skeletons()

       # On vérifie si l'utilisateur a cliqué sur "Arrêter"
        if self._trans_worker and self._trans_worker.is_stopped():
            self.status.showMessage("❌ Traduction interrompue par l'utilisateur.")
            self.a_export.setEnabled(True)  # Permet d'exporter ce qui a déjà été traduit
        else:
            self.status.showMessage("✅ Traduction terminée.")
            self.a_export.setEnabled(True)
            QMessageBox.information(self, "Terminé", "Le document a été traduit avec succès !")

    def _on_translation_error(self, err_msg: str):
        self.a_start.setText("▶  Démarrer la traduction")
        QMessageBox.critical(self, "Erreur", f"La traduction a été interrompue :\n{err_msg}")

    # ── LOGIQUE D'EXPORTATION NATIVE HAUTE FIDÉLITÉ  ──
    def _export_pdf_dialog(self):
        """
        Génère un PDF vectoriel d'une qualité d'impression identique en tâche de fond.
        """
        if not self._instrumented_html_path:
            return

        original_file_name = os.path.basename(self._pdf_path)
        base_name, extension = os.path.splitext(original_file_name)
        suggested_name = f"{base_name}_translated{extension}"

        default_dir = os.path.join(os.path.expanduser("~"), "Documents", suggested_name)

        destination_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exporter le PDF traduit",
            default_dir,
            "Documents PDF (*.pdf)"
        )

        if not destination_path:
            return

        QTimer.singleShot( 2000, lambda: self.status.showMessage("Génération du document PDF vectoriel final...")    ) 

        # ÉTAPE 1 : Récupérer le code HTML déjà traduit depuis la mémoire active de l'iframe
        js_get_translated_html = """
        (function() {
            var iframe = document.getElementById('html-iframe');
            if (iframe && iframe.contentWindow) {
                return iframe.contentWindow.document.documentElement.outerHTML;
            }
            return "";
        })();
        """
        self.status.showMessage("Export du document PDF vectoriel final, Patientez...")  
        def on_html_retrieved(translated_html):
            if not translated_html:
                self.status.showMessage("❌ Échec de la récupération du texte traduit.")
                return

            # ÉTAPE 2 : Écrire cet HTML traduit et propre dans un fichier temporaire sur le disque
            self._temp_print_file = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
            self._temp_print_file.write(translated_html)
            self._temp_print_file.close()

            # ÉTAPE 3 : Lancer l'imprimante Chromium asynchrone sur ce fichier propre sans loaders
            self._print_view = QWebEngineView()
            self._print_view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            self._print_view.load(QUrl.fromLocalFile(self._temp_print_file.name))

            def on_load_finished(ok):
                if ok:
                    # Lancement de l'impression PDF Chromium standard (asynchrone, ne fige pas l'IHM)
                    self._print_view.page().printToPdf(destination_path)
                else:
                    self.status.showMessage("❌ Échec du chargement du document pour l'exportation.")
                    try:
                        os.unlink(self._temp_print_file.name)
                    except Exception:
                        pass

            def on_pdf_printed(path):
                self.status.showMessage(f"Fichier exporté avec succès : {os.path.basename(path)}")
                QMessageBox.information(self, "Export réussi", f"Le PDF traduit a été enregistré sous :\n{path}")
                
                # Nettoyage physique du fichier temporaire du disque
                try:
                    os.unlink(self._temp_print_file.name)
                except Exception:
                    pass
                self._print_view = None  # Libération de la mémoire de l'imprimante

            self._print_view.loadFinished.connect(on_load_finished)
            self._print_view.page().pdfPrintingFinished.connect(on_pdf_printed)

        # Exécuter l'extraction asynchrone depuis la vue Chromium active
        self.workspace_view.page().runJavaScript(js_get_translated_html, on_html_retrieved)



    # ── LOGIQUE DES ACTIONS DE SÉLECTION MENUS ──
    def _apply_layout_both(self):
        self.workspace_view.set_pane_layout("both")
        self.status.showMessage("Affichage : Vue partagée côte-à-côte.")

    def _apply_layout_pdf_only(self):
        self.workspace_view.set_pane_layout("pdf_only")
        self.status.showMessage("Affichage : Original (PDF) uniquement.")

    def _apply_layout_trans_only(self):
        self.workspace_view.set_pane_layout("trans_only")
        self.status.showMessage("Affichage : Traduction uniquement.")

    def _adjust_zoom(self, delta: float):
        if delta == 0.0:
            self._zoom = 1.0
        else:
            self._zoom = max(0.5, min(2.5, self._zoom + delta))
        self.workspace_view.setZoomFactor(self._zoom)
        self.status.showMessage(f"Zoom appliqué : {int(self._zoom * 100)}%")

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.a_fullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.a_fullscreen.setChecked(True)

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

    def _close_document(self):
        # Arrêt sécurisé et découplé du thread actif s'il existe
        if self._trans_worker and self._trans_worker.isRunning():
            self._trans_worker.stop()
            
            # Déconnexion de sécurité des signaux pour éviter les retours sur widgets détruits
            try:
                self._trans_worker.status_update.disconnect()
                self._trans_worker.batch_progress.disconnect()
                self._trans_worker.segment_translated.disconnect()
                self._trans_worker.finished.disconnect()
                self._trans_worker.error.disconnect()
            except Exception:
                pass
                
            # Attente maximale de 300ms, sinon interruption forcée pour éviter le plantage
            if not self._trans_worker.wait(300):
                self._trans_worker.terminate()

        self.workspace_view.cleanup_temp_files()
        self.workspace_view.load(QUrl("about:blank"))
        
        self._pdf_path = None
        self._instrumented_html_path = None
        self._original_texts = {}
        
        self.a_close.setEnabled(False)
        self.a_start.setEnabled(False)
        self.a_export.setEnabled(False)
        
        self.a_layout_both.setChecked(True)
        self.stacked_widget.setCurrentIndex(0)
        self.status.showMessage("Document clos.")

    def closeEvent(self, event):
        self._close_document()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())