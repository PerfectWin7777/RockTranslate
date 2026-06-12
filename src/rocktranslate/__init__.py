"""
RockTranslate — High-Fidelity PDF Layout-Preserved Translation Tool
Path: src/rocktranslate/__init__.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0

"""

from typing import Optional

# Expose programmatic API to developers
from .core.html_transformer import convert_pdf_to_html, instrument_html
from .core.llm_client import LLMClient

__version__ = "1.0.0"
__all__ = ["convert_pdf_to_html", "instrument_html", "LLMClient"]