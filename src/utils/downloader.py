# utils/downloader.py

import os
import sys
import zipfile
import urllib.request

# Détection dynamique du dossier assets de production
if os.path.exists("./src/assets"):
    DEFAULT_ASSETS_DIR = os.path.abspath("./src/assets")
else:
    DEFAULT_ASSETS_DIR = os.path.abspath("./assets")


def _download_and_extract(url: str, dest_dir: str, zip_name: str) -> bool:
    """Helper générique pour télécharger et extraire un fichier ZIP de manière sécurisée."""
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, zip_name)
    
    try:
        def progress(count, block_size, total_size):
            percent = int(count * block_size * 100 / total_size)
            sys.stdout.write(f"\rTéléchargement : {min(percent, 100)}%")
            sys.stdout.flush()
            
        urllib.request.urlretrieve(url, zip_path, reporthook=progress)
        print() # Retour à la ligne après le décompte
        
        print("⚙️ Extraction de l'archive...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(dest_dir)
            
        os.remove(zip_path) # Nettoyage du fichier temporaire ZIP
        return True
    except Exception as e:
        print(f"❌ Échec de l'opération : {e}")
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return False


def check_and_download_pdf2htmlex(assets_dir: str = DEFAULT_ASSETS_DIR) -> str | None:
    """
    Vérifie la présence locale de pdf2htmlEX dans le dossier assets de production.
    Promène un téléchargement propre si absent.
    """
    # Correction : On cible explicitement pdf2htmlEX et non pdfjs
    pdf2html_dir = os.path.join(assets_dir, "pdf2htmlEX")
    local_exe = os.path.join(pdf2html_dir, "pdf2htmlEX.exe")
    
    if os.path.exists(local_exe):
        return local_exe
        
    print("📥 pdf2htmlEX manquant. Lancement du téléchargement automatique...")
    url = "https://shuvomoy.github.io/blogs/assets/pdf2htmlEX/pdf2htmlEX-win32-0.14.6-with-poppler-data.zip"
    
    success = _download_and_extract(url, pdf2html_dir, "pdf2htmlEX.zip")
    if success:
        # Recherche récursive de l'exécutable après extraction
        for root, _, files in os.walk(pdf2html_dir):
            if "pdf2htmlEX.exe" in files:
                return os.path.join(root, "pdf2htmlEX.exe")
    return None


def check_and_download_pdfjs(assets_dir: str = DEFAULT_ASSETS_DIR) -> str | None:
    """
    Vérifie la présence locale de PDF.js (de Mozilla) dans le dossier assets de production.
    Télécharge et configure la structure s'il est absent.
    """
    pdfjs_dir = os.path.join(assets_dir, "pdfjs")
    local_viewer = os.path.join(pdfjs_dir, "web", "viewer.html")
    
    if os.path.exists(local_viewer):
        return local_viewer
        
    print("📥 PDF.js manquant. Lancement du téléchargement automatique...")
    # Version v3.11.174 de Mozilla, ultra-stable et compatible hors-ligne
    url = "https://github.com/mozilla/pdf.js/releases/download/v3.11.174/pdfjs-3.11.174-dist.zip"
    
    success = _download_and_extract(url, pdfjs_dir, "pdfjs.zip")
    if success and os.path.exists(local_viewer):
        print("✅ Moteur PDF.js configuré avec succès.")
        return local_viewer
    return None