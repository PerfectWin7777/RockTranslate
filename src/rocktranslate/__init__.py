"""
RockTranslate — High-Fidelity PDF Layout-Preserved Translation Tool
Path: src/rocktranslate/__init__.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0

"""

from .core.html_transformer import convert_pdf_to_html, instrument_html
from .api import RockTranslator, extract, translate
from .document import Chunk, Document, Element

__version__ = "2.0.5"
__all__ = ["extract", "translate", "Document", "Element", "Chunk", "RockTranslator",
           "convert_pdf_to_html", "instrument_html"]