"""
RockTranslate — Reliable PDF Metadata and Layout Dimension Extractor
Path: utils/pdf_metadata.py

This module extracts physical characteristics, structural flags, and standard 
PDF metadata from documents. Default values are programmatically kept in English
to comply with i18n standards, allowing seamless UI localization later on.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import re
from typing import Dict, Optional, Any
from loguru import logger

# Safe optional import of pypdf, providing graceful fallbacks if not installed
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None


def get_pdf_metadata(pdf_path: str, translation_stats: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """
    Extracts physical and metadata properties of a PDF file.

    Reads structural byte-markers (PDF version, linearization) and relies 
    on pypdf to read metadata details, returning a unified properties dictionary.

    Args:
        pdf_path: The absolute filesystem path to the PDF document.
        translation_stats: Optional dictionary holding custom RockTranslate statistics.

    Returns:
        Dict[str, Any]: Map containing file dimensions, dates, counts, and descriptions.
    """
    # Programmatic defaults are defined in English to align with open-source design
    stats: Dict[str, Any] = {
        "file_path": pdf_path,
        "file_size": f"{os.path.getsize(pdf_path) / (1024 * 1024):.2f} MB",
        "pdf_version": "1.4",
        "linearized": "No",
        "tagged": "No",
        "page_size": "Unknown",
        "pages_count": 0,
        "title": "Unknown",
        "subject": "Unknown",
        "creator": "Unknown",
        "author": "Unknown",
        "producer": "Unknown",
        "keywords": "None",
        "created_date": "Unknown",
        "mod_date": "Unknown",
    }
    
    # 1. Inspect the binary stream header (PDF version and linearization flag)
    try:
        with open(pdf_path, 'rb') as f:
            first_kb: bytes = f.read(1024)
            # Match standard %PDF-1.x header signature
            version_match = re.search(r'%PDF-(\d\.\d)', first_kb.decode('latin1', errors='ignore'))
            if version_match:
                stats["pdf_version"] = f"PDF-{version_match.group(1)}"
            if b"/Linearized" in first_kb:
                stats["linearized"] = "Yes"
    except Exception as e:
        logger.warning(f"Could not read PDF raw binary stream: {e}")

    # 2. Extract structural meta details using pypdf parser
    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            stats["pages_count"] = len(reader.pages)
            
            # Convert default PDF media points (1/72 of an inch) to centimeters
            if len(reader.pages) > 0:
                box = reader.pages[0].mediabox
                w_cm: float = float(box.width) * 0.0352778
                h_cm: float = float(box.height) * 0.0352778
                stats["page_size"] = f"[{w_cm:.2f} x {h_cm:.2f} cm]"
            
            catalog = reader.trailer.get('/Root', {})
            if '/MarkInfo' in catalog or '/StructTreeRoot' in catalog:
                stats["tagged"] = "Yes"
                
            meta = reader.metadata
            if meta:
                stats["title"] = meta.title or os.path.splitext(os.path.basename(pdf_path))[0]
                stats["subject"] = meta.subject or "Unknown"
                stats["creator"] = meta.creator or "Unknown"
                stats["author"] = meta.author or "Unknown"
                stats["producer"] = meta.producer or "Unknown"
                stats["keywords"] = meta.get('/Keywords') or "None"
                
                stats["created_date"] = parse_pdf_date(meta.get('/CreationDate'))
                stats["mod_date"] = parse_pdf_date(meta.get('/ModDate'))
        except Exception as e:
            logger.warning(f"Failed to extract structural metadata with pypdf: {e}")
    else:
        logger.warning("pypdf is not installed. Structural metadata extraction skipped.")
            
    # Safely merge custom application translation statistics if provided
    if translation_stats:
        stats.update(translation_stats)
        
    return stats


def parse_pdf_date(date_str: Optional[str]) -> str:
    """
    Standardizes standard PDF Date format sequences (e.g., D:YYYYMMDD...) into a human-readable date.

    Args:
        date_str: Raw PDF date string value.

    Returns:
        str: ISO formatted date-time string (YYYY-MM-DD HH:MM:SS) or 'Unknown'.
    """
    if not date_str:
        return "Unknown"
    
    if date_str.startswith("D:"):
        date_str = date_str[2:]
        
    # Corrected regex pattern from the legacy typo (removed duplicate caret)
    match = re.match(r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', date_str)
    if match:
        return (
            f"{match.group(1)}-{match.group(2)}-{match.group(3)} "
            f"{match.group(4)}:{match.group(5)}:{match.group(6)}"
        )
    return date_str