"""
RockTranslate — Main Application Entry Point
Path: main.py

This script initializes the environment, sets up global logging, configures High-DPI
scaling, loads system locales, and launches the primary PyQt6 GUI MainWindow.
Uses lazy-importing to guarantee an instantaneous splash screen display on startup.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
from loguru import logger

# ── TIKTOKEN PYINSTALLER RUNTIME HOOK ──
# If running inside a compiled PyInstaller frozen bundle, manually register
# the tiktoken encoding constructors to bypass its broken dynamic package lookup.
if hasattr(sys, "_MEIPASS"):
    try:
        import tiktoken.registry
        import tiktoken_ext.openai_public
        tiktoken.registry.ENCODING_CONSTRUCTORS = dict(
            tiktoken_ext.openai_public.ENCODING_CONSTRUCTORS
        )
    except ImportError:
        pass
# ───────────────────────────────────────

# Resolve system search paths dynamically to prevent ModuleNotFoundErrors
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, "src")

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from PyQt6.QtWidgets import QApplication, QSplashScreen  
from PyQt6.QtGui import QFont, QPixmap, QColor 
from PyQt6.QtCore import QTranslator, QLocale, QSettings, Qt


# --- IMPORTANT: MainWindow is NOT imported here at the top ---
# This prevents heavy C++ QtWebEngine modules from delaying the startup.

def main() -> None:
    """
    Primary runtime initialization routine. Configures systemic dependencies,
    loads translation tables, and executes the Qt application loop.
    """
    # Writing inside Program Files is restricted on Windows, so we redirect logs to %LOCALAPPDATA%
    # 1. Setup robust logging file rotation in a secure, dynamically-routed directory
    # If compiled/frozen, write to writable OS folders; if in dev mode, keep logs locally.
    if hasattr(sys, "_MEIPASS"):
        if os.name == "nt":
            app_data_dir = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
            log_dir = os.path.join(app_data_dir, "RockTranslate", "logs")
        else:
            log_dir = os.path.expanduser("~/.config/rocktranslate/logs")
    else:
        # Standard local development run
        log_dir = os.path.join(current_dir, "logs")
        
    os.makedirs(log_dir, exist_ok=True)
    logger.add(
        os.path.join(log_dir, "app.log"),
        rotation="10 MB",
        retention="5 days",
        level="INFO",
        encoding="utf-8"
    )
    logger.info("Initializing RockTranslate application lifecycle...")

    # 2. Instantiate QApplication with high-DPI scaling active by default in PyQt6
    # Configure OpenGL Context Sharing and Instantiate QApplication
    # This attribute must be set BEFORE QApplication is constructed
    # to allow lazy-loading QtWebEngineWidgets dynamically during the splash screen.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setOrganizationName("RockTranslate")
    app.setFont(QFont("Segoe UI", 10))
    

     # ── 3. SHOW SPLASH SCREEN IMMEDIATELY ──
    # Look for the splash image inside our assets directory
    # Since we haven't loaded MainWindow yet, this block executes in under 50ms!
    try:
        from src.core.constants import DEFAULT_ASSETS_DIR
    except ImportError: 
        from core.constants import DEFAULT_ASSETS_DIR # type: ignore

    splash_path = os.path.join(DEFAULT_ASSETS_DIR, "rocktranslate_logo.png")
    splash = None
    
    if os.path.exists(splash_path):
        pixmap = QPixmap(splash_path)
        # Scaled to fit beautifully while loading
        scaled_pixmap = pixmap.scaled(
            500*2, 300*2, 
            Qt.AspectRatioMode.KeepAspectRatio, 
            Qt.TransformationMode.SmoothTransformation
        )
        splash = QSplashScreen(scaled_pixmap)
        # Show splash with top-most window hint
        splash.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        splash.show()
        splash.showMessage(
            "Initializing translation engine...", 
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, 
            QColor("#cbd5e0")
        )
        # Force the OS to instantly draw the window on screen
        app.processEvents()

    # 4. Initialize Internationalization (i18n)
    if splash:
        splash.showMessage(
            "Loading active locales...", 
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, 
            QColor("#cbd5e0")
        )
        app.processEvents()

    # Detects system locale and loads translated .qm packages if available
    translator = QTranslator()
    
    # Check if the user has manually set a custom language preference
    system_settings = QSettings("RockTranslate", "SystemConfig")
    user_lang = system_settings.value("ui_language", "", type=str)
    
    if user_lang:
        active_lang = user_lang
        logger.info(f"Using user-defined UI language preference: {active_lang}")
    else:
        # Fallback to system locale detection
        system_locale = QLocale.system().name()  # e.g., 'fr_FR' or 'es_ES'
        active_lang = system_locale.split("_")[0]
        logger.info(f"No user preference found. Defaulting to system locale: {active_lang}")
        
    translations_path = os.path.join(current_dir, "src", "assets", "translations")
    if os.path.exists(translations_path):
        if translator.load(f"rocktranslate_{active_lang}", translations_path):
            app.installTranslator(translator)
            logger.info(f"Loaded active translation package for locale: {active_lang}")
        else:
            logger.info(f"No translation package found for locale: {active_lang}. Defaulting to English.")

    
    if splash:
        splash.showMessage(
            "Configuring workspace interface...", 
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, 
            QColor("#cbd5e0")
        )
        app.processEvents()

    # 5. Launch Main MainWindow
    try:
        try:
            from src.ui_pyqt.main_window import MainWindow # <-- IMPORT INTRADÉPARTEMENTAL (LAZY)
        except ImportError:
            from ui_pyqt.main_window import MainWindow # type: ignore
     
        window = MainWindow()
        window.showMaximized()

        # Close the splash screen and transfer focus to the main window
        if splash:
            splash.finish(window)

        logger.info("MainWindow displayed successfully. Executing application loop...")
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Unhandled critical exception raised during execution loop: {e}")
        if splash:
            splash.close()
        sys.exit(1)


if __name__ == "__main__":
    main()