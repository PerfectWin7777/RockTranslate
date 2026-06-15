"""
RockTranslate — Unified pywebview Desktop Host API Bridge
Path: src/rocktranslate/core/web_api.py

Aggregates modular mixin classes (History, Config, and Translation)
to expose unified endpoints to the Web UI context.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.1
"""

import webview
from typing import Optional
import os
import tempfile
import re
import json
from loguru import logger
import shutil
from .renderer import resolve_pdf_renderer, apply_translations_offline, print_html_to_vector_pdf
from .pdf_metadata import get_pdf_metadata

# Import our decoupled mixins from the api package folder
from .api import HistoryApiMixin, ConfigApiMixin, TranslationApiMixin


class RockTranslateAPI(HistoryApiMixin, ConfigApiMixin, TranslationApiMixin):
    """
    Main host API bridge communicating with JavaScript.
    Inherits methods and attributes from history, configuration, and translation components.
    """
    def __init__(self) -> None:
        super().__init__()
        
        # Private window reference to prevent WebView2 recursive serialization loops
        self._window: Optional[webview.Window] = None

    # ── EXPOSED TRANSLATION ENDPOINTS ──
    def start_translation(self) -> None:
        """Starts a full translation run on the active document."""
        self.start_full_translation()

    def translate_pages(self, range_str: str) -> None:
        """Starts a range translation run on selected pages."""
        self.start_range_translation(range_str)

    def cancel_translation(self) -> None:
        """Stops the active translation background thread."""
        self.stop_translation()

    def reset_translation_state(self) -> None:
        """Clears translation memory and restores original document DOM."""
        self.reset_all_translations()
    

    def is_document_translated(self) -> bool:
        """Exposed endpoint to check if document is already fully translated."""
        return super().is_document_translated()
    
    # ── EXPOSED WINDOW MANAGEMENT ENDPOINTS ──
    def toggle_fullscreen(self) -> None:
        """
        Bascule l'état d'affichage de l'application en mode plein écran 
        ou en affichage fenêtré standard.
        """
        if self._window:
            self._window.toggle_fullscreen()

    def quit_application(self) -> None:
        """
        Ferme proprement l'application de bureau et libère toutes les ressources.
        """
        if self._window:
            self._window.destroy()

    
    def close_document(self) -> None:
        """Exposed endpoint to close the active document and run cache cleanup."""
        super().close_document()
    
   