# src/utils/pdf_metadata.py

import os
import re
from loguru import logger

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

def get_pdf_metadata(pdf_path: str, translation_stats: dict = None) -> dict:
    """
    Extrait de manière fiable toutes les propriétés physiques et métadonnées du PDF.
    """
    stats = {
        "file_path": pdf_path,
        "file_size": f"{os.path.getsize(pdf_path) / (1024*1024):.2f} MB",
        "pdf_version": "1.4",
        "linearized": "Non",
        "tagged": "Non",
        "page_size": "Inconnu",
        "pages_count": 0,
        "title": "Inconnu",
        "subject": "Inconnu",
        "creator": "Inconnu",
        "author": "Inconnu",
        "producer": "Inconnu",
        "keywords": "Aucun",
        "created_date": "Inconnu",
        "mod_date": "Inconnu",
    }
    
    # 1. Lecture rapide de la version PDF et de la linéarisation dans le flux binaire d'origine
    try:
        with open(pdf_path, 'rb') as f:
            first_kb = f.read(1024)
            # Match le marqueur %PDF-1.x
            m = re.search(r'%PDF-(\d\.\d)', first_kb.decode('latin1', errors='ignore'))
            if m:
                stats["pdf_version"] = f"PDF-{m.group(1)}"
            if b"/Linearized" in first_kb:
                stats["linearized"] = "Oui"
    except Exception as e:
        logger.warning(f"Impossible de lire le flux binaire du PDF : {e}")

    # 2. Extraction des métadonnées structurelles via pypdf
    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            stats["pages_count"] = len(reader.pages)
            
            # Extraction géométrique de la taille de la première page
            if len(reader.pages) > 0:
                box = reader.pages[0].mediabox
                # Conversion des points d'impression PDF (1/72 inch) en centimètres
                w_cm = float(box.width) * 0.0352778
                h_cm = float(box.height) * 0.0352778
                stats["page_size"] = f"[{w_cm:.2f} * {h_cm:.2f} cm]"
            
            catalog = reader.trailer.get('/Root', {})
            if '/MarkInfo' in catalog or '/StructTreeRoot' in catalog:
                stats["tagged"] = "Oui"
                
            meta = reader.metadata
            if meta:
                stats["title"] = meta.title or os.path.splitext(os.path.basename(pdf_path))[0]
                stats["subject"] = meta.subject or "Inconnu"
                stats["creator"] = meta.creator or "Inconnu"
                stats["author"] = meta.author or "Inconnu"
                stats["producer"] = meta.producer or "Inconnu"
                stats["keywords"] = meta.get('/Keywords') or "Aucun"
                
                stats["created_date"] = parse_pdf_date(meta.get('/CreationDate'))
                stats["mod_date"] = parse_pdf_date(meta.get('/ModDate'))
        except Exception as e:
            logger.warning(f"Erreur d'extraction de métadonnées pypdf : {e}")
            
    # Injection de nos métadonnées uniques d'application
    if translation_stats:
        stats.update(translation_stats)
        
    return stats

def parse_pdf_date(date_str) -> str:
    """Formatte les dates PDF standardisées (ex: D:20240828...) en format lisible."""
    if not date_str:
        return "Inconnu"
    if date_str.startswith("D:"):
        date_str = date_str[2:]
    match = re.match(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}:{match.group(5)}:{match.group(6)}"
    return date_str