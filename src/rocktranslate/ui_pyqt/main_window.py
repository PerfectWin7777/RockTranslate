"""
RockTranslate — Core Window Orchestrator and Workspace Controller
Path: src/rocktranslate/ui_pyqt/main_window.py

This module implements the primary Desktop application window, managing:
1. Dynamic drag-and-drop dashboard interfaces.
2. Dual-pane synchronous WebEngine viewports.
3. Event-driven progress bars, zoom widgets, and dynamic menu maps.
4. Asynchronous worker thread operations (extraction, LLM translation).

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import sys
import re
import subprocess
import webbrowser

# ── DYNAMIC SYSTEM PATH RESOLUTION ──
# Allows direct script execution of main_window.py for fast local development.
# Path: src/rocktranslate/ui_pyqt/main_window.py -> we go up 2 levels to get 'src'
current_dir = os.path.dirname(os.path.abspath(__file__))  # src/rocktranslate/ui_pyqt
src_parent_dir = os.path.abspath(os.path.join(current_dir, "..", ".."))  # src

if src_parent_dir not in sys.path:
    sys.path.insert(0, src_parent_dir)
# ────────────────────────────────────

import datetime
import json
from typing import Optional, Dict, List, Any, Set
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QFileDialog, QMessageBox, QLabel, QStatusBar, QStackedWidget, QFrame,
    QHBoxLayout, QScrollArea, QPushButton, QDialog,
    QInputDialog
)
from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QKeySequence, QAction, QActionGroup, QPixmap, QIcon

# Absolute imports from the rocktranslate package
from rocktranslate.core.constants import DEFAULT_PROVIDERS, DEFAULT_ASSETS_DIR
from rocktranslate.ui_pyqt.widget.workspace_viewer import WorkspaceViewer
from rocktranslate.ui_pyqt.widget.progress_panel import ProgressPanel
from rocktranslate.ui_pyqt.widget.zoom_widget import ZoomWidget
from rocktranslate.ui_pyqt.widget.properties_dialog import DocumentPropertiesDialog
from rocktranslate.ui_pyqt.widget.api_config_dialog import APIConfigDialog
from rocktranslate.ui_pyqt.widget.system_settings_dialog import SystemWorkflowDialog
from rocktranslate.ui_pyqt.widget.translation_settings_dialog import TranslationWorkflowDialog
from rocktranslate.ui_pyqt.widget.about_dialog import AboutDialog
from rocktranslate.ui_pyqt.workers.extraction_worker import ExtractionWorker
from rocktranslate.ui_pyqt.workers.translation_worker import TranslationWorker
from rocktranslate.ui_pyqt.utils.pdf_exporter import PDFExporter
from rocktranslate.core.pdf_metadata import get_pdf_metadata
from rocktranslate.ui_pyqt.utils.recent_files_manager import RecentFilesManager
from rocktranslate.core.downloader import check_and_download_pdfjs, check_and_download_pdf2htmlex



def parse_page_range(range_str: str, max_pages: int) -> List[int]:
    """
    Parses a user-defined page range string into a sorted list of zero-based page indices.
    Tolerates spaces, handles inverted ranges (e.g., "5-2"), and filters out invalid 
    or out-of-bounds pages.

    Args:
        range_str: User input string (e.g., "2-5, 9, 12-10").
        max_pages: Maximum page count of the active PDF.

    Returns:
        List[int]: Sorted list of unique zero-based page indices.
    """
    pages: Set[int] = set()
    if not range_str.strip():
        return []

    # Split by comma for distinct pages/ranges
    parts = range_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            # Handle page range: e.g., "2-5" or "10-8"
            sub_parts = part.split('-')
            if len(sub_parts) == 2:
                try:
                    start_val = int(sub_parts[0].strip())
                    end_val = int(sub_parts[1].strip())
                    
                    # Validate values are within physical boundaries
                    if 1 <= start_val <= max_pages and 1 <= end_val <= max_pages:
                        # Support both standard (2-5) and inverted (5-2) formats
                        min_val = min(start_val, end_val)
                        max_val = max(start_val, end_val)
                        for p in range(min_val, max_val + 1):
                            pages.add(p - 1)  # Shift to zero-based index
                except ValueError:
                    continue
        else:
            # Handle single page: e.g., "9"
            try:
                p = int(part)
                if 1 <= p <= max_pages:
                    pages.add(p - 1)  # Shift to zero-based index
            except ValueError:
                continue

    return sorted(list(pages))




class RecentFileItem(QFrame):
    """
    Individual card representing a verified, interactive recent document link.
    """
    clicked = pyqtSignal(str)

    def __init__(self, file_path: str, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the file card.

        Args:
            file_path: Absolute validated filesystem path.
            parent: Optional parent QWidget container.
        """
        super().__init__(parent)
        self.file_path: str = file_path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("RecentItem")
        self.setStyleSheet("""
            #RecentItem {
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                border-radius: 6px;
                padding: 10px;
                margin-bottom: 4px;
            }
            #RecentItem:hover {
                background-color: #f7fafc;
                border-color: #4f8ef7;
            }
            #RecentItem QLabel {
                border: none !important;
                background: transparent !important;
                border-radius: 0px !important;
            }
            QLabel[class="name"] {
                color: #2d3748;
                font-weight: bold;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
            }
            QLabel[class="path"] {
                color: #718096;
                font-size: 9px;
                font-family: 'Segoe UI', sans-serif;
            }
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        icon = QLabel("📄", self)
        icon.setFont(QFont("Segoe UI", 16))
        icon.setFixedWidth(24)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        
        name_lbl = QLabel(os.path.basename(self.file_path), self)
        name_lbl.setProperty("class", "name")
        
        path_lbl = QLabel(self.file_path, self)
        path_lbl.setProperty("class", "path")
        path_lbl.setWordWrap(True)

        text_layout.addWidget(name_lbl)
        text_layout.addWidget(path_lbl)

        layout.addWidget(icon)
        layout.addLayout(text_layout)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.file_path)
        super().mousePressEvent(event)


class WelcomeDashboard(QFrame):
    """
    Main opening landing interface featuring:
    - Left side: Drag & Drop active zones or manual browse triggers.
    - Right side: Dynamic synchronized lists of recently accessed documents.
    """
    file_dropped = pyqtSignal(str)

    def __init__(self, recent_manager: RecentFilesManager, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the Welcome Dashboard.

        Args:
            recent_manager: Centralized, synchronized recent history manager.
            parent: Optional parent QWidget.
        """
        super().__init__(parent)
        self.recent_manager: RecentFilesManager = recent_manager
        self.setAcceptDrops(True)
        self.setStyleSheet("WelcomeDashboard { background-color: #f7fafc; border: none; }")
        self._build_ui()
        
        # Re-sync lists automatically when historical values are mutated elsewhere
        self.recent_manager.history_changed.connect(self.refresh_recent_files)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(30)

        # ── LEFT PANE: Active Open File / Drop Area ──
        # --- LEFT PANE: Active Open File / Drop Area ---
        self.drop_panel = QFrame(self)
        self.drop_panel.setStyleSheet("""
            QFrame {
                border: 2px dashed #cbd5e0;
                border-radius: 12px;
                background: #ffffff;
            }
        """)
        drop_layout = QVBoxLayout(self.drop_panel)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.setContentsMargins(40, 40, 40, 40)
        drop_layout.setSpacing(0)  # Standardize spacing internally

        # Dynamic spacer to gently push the content down from the top,
        # but leaving more space at the bottom to keep the logo positioned higher.
        drop_layout.addStretch(1)

        # 1. Logo container configuration
        self.lbl_logo = QLabel(self)
        self.lbl_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_logo.setStyleSheet("border: none; background: transparent;")
        
        logo_path = os.path.join(DEFAULT_ASSETS_DIR, "RockTranslate_logo.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            # High-fidelity scale: doubled resolution for high-DPI (Retina) displays,
            # with a maximum visual boundary of 480x240 for standard viewport layouts.
            scaled_pixmap = pixmap.scaled(
                480*2, 240*2, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.lbl_logo.setPixmap(scaled_pixmap)
            self.lbl_logo.setMaximumWidth(480*2)
        else:
            self.lbl_logo.setText("RockTranslate")
            self.lbl_logo.setFont(QFont("Segoe UI", 28, QFont.Weight.Bold))
            self.lbl_logo.setStyleSheet("color: #2d3748; border: none; background: transparent;")

        drop_layout.addWidget(self.lbl_logo, 0, Qt.AlignmentFlag.AlignCenter)
        
        # Clean, modern spacing between the logo and the subtitle block
        drop_layout.addSpacing(15)

        # 2. Subtitle configuration
        subtitle = QLabel(self.tr("Drag & Drop your scientific PDF here"), self)
        subtitle.setFont(QFont("Segoe UI", 20))
        subtitle.setStyleSheet("color: #a0aec0; border: none; background: transparent;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)

        drop_layout.addSpacing(12)

        # 3. Action button configuration
        self.btn_open_file = QPushButton(self.tr("Open File..."), self)
        self.btn_open_file.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_file.setFixedWidth(260)  # Centered, elegant fixed-width action button
        self.btn_open_file.setStyleSheet("""
            QPushButton {
                background-color: #4f8ef7;
                border: none;
                border-radius: 6px;
                color: white;
                font-weight: bold;
                padding: 10px 20px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #3b7ad4;
            }
        """)
        drop_layout.addWidget(self.btn_open_file, 0, Qt.AlignmentFlag.AlignCenter)

        drop_layout.addSpacing(20)

        # 4. Connection status bar configuration
        self.lbl_status = QLabel(self)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_status.setStyleSheet("border: none; background: transparent;")
        self._check_api_keys()
        drop_layout.addWidget(self.lbl_status, 0, Qt.AlignmentFlag.AlignCenter)

        # Larger stretch at the bottom to balance gravity and maintain the higher position
        drop_layout.addStretch(3)

        main_layout.addWidget(self.drop_panel, 1)

        # ── RIGHT PANE: Recent Files List ──
        self.recent_panel = QFrame(self)
        self.recent_panel.setFixedWidth(400)
        self.recent_panel.setStyleSheet("""
            QFrame {
                background: #ffffff;
                border-radius: 12px;
                border: 1px solid #e2e8f0;
            }
        """)
        recent_layout = QVBoxLayout(self.recent_panel)
        recent_layout.setContentsMargins(15, 15, 15, 15)
        recent_layout.setSpacing(10)

        recent_title = QLabel(self.tr("Recent Documents"), self)
        recent_title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        recent_title.setStyleSheet("color: #2d3748; border: none; background: transparent;")
        recent_layout.addWidget(recent_title)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.scroll_content = QWidget()
        self.scroll_content.setStyleSheet("background: transparent;")
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(6)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.scroll.setWidget(self.scroll_content)
        recent_layout.addWidget(self.scroll, 1)

        main_layout.addWidget(self.recent_panel, 0)
        
        self.refresh_recent_files()

    def _check_api_keys(self) -> None:
        """ Verifies configuration states and displays live API connection feedback labels. """
        settings = QSettings("RockTranslate", "APIConfig")
        provider = settings.value("provider", "Google Gemini")
        
        raw_keys = settings.value("api_keys_by_provider", "{}")
        try:
            keys_dict = json.loads(raw_keys) if isinstance(raw_keys, str) else raw_keys
        except Exception:
            keys_dict = {}
        active_key: str = keys_dict.get(provider, "")

        fallback_model: str = DEFAULT_PROVIDERS[provider]["models"][0]
        active_model: str = settings.value(f"last_model_{provider}", fallback_model)

        if provider == "Ollama (Local)":
            self.lbl_status.setText(self.tr("● Local Mode Active (Ollama: {model})").format(model=active_model))
            self.lbl_status.setStyleSheet("color: #38a169; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        elif active_key:
            self.lbl_status.setText(self.tr("● AI Active: {provider} ({model})").format(provider=provider, model=active_model))
            self.lbl_status.setStyleSheet("color: #38a169; font-weight: bold; font-size: 11px; border: none; background: transparent;")
        else:
            self.lbl_status.setText(self.tr("○ Setup Required: Missing API key for {provider}").format(provider=provider))
            self.lbl_status.setStyleSheet("color: #e53e3e; font-size: 11px; border: none; background: transparent;")

    def refresh_recent_files(self) -> None:
        """ Rebuilds file historical card grids. """
        while self.scroll_layout.count():
            child = self.scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        recent_list: List[str] = self.recent_manager.get_recent_files()
        
        if not recent_list:
            empty_lbl = QLabel(self.tr("No recent documents found."), self)
            empty_lbl.setStyleSheet("color: #718096; border: none; font-size: 11px; background: transparent;")
            self.scroll_layout.addWidget(empty_lbl)
            return

        for path in recent_list:
            item = RecentFileItem(path, self)
            item.clicked.connect(self.file_dropped.emit)
            self.scroll_layout.addWidget(item)

    def dragEnterEvent(self, event: Any) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:
        for url in event.mimeData().urls():
            file_path: str = url.toLocalFile()
            if file_path.lower().endswith(".pdf"):
                self.file_dropped.emit(file_path)
                break


class MainWindow(QMainWindow):
    """
    Main orchestrator window managing multi-pane states, action bars,
    worker synchronizations, and menu setups.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RockTranslate")
        self.resize(1440, 900)
        # Load and apply the application window icon
        icon_path = os.path.join(DEFAULT_ASSETS_DIR, "rocktranslate_icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Unified Application State Map
        self._pdf_path: Optional[str] = None
        self._instrumented_html_path: Optional[str] = None
        self._original_texts: Dict[str, str] = {}
        self._zoom: float = 0.8

        self._ext_worker: Optional[ExtractionWorker] = None
        self._trans_worker: Optional[TranslationWorker] = None
        
        self._current_model: Optional[str] = None
        self._current_lang: str = "French"

        self._tid_to_page: Dict[str, int] = {}
        self._current_translating_page: int = -1
        self._translated_pages: Dict[int, Dict[str, str]] = {}

        # ── INITIALIZE PERSISTENCE MANAGERS ──
        self.recent_manager = RecentFilesManager(self)

        # Trigger automatic download verifications silently on startup
        check_and_download_pdfjs()
        check_and_download_pdf2htmlex()

        self._build_menu()
        self._build_ui()
        
        # Connect dynamic triggers
        self.recent_manager.history_changed.connect(self._populate_recent_menu)

    def _build_ui(self) -> None:
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        # Dashboard Landing Screen (Page 0)
        self.welcome_screen = WelcomeDashboard(self.recent_manager, self)
        self.welcome_screen.file_dropped.connect(self._open_pdf_by_path)
        self.welcome_screen.btn_open_file.clicked.connect(self._open_pdf_dialog)
        self.stacked_widget.addWidget(self.welcome_screen)

        # Main Workspace Container (Page 1)
        workspace = QWidget()
        work_layout = QVBoxLayout(workspace)
        work_layout.setContentsMargins(0, 0, 0, 0)
        work_layout.setSpacing(0)

        # Setup browser dual-view splits
        self.workspace_view = WorkspaceViewer(self)
        self.workspace_view.set_zoom(self._zoom)
        work_layout.addWidget(self.workspace_view, 1)

        # Setup decoupled high-fidelity PDF vector exporter
        self.pdf_exporter = PDFExporter(self, self.workspace_view, self.status_message_callback)

        # Bottom real-time progress panel
        self.progress_panel = ProgressPanel(self)
        work_layout.addWidget(self.progress_panel)

        self.stacked_widget.addWidget(workspace)

        # Setup status bars and zoom control sliders
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        
        self.zoom_widget = ZoomWidget(self)
        self.zoom_widget.set_zoom_factor(self._zoom)
        self.zoom_widget.zoom_changed.connect(self._on_slider_zoom_changed)
        self.status.addPermanentWidget(self.zoom_widget)
        
        self.status.showMessage(self.tr("Ready. Open or drag a PDF document to begin."))

    def _build_menu(self) -> None:
        mb = self.menuBar()

        # ── File Menu ──
        m_file = mb.addMenu(self.tr("File"))

        self.a_open = QAction(self.tr("Open PDF..."), self)
        self.a_open.setShortcut(QKeySequence("Ctrl+O"))
        self.a_open.triggered.connect(self._open_pdf_dialog)
        m_file.addAction(self.a_open)

        self.a_close = QAction(self.tr("Close Document"), self)
        self.a_close.setEnabled(False)
        self.a_close.triggered.connect(self._close_document)
        m_file.addAction(self.a_close)

        self.a_export = QAction(self.tr("Export Translated PDF..."), self)
        self.a_export.setShortcut(QKeySequence("Ctrl+S"))
        self.a_export.setEnabled(False)
        self.a_export.triggered.connect(self._export_pdf_dialog)
        m_file.addAction(self.a_export)

        m_file.addSeparator()

        self.a_properties = QAction(self.tr("Document Properties..."), self)
        self.a_properties.setShortcut(QKeySequence("Ctrl+D"))
        self.a_properties.setEnabled(False)
        self.a_properties.triggered.connect(self._show_document_properties)
        m_file.addAction(self.a_properties)
        
        m_file.addSeparator()

        self.m_recent = m_file.addMenu(self.tr("Recent Files"))
        self.m_recent.aboutToShow.connect(self._populate_recent_menu)

        m_file.addSeparator()

        a_quit = QAction(self.tr("Quit"), self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # ── Translation Menu ──
        m_trans = mb.addMenu(self.tr("Translation"))

        self.a_start = QAction(self.tr("Start Translation"), self)
        self.a_start.setShortcut(QKeySequence("Ctrl+Return"))
        self.a_start.setEnabled(False)
        self.a_start.triggered.connect(self._toggle_translation)
        m_trans.addAction(self.a_start)

        self.a_start_range = QAction(self.tr("Translate Specific Pages..."), self)
        self.a_start_range.setShortcut(QKeySequence("Ctrl+Shift+Return"))
        self.a_start_range.setEnabled(False)
        self.a_start_range.triggered.connect(self._toggle_translation_range)
        m_trans.addAction(self.a_start_range)

        m_trans.addSeparator()

        self.a_api_config = QAction(self.tr("API & Model Configuration..."), self)
        self.a_api_config.triggered.connect(self._show_api_configuration)
        m_trans.addAction(self.a_api_config)

        m_lang = m_trans.addMenu(self.tr("Target Language"))
        self._lang_actions: Dict[str, QAction] = {}
        
        # Languages table map
        languages_ui = [
            ("Français", "French"),
            ("Español", "Spanish"),
            ("English", "English"),
            ("Deutsch", "German"),
            ("العربية", "Arabic"),
            ("中文", "Chinese (Simplified)"),
            ("Português", "Portuguese"),
            ("Italiano", "Italian"),
            ("日本語", "Japanese"),
            ("Русский", "Russian"),
        ]
        
        for display, name in languages_ui:
            a = QAction(display, self, checkable=True)
            a.setData(name)
            a.triggered.connect(self._on_lang_selected)
            if name == "French":
                a.setChecked(True)
            m_lang.addAction(a)
            self._lang_actions[name] = a

        # ── View Menu ──
        m_view = mb.addMenu(self.tr("View"))

        a_zoom_in = QAction(self.tr("Zoom In"), self)
        a_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        m_view.addAction(a_zoom_in)

        a_zoom_out = QAction(self.tr("Zoom Out"), self)
        a_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        m_view.addAction(a_zoom_out)

        a_zoom_reset = QAction(self.tr("Zoom 100%"), self)
        a_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        m_view.addAction(a_zoom_reset)

        a_zoom_in.triggered.connect(lambda: self._adjust_zoom(0.1))
        a_zoom_out.triggered.connect(lambda: self._adjust_zoom(-0.1))
        a_zoom_reset.triggered.connect(lambda: self._adjust_zoom(0.0))

        m_view.addSeparator()
        
        self.a_toggle_progress = QAction(self.tr("Show Progress Panel"), self, checkable=True)
        self.a_toggle_progress.setShortcut(QKeySequence("Ctrl+J"))
        self.a_toggle_progress.setChecked(True)
        self.a_toggle_progress.triggered.connect(self._toggle_progress_panel)
        m_view.addAction(self.a_toggle_progress)

        self.a_fullscreen = QAction(self.tr("Full Screen"), self, checkable=True)
        self.a_fullscreen.setShortcut(QKeySequence("F11"))
        self.a_fullscreen.triggered.connect(self.toggle_fullscreen)
        m_view.addAction(self.a_fullscreen)

        m_view.addSeparator()

        self.layout_group = QActionGroup(self)

        self.a_layout_both = QAction(self.tr("Show Dual Split View"), self, checkable=True)
        self.a_layout_both.setShortcut(QKeySequence("Ctrl+3"))
        self.a_layout_both.setChecked(True)
        self.a_layout_both.triggered.connect(self._apply_layout_both)
        self.layout_group.addAction(self.a_layout_both)
        m_view.addAction(self.a_layout_both)

        self.a_layout_pdf = QAction(self.tr("Show Original PDF Only"), self, checkable=True)
        self.a_layout_pdf.setShortcut(QKeySequence("Ctrl+1"))
        self.a_layout_pdf.triggered.connect(self._apply_layout_pdf_only)
        self.layout_group.addAction(self.a_layout_pdf)
        m_view.addAction(self.a_layout_pdf)

        self.a_layout_trans = QAction(self.tr("Show Translation Only"), self, checkable=True)
        self.a_layout_trans.setShortcut(QKeySequence("Ctrl+2"))
        self.a_layout_trans.triggered.connect(self._apply_layout_trans_only)
        self.layout_group.addAction(self.a_layout_trans)
        m_view.addAction(self.a_layout_trans)
        
        # ── Settings Menu ──
        m_settings = mb.addMenu(self.tr("Settings"))

        self.a_trans_settings = QAction(self.tr("Translation Engine..."), self)
        self.a_trans_settings.triggered.connect(self._show_translation_settings)
        m_settings.addAction(self.a_trans_settings)

        self.a_system_settings = QAction(self.tr("System & Cache..."), self)
        self.a_system_settings.triggered.connect(self._show_system_settings)
        m_settings.addAction(self.a_system_settings)

        m_settings.addSeparator()

        m_lang = m_settings.addMenu(self.tr("Application Language"))
        self._app_lang_actions = {}
        
        # Supported interface languages mapping
        languages_list = [
            ("English", "en"),
            ("Français", "fr"),
            ("Español", "es"),
            ("Deutsch", "de"),
        ]
        
        # Load currently saved language to check the correct item on startup
        current_lang = QSettings("RockTranslate", "SystemConfig").value("ui_language", "")
        
        for display, code in languages_list:
            action = QAction(display, self, checkable=True)
            action.setData(code)
            action.triggered.connect(self._on_app_language_changed)
            
            # If no manual preference is set, check "English" as fallback
            if current_lang == code or (not current_lang and code == "en"):
                action.setChecked(True)
                
            m_lang.addAction(action)
            self._app_lang_actions[code] = action

        m_settings.addSeparator()

        self.a_reset_settings = QAction(self.tr("Reset Settings to Default"), self)
        self.a_reset_settings.triggered.connect(self._reset_all_settings)
        m_settings.addAction(self.a_reset_settings)
        
        # ── Help Menu ──
        m_help = mb.addMenu(self.tr("Help"))

        self.a_about = QAction(self.tr("About RockTranslate..."), self)
        self.a_about.triggered.connect(self._show_about_dialog)
        m_help.addAction(self.a_about)

        m_help.addSeparator()

        self.a_website = QAction(self.tr("Official Website"), self)
        self.a_website.triggered.connect(self._open_website)
        m_help.addAction(self.a_website)

        self.a_github = QAction(self.tr("Source Code (GitHub)"), self)
        self.a_github.triggered.connect(self._open_github)
        m_help.addAction(self.a_github)

        self.a_issues = QAction(self.tr("Report an Issue"), self)
        self.a_issues.triggered.connect(self._open_issues)
        m_help.addAction(self.a_issues)


        # ── TOP RIGHT CORNER: Active Model Label Indicator ──
        self.lbl_menu_model = QLabel(self)
        self.lbl_menu_model.setStyleSheet("""
            QLabel {
                color: #2b6cb0;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
                margin-right: 30px;
                background: transparent;
                border: none;
            }
        """)
        mb.setCornerWidget(self.lbl_menu_model, Qt.Corner.TopRightCorner)
        self._update_menu_model_indicator()

    def status_message_callback(self, message: str) -> None:
        """ Thread-safe callback routing module updates to the status bar. """
        self.status.showMessage(message)

    def _update_menu_model_indicator(self) -> None:
        """ Refreshes active model display strings on top action bars. """
        settings = QSettings("RockTranslate", "APIConfig")
        provider = settings.value("provider", "Google Gemini")
        
        fallback_model = DEFAULT_PROVIDERS[provider]["models"][0]
        model = settings.value(f"last_model_{provider}", fallback_model)
        
        short_model = model.split("/")[-1] if "/" in model else model
        self.lbl_menu_model.setText(f" AI MODEL ACTIVE   |   🤖 {provider}: {short_model}")

    def _show_api_configuration(self) -> None:
        """ Triggers setup panels and visual triggers. """
        dialog = APIConfigDialog(self)
        if dialog.exec():
            self.welcome_screen._check_api_keys()
            self._update_menu_model_indicator()
            self.status.showMessage(self.tr("API configuration saved successfully."))

    def _open_pdf_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Open PDF"), "", "PDF (*.pdf)")
        if path:
            self._open_pdf_by_path(path)

    def _open_pdf_by_path(self, path: str) -> None:
        self.status.showMessage(self.tr("Analyzing document and extracting layout..."))
        self._pdf_path = path
        self.a_open.setEnabled(False)

        # Background PDF extraction cycles
        self._ext_worker = ExtractionWorker(path)
        self._ext_worker.status_update.connect(self.status.showMessage)
        self._ext_worker.extraction_progress.connect(self._on_extraction_progress)
        self._ext_worker.finished.connect(self._on_extraction_finished)
        self._ext_worker.error.connect(self._on_extraction_error)
        self._ext_worker.start()

    def _on_extraction_progress(self, current: int, total: int) -> None:
        self.status.showMessage(
            self.tr("Analyzing Document layout: Page {current}/{total}...").format(
                current=current, total=total
            )
        )

    def _on_extraction_finished(self, instrumented_html_path: str, original_texts_map: dict, tid_to_page: dict) -> None:
        self._instrumented_html_path = instrumented_html_path
        self._original_texts = original_texts_map
        self._tid_to_page = tid_to_page
        
        self._translated_pages = {}

         # --- OPTIMIZATION: Initialize progress panel with real document dimensions ---
        total_pages = max(tid_to_page.values()) + 1 if tid_to_page else 1
        total_segments = len(original_texts_map)
        self.progress_panel.initialize_bounds(total_pages, total_segments)

        # Update historical persistent states via our clean manager
        self._add_to_recent_files(self._pdf_path)

        # Display workspace layout
        self.stacked_widget.setCurrentIndex(1)
        self.a_close.setEnabled(True)
        self.a_start.setEnabled(True)
        self.a_start_range.setEnabled(True)
        self.a_properties.setEnabled(True)

        # Load split pane viewports
        pdfjs_absolute_path = os.path.join(DEFAULT_ASSETS_DIR, "pdfjs")
        self.workspace_view.load_document(self._pdf_path, self._instrumented_html_path, pdfjs_absolute_path)
        

        self.status.showMessage(
            self.tr("Document loaded: {filename} ({count} text nodes mapped)").format(
                filename=os.path.basename(self._pdf_path), count=len(original_texts_map)
            )
        )
        self.a_open.setEnabled(True)

    def _on_extraction_error(self, err_msg: str) -> None:
        QMessageBox.critical(self, self.tr("Extraction Error"), f"{self.tr('Could not parse target document:')}\n{err_msg}")
        self._close_document()
        self.a_open.setEnabled(True)

    def _toggle_translation(self) -> None:
        if self._trans_worker and self._trans_worker.isRunning():
            self.status.showMessage(self.tr("Stopping translation process..."))
            self._trans_worker.stop()
            self.a_start.setEnabled(False)
            return
        self._start_translation()

    def _start_translation(self, target_pages: Optional[List[int]] = None) -> None:
        if not self._original_texts:
            QMessageBox.warning(
                self, 
                self.tr("No Text Detected"), 
                self.tr("No translatable text elements found in this document. Please verify OCR layers.")
            )
            return

        api_settings = QSettings("RockTranslate", "APIConfig")
        provider = api_settings.value("provider", "Google Gemini")
        
        config = DEFAULT_PROVIDERS[provider]
        fallback_model = DEFAULT_PROVIDERS[provider]["models"][0]
        active_model = api_settings.value(f"last_model_{provider}", fallback_model)

        llm_model_name: str = active_model
        if config["prefix"] and isinstance(config["prefix"], str) and not llm_model_name.startswith(config["prefix"]):
            llm_model_name = f"{config['prefix']}{llm_model_name}"
        
        raw_keys = api_settings.value("api_keys_by_provider", "{}")
        try:
            keys_dict = json.loads(raw_keys) if isinstance(raw_keys, str) else raw_keys
        except Exception:
            keys_dict = {}
        active_api_key: str = keys_dict.get(provider, "")
        
        use_custom_base = api_settings.value("use_custom_base", False, type=bool)
        active_base_url = api_settings.value("custom_base_url", "") if use_custom_base else None

        if provider != "Ollama (Local)" and not active_api_key:
            QMessageBox.warning(
                self, 
                self.tr("Missing API Key"), 
                self.tr("Please setup your API Key for {provider} first.").format(provider=provider)
            )
            self._show_api_configuration()
            return

        self.a_export.setEnabled(False)

        total_pages: int = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1

        already_translated_ids = set()
        for page_data in self._translated_pages.values():
            already_translated_ids.update(page_data.keys())

         # --- SURGICAL REFACTOR: FILTER UNTRANSLATED BY TARGET RANGE ---
        if target_pages is not None:
            untranslated_texts = {
                k: v for k, v in self._original_texts.items()
                if k not in already_translated_ids and self._tid_to_page.get(k, 0) in target_pages
            }
            
            # Hide the glass overlay for all pages that will NOT be translated
            unselected_pages = [p for p in range(total_pages) if p not in target_pages]
            if unselected_pages:
                self.workspace_view.hide_glass_overlays(unselected_pages)

        else: # normal case 
            untranslated_texts = {
                k: v for k, v in self._original_texts.items()
                if k not in already_translated_ids
            }


        if not untranslated_texts:
            reply = QMessageBox.question(
                self,
                self.tr("Document Translated"),
                self.tr(
                    "All pages are already translated.\n\n"
                    "Do you want to reset historical structures and translate again?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self._translated_pages = {}
                already_translated_ids = set()
                untranslated_texts = self._original_texts.copy()
            else:
                self.status.showMessage(self.tr("Translation already complete."))
                self.a_export.setEnabled(True)
                return

        self.progress_panel.reset(total_pages, len(untranslated_texts), target_pages)
        self.progress_panel.set_segments(len(already_translated_ids))

        # Launch active translation thread
        self._trans_worker = TranslationWorker(
            untranslated_texts,
            llm_model_name,
            active_api_key,
            self._current_lang,
            custom_base_url=active_base_url,
            all_keys=keys_dict 
        )
        self._current_model = llm_model_name
        self._trans_worker.status_update.connect(self.status.showMessage)
        self._trans_worker.batch_progress.connect(self.progress_panel.set_batches)
        self._trans_worker.segment_translated.connect(self._on_segment_translated)
        self._trans_worker.finished.connect(self._on_translation_finished)
        self._trans_worker.error.connect(self._on_translation_error)
        
        self.a_start.setText(self.tr("Stop Translation"))
        if target_pages is not None:
           self.a_start_range.setText(self.tr("Stop Translation"))
        
        first_missing_id = next(iter(untranslated_texts.keys()))
        first_missing_page = self._tid_to_page.get(first_missing_id, 0)
        self._current_translating_page = first_missing_page
        self.progress_panel.set_page(first_missing_page + 1)
        self.workspace_view.prepare_page(first_missing_page)
        
        self._trans_worker.start()

    def _on_segment_translated(self, trans_id: str, translated_text: str) -> None:
        """ Updates visual panes sequentially on thread signals. """
        page_idx: int = self._tid_to_page.get(trans_id, 0)
        
        if page_idx != self._current_translating_page:
            self._current_translating_page = page_idx
            self.workspace_view.prepare_page(page_idx)
            self.progress_panel.set_page(page_idx + 1)

        self.workspace_view.stream_translation(trans_id, translated_text)
        self.progress_panel.increment_segment()

    def _on_translation_finished(self) -> None:
        self.a_start.setText(self.tr("Start Translation"))
        self.a_start_range.setText(self.tr("Translate Specific Pages..."))
        self.a_start.setEnabled(True)
        self.a_start_range.setEnabled(True)
        self.workspace_view.clean_up_all_skeletons()

        if self._trans_worker and not self._trans_worker.is_stopped():
            self.status.showMessage(self.tr("Translation completed successfully."))
            self.a_export.setEnabled(True)
            
            self.progress_panel.local_progress.update_values(
                len(self._original_texts), len(self._original_texts), self.tr("Finished ✓")
            )
            
            # Map memory states
            for p_idx in range(self.progress_panel._total_pages):
                if p_idx not in self._translated_pages:
                    self._translated_pages[p_idx] = {}
                for k, v in self._original_texts.items():
                    if self._tid_to_page.get(k, 0) == p_idx and k not in self._translated_pages[p_idx]:
                        self._translated_pages[p_idx][k] = v
            
            QMessageBox.information(self, self.tr("Success"), self.tr("Document translation succeeded!"))
        else:
            self.status.showMessage(self.tr("Translation process canceled."))
            if self._current_translating_page != -1:
                self.workspace_view.reset_page_to_waiting(self._current_translating_page)



    def _on_translation_error(self, err_msg: str) -> None:
        self.a_start.setText(self.tr("Start Translation"))
        self.a_start_range.setText(self.tr("Translate Specific Pages..."))
        self.a_start.setEnabled(True)
        self.a_start_range.setEnabled(True)

        QMessageBox.critical(self, self.tr("Translation Interrupted"), 
                             f"{self.tr('An error occurred during translation:')}\n{err_msg}")
        
        if self._current_translating_page != -1:
            self.workspace_view.reset_page_to_waiting(self._current_translating_page)

    def _toggle_translation_range(self) -> None:
        """
        Invokes an input dialog requesting specific target page numbers,
        validates the input boundaries, and starts the range translation process.
        """
        if self._trans_worker and self._trans_worker.isRunning():
            self.status.showMessage(self.tr("Stopping translation process..."))
            self._trans_worker.stop()
            self.a_start_range.setEnabled(False)
            return

        total_pages: int = max(self._tid_to_page.values()) + 1 if self._tid_to_page else 1

        # Interactive and clear tutorial text explaining the range operators '-' and ','
        label_text = (
            f"{self.tr('Enter page numbers or ranges to translate (Total Pages:')} {total_pages}):\n\n"
            f"📖 {self.tr('Syntax Guide:')}\n"
            f"  • {self.tr("If you want to translate a single page, enter its number. Example: '4' translates only page 4.")}\n"
            f"  • {self.tr("Use '-' for a sequential range of pages. Example: '2-5' translates pages 2, 3, 4, and 5.")}\n"
            f"  • {self.tr("Use ',' to separate distinct pages or ranges. Example: '1, 3, 5' translates pages 1, 3, and 5.")}\n"
            f"  • {self.tr("Combine both formats. Example: '2-4, 7, 9' translates pages 2, 3, 4, 7, and 9.")}\n\n"
            f"⚠️ {self.tr('Note: Pages out-of-bounds (e.g., page 12 on a 10-page document) will be skipped.')}"
        )

        user_input, ok = QInputDialog.getText(
            self, 
            self.tr("Translate Specific Pages"), 
            label_text
        )

        if not ok or not user_input.strip():
            return

        # Parse user inputs
        target_pages = parse_page_range(user_input, total_pages)

        if not target_pages:
            # Detailed feedback if user entered out-of-bound numbers
            try:
                raw_numbers = [int(s) for s in re.findall(r'\d+', user_input)]
                out_of_bounds = [n for n in raw_numbers if n < 1 or n > total_pages]
                if out_of_bounds:
                    QMessageBox.warning(
                        self,
                        self.tr("Invalid Page Scope"),
                        self.tr(
                            "The entered pages ({pages}) are out of boundaries.\n"
                            "This document only has {total} pages."
                        ).format(pages=", ".join(map(str, out_of_bounds)), total=total_pages)
                    )
                    return
            except Exception:
                pass

            QMessageBox.warning(
                self,
                self.tr("No Valid Pages"),
                self.tr("Please enter a valid page range matching the syntax guide.")
            )
            return

        # Start the range-targeted translation
        self._start_translation(target_pages)


    def _export_pdf_dialog(self) -> None:
        """ Invokes the decoupled headless Chromium vector exporter utility. """
        if self._pdf_path:
            self.pdf_exporter.export_pdf(self._pdf_path)

    def _apply_layout_both(self) -> None:
        self.workspace_view.set_pane_layout("both")
        self.status.showMessage(self.tr("Display: Dual split layout active."))

    def _apply_layout_pdf_only(self) -> None:
        self.workspace_view.set_pane_layout("pdf_only")
        self.status.showMessage(self.tr("Display: Original PDF layout active."))

    def _apply_layout_trans_only(self) -> None:
        self.workspace_view.set_pane_layout("trans_only")
        self.status.showMessage(self.tr("Display: Translated layout active."))

    def _adjust_zoom(self, delta: float) -> None:
        if delta == 0.0:
            self._zoom = 1.0
        else:
            self._zoom = max(0.5, min(2.5, self._zoom + delta))
        self.workspace_view.set_zoom(self._zoom)
        self.zoom_widget.set_zoom_factor(self._zoom)
        self.status.showMessage(self.tr("Zoom set to: {percent}%").format(percent=int(self._zoom * 100)))
    
    def _on_slider_zoom_changed(self, factor: float) -> None:
        self._zoom = factor
        self.workspace_view.set_zoom(factor)
    
    def _toggle_progress_panel(self, visible: bool) -> None:
        self.progress_panel.setVisible(visible)
        state_label: str = self.tr("displayed") if visible else self.tr("hidden")
        self.status.showMessage(self.tr("Display: Progress tracking panel {state}.").format(state=state_label))

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.a_fullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.a_fullscreen.setChecked(True)

    def _on_lang_selected(self) -> None:
        a = self.sender()
        if isinstance(a, QAction):
            self._current_lang = str(a.data())
            for act in self._lang_actions.values():
                act.setChecked(False)
            a.setChecked(True)

    def _populate_recent_menu(self) -> None:
        """ Dynamically builds file historical menu rows. """
        self.m_recent.clear()
        recent_list: List[str] = self.recent_manager.get_recent_files()
        
        if not recent_list:
            empty_action = QAction(self.tr("No recent documents found"), self)
            empty_action.setEnabled(False)
            self.m_recent.addAction(empty_action)
            return
        
        for file_path in recent_list:
            action = QAction(os.path.basename(file_path), self)
            action.setToolTip(file_path)
            # Safe lambda capture index maps
            action.triggered.connect(lambda checked, path=file_path: self._open_pdf_by_path(path))
            self.m_recent.addAction(action)
        
        if recent_list:
            self.m_recent.addSeparator()
            clear_action = QAction(self.tr("Clear History"), self)
            clear_action.triggered.connect(self._clear_recent_files)
            self.m_recent.addAction(clear_action)

    def _clear_recent_files(self) -> None:
        self.recent_manager.clear_history()

    def _add_to_recent_files(self, file_path: str) -> None:
        self.recent_manager.add_file(file_path)

    def _show_document_properties(self) -> None:
        if not self._pdf_path:
            return

        already_translated_ids = set()
        for page_data in self._translated_pages.values():
            already_translated_ids.update(page_data.keys())
        done_segments: int = len(already_translated_ids)
        total_segments: int = len(self._original_texts)
        
        # Standardized English states for our properties translator
        trans_status: str = "Not translated"
        trans_date: str = "Unknown"
        if done_segments >= total_segments and total_segments > 0:
            trans_status = "Fully translated 💎"
            trans_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif done_segments > 0:
            trans_status = "Partial translation in progress"

        trans_stats = {
            "trans_status": trans_status,
            "trans_lang": self._current_lang,
            "trans_model": self._current_model or "None",
            "trans_segments": f"{done_segments} / {total_segments}",
            "trans_scale_avg": "94.4% (Optimized)" if done_segments > 0 else "100.0%",
            "trans_date": trans_date
        }

        # Run file metadata extract cycles
        metadata = get_pdf_metadata(self._pdf_path, trans_stats)

        # Build modal dialog
        dialog = DocumentPropertiesDialog(metadata, self)
        dialog.exec()
    

    def _show_translation_settings(self) -> None:
        """ Opens the translation workflow configuration dialog modal. """
        
        dialog = TranslationWorkflowDialog(self)
        dialog.exec()

    def _show_system_settings(self) -> None:
        """ Opens the system and executable path configuration dialog modal. """
        
        dialog = SystemWorkflowDialog(self)
        dialog.exec()

    def _reset_all_settings(self) -> None:
        """ Resets all translation and system configurations to their defaults after confirmation. """
        reply = QMessageBox.question(
            self,
            self.tr("Reset Settings"),
            self.tr("Are you sure you want to reset all engine and system configurations to their defaults?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            QSettings("RockTranslate", "TranslationConfig").clear()
            QSettings("RockTranslate", "SystemConfig").clear()
            QMessageBox.information(
                self, 
                self.tr("Success"), 
                self.tr("All workflow configurations have been reset successfully.")
            )

    
    def _on_app_language_changed(self) -> None:
        """ Handles application language change and triggers a fast software restart. """
        action = self.sender()
        if not isinstance(action, QAction):
            return
            
        selected_code = str(action.data())
        
        # Uncheck other languages
        for act in self._app_lang_actions.values():
            act.setChecked(False)
        action.setChecked(True)
        
        # Save preference
        system_settings = QSettings("RockTranslate", "SystemConfig")
        system_settings.setValue("ui_language", selected_code)
        
        # Prompt user to restart
        reply = QMessageBox.question(
            self,
            self.tr("Restart Required"),
            self.tr("The language has been updated.\n\nWould you like to restart RockTranslate now to apply the changes?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # ── AUTO-RESTART ENGINE ──
            # Safely close the active document first to clear temporary locks
            self._close_document()
            
            # Close this QApplication instance
            QApplication.quit()
            
            # Instantly launch a new process with identical CLI arguments
            
            subprocess.Popen([sys.executable] + sys.argv)

    def _show_about_dialog(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def _open_website(self) -> None:
        """ Opens the official project landing page in the default system browser. """
        webbrowser.open("https://rocktranslate.org")  # todo Target placeholder

    def _open_github(self) -> None:
        """ Opens the project GitHub repository in the default system browser. """
        webbrowser.open(" https://github.com/PerfectWin7777/RockTranslate")

    def _open_issues(self) -> None:
        """ Opens the project GitHub issues page in the default system browser. """
        webbrowser.open(" https://github.com/PerfectWin7777/RockTranslate/issues")


    def _close_document(self) -> None:
        if self._trans_worker and self._trans_worker.isRunning():
            self._trans_worker.stop()
            try:
                self._trans_worker.status_update.disconnect()
                self._trans_worker.batch_progress.disconnect()
                self._trans_worker.segment_translated.disconnect()
                self._trans_worker.finished.disconnect()
                self._trans_worker.error.disconnect()
            except Exception:
                pass
                
            if not self._trans_worker.wait(300):
                self._trans_worker.terminate()

        self.workspace_view.cleanup_temp_files()
        self.workspace_view.load(QUrl("about:blank"))
        
        self._pdf_path = None
        self._instrumented_html_path = None
        self._original_texts = {}
        self._translated_pages = {}
        self.progress_panel.clear()
        
        self.a_close.setEnabled(False)
        self.a_start.setEnabled(False)
        self.a_export.setEnabled(False)
        self.a_start_range.setEnabled(False)
        self.a_properties.setEnabled(False) 
        
        self.a_layout_both.setChecked(True)
        self.stacked_widget.setCurrentIndex(0)
        self.status.showMessage(self.tr("Document closed."))

    def closeEvent(self, event: Any) -> None:
        self._close_document()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RockTranslate")
    app.setFont(QFont("Segoe UI", 10))
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())