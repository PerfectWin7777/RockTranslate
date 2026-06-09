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
    finished      = pyqtSignal(str, dict)        # Émet (instrumented_html_path, dictionnaire_textes)
    error         = pyqtSignal(str)              # Émet le message en cas d'erreur fatale

    def __init__(self, pdf_path: str, assets_dir: str = "src/assets"):
        super().__init__()
        self.pdf_path = pdf_path
        self.assets_dir = assets_dir

    def run(self):
        try:
            self.status_update.emit("⚙️ Conversion haute fidélité du PDF en cours...")
            logger.info(f"Lancement de la conversion du PDF : {self.pdf_path}")
            
            # Étape A : Conversion unifiée via pdf2htmlEX
            raw_html_path = convert_pdf_to_html(self.pdf_path, self.assets_dir)
            if not raw_html_path or not os.path.exists(raw_html_path):
                self.error.emit("La conversion géométrique par pdf2htmlEX a échoué.")
                return

            self.status_update.emit("⚙️ Analyse et instrumentation BeautifulSoup en cours...")
            logger.info("Extraction et empaquetage sémantique avec BeautifulSoup...")
            
            # Étape B : Instrumentation du fichier et génération de la carte sémantique de traduction
            pdf_dir = os.path.dirname(os.path.abspath(self.pdf_path))
            pdf_filename = os.path.basename(self.pdf_path)
            instrumented_html_path = os.path.join(pdf_dir, f"{os.path.splitext(pdf_filename)[0]}_workspace.html")
            
            original_texts_map = instrument_html(raw_html_path, instrumented_html_path)
            
            self.status_update.emit("✅ Espace de travail configuré.")
            self.finished.emit(instrumented_html_path, original_texts_map)

        except Exception as e:
            logger.error(f"Erreur durant l'extraction du document : {e}")
            self.error.emit(str(e))