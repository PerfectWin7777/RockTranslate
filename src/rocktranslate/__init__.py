"""
RockTranslate — High-Fidelity PDF Layout-Preserved Translation Tool
Path: src/rocktranslate/__init__.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0

"""

from .core.html_transformer import convert_pdf_to_html, instrument_html
from .api import (RockTranslator, ask, explain, extract, glossary, side_by_side, summarize, translate,
                  translate_text)
from .document import Chunk, Document, Element

__version__ = "2.0.6"
__all__ = ["extract", "translate", "translate_text", "explain", "summarize", "glossary", "ask", "side_by_side",
           "Document", "Element", "Chunk", "RockTranslator",
           "convert_pdf_to_html", "instrument_html"]