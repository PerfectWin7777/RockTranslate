"""
RockTranslate — Main Application Entry Point
Path: main.py

This script initializes the environment, sets up global logging, configures High-DPI
scaling, loads system locales, and launches the primary PyQt6 GUI MainWindow.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
from loguru import logger

# Resolve system search paths dynamically to prevent ModuleNotFoundErrors
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, "src")

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QTranslator, QLocale

# Modular imports
try:
    from src.ui_pyqt.main_window import MainWindow
except ImportError:
    from ui_pyqt.main_window import MainWindow # type: ignore


def main() -> None:
    """
    Primary runtime initialization routine. Configures systemic dependencies,
    loads translation tables, and executes the Qt application loop.
    """
    # 1. Setup robust logging file rotation
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
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setOrganizationName("RockTranslate")
    
    # 3. Set up systemic typography baseline
    app.setFont(QFont("Segoe UI", 10))

    # 4. Initialize Internationalization (i18n)
    # Detects system locale and loads translated .qm packages if available
    translator = QTranslator()
    system_locale = QLocale.system().name()  # e.g., 'fr_FR' or 'en_US'
    
    translations_path = os.path.join(current_dir, "src", "assets", "translations")
    if os.path.exists(translations_path):
        if translator.load(f"rocktranslate_{system_locale}", translations_path):
            app.installTranslator(translator)
            logger.info(f"Loaded active translation package for locale: {system_locale}")
        else:
            logger.info(f"No translation package found for locale: {system_locale}. Defaulting to English.")

    # 5. Launch Main MainWindow
    try:
        window = MainWindow()
        window.showMaximized()
        logger.info("MainWindow displayed successfully. Executing application loop...")
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Unhandled critical exception raised during execution loop: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()