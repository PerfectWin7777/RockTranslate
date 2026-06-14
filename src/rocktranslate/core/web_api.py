"""
RockTranslate — Unified pywebview Desktop Host API Bridge
Path: src/rocktranslate/core/web_api.py

Aggregates modular mixin classes (History, Config, and eventually Translation)
to expose unified endpoints to the Web UI context.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import webview
from typing import Optional

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