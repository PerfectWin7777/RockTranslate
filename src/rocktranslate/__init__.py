"""
RockTranslate — High-Fidelity PDF Layout-Preserved Translation Tool
Path: src/rocktranslate/__init__.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0

"""

from .core.html_transformer import convert_pdf_to_html, instrument_html
from .api import RockTranslator

__version__ = "1.0.0"
__all__ = ["convert_pdf_to_html", "instrument_html", "RockTranslator"]