# ui_pyqt/workers/extraction_worker.py

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger
import os

# Importation de nos fonctions d'analyse pures de core/
from core.html_transformer import convert_pdf_to_html, instrument_html

class ExtractionWorker(QThread):
    """
    Worker d'arrière-plan gérant l'extraction et l'instrumentation géométrique du PDF.
    """
    status_update = pyqtSignal(str)              # Pour mettre à jour la barre d'état UI
    extraction_progress = pyqtSignal(int, int)   # Émet (page_courante, pages_totales) en direct
    finished =      pyqtSignal(str, dict, dict)  # Émet (instrumented_html_path, original_texts_map, tid_to_page)
    error         = pyqtSignal(str)              # Émet le message en cas d'erreur fatale

    def __init__(self, pdf_path: str, assets_dir: str = "src/assets"):
        super().__init__()
        self.pdf_path = pdf_path
        self.assets_dir = assets_dir

    def run(self):
        try:
            self.status_update.emit("⚙️ Conversion haute fidélité du PDF en cours...")
            logger.info(f"Lancement de la conversion du PDF : {self.pdf_path}")

            # Callback de progression en direct
            def on_pdf_progress(current: int, total: int):
                self.extraction_progress.emit(current, total)
            
            # Étape A : Conversion unifiée via pdf2htmlEX avec retour d'avancement
            raw_html_path = convert_pdf_to_html(self.pdf_path, self.assets_dir, on_progress=on_pdf_progress)
            if not raw_html_path or not os.path.exists(raw_html_path):
                self.error.emit("La conversion géométrique par pdf2htmlEX a échoué.")
                return

            self.status_update.emit("⚙️ Analyse et instrumentation en cours...")
            logger.info("Extraction et empaquetage sémantique avec BeautifulSoup...")
            
            # Étape B : Instrumentation du fichier et génération de la carte sémantique de traduction
            pdf_dir = os.path.dirname(os.path.abspath(self.pdf_path))
            pdf_filename = os.path.basename(self.pdf_path)
            instrumented_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_workspace.html")
            
            original_texts_map, tid_to_page = instrument_html(raw_html_path, instrumented_html_path)
            
            self.status_update.emit("✅ Espace de travail configuré.")
            self.finished.emit(instrumented_html_path, original_texts_map, tid_to_page)

        except Exception as e:
            logger.error(f"Erreur durant l'extraction du document : {e}")
            self.error.emit(str(e))