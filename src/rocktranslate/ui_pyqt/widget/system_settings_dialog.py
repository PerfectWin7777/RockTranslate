"""
RockTranslate — System and Cache Configuration Dialog
Path: src/rocktranslate/ui_pyqt/widget/system_settings_dialog.py

This module implements the system configuration panel, allowing users to control
automatic cache clearing and manually override paths for pdf2htmlEX and PDF.js.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, 
    QLineEdit, QCheckBox, QPushButton, QDialogButtonBox, QFileDialog, QWidget
)
from PyQt6.QtCore import Qt, QSettings


class SystemWorkflowDialog(QDialog):
    """
    Modular system configuration dialog managing local cache lifecycles and manual
    overrides for third-party executables (pdf2htmlEX, PDF.js).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the dialog window, loading stylesheets and persisted paths.

        Args:
            parent: Optional parent QWidget container.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("System & Cache Settings"))
        self.resize(600, 260)
        self.setStyleSheet("""
            QDialog {
                background-color: #f7fafc;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #4a5568;
                font-weight: bold;
            }
            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                padding: 6px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2d3748;
            }
            QLineEdit:focus {
                border-color: #4f8ef7;
            }
            QCheckBox {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #4a5568;
            }
            QPushButton#BrowseBtn {
                background-color: #edf2f7;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                color: #4a5568;
                padding: 6px 12px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton#BrowseBtn:hover {
                background-color: #e2e8f0;
            }
        """)

        self.settings = QSettings("RockTranslate", "SystemConfig")
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        """ Renders the system path and cache configuration form. """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        form = QFormLayout()
        form.setSpacing(12)

        # 1. Clear Cache on exit (Checkbox)
        self.chk_clear_cache = QCheckBox(self.tr("Automatically clear temporary workspace files on exit"), self)
        self.chk_clear_cache.setToolTip(self.tr("If checked, generated HTML workspace files will be deleted when closing documents."))
        form.addRow(self.tr("Cache Lifecycle"), self.chk_clear_cache)

        # 2. pdf2htmlEX Custom Executable Path
        self.edit_pdf2html = QLineEdit(self)
        self.edit_pdf2html.setPlaceholderText(self.tr("Auto-detected by default"))
        self.btn_browse_pdf2html = QPushButton(self.tr("Browse..."), self)
        self.btn_browse_pdf2html.setObjectName("BrowseBtn")
        self.btn_browse_pdf2html.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_pdf2html.clicked.connect(self._browse_pdf2html)

        lay_pdf2html = QHBoxLayout()
        lay_pdf2html.addWidget(self.edit_pdf2html, 1)
        lay_pdf2html.addWidget(self.btn_browse_pdf2html)
        form.addRow(self.tr("pdf2htmlEX Binary Override"), lay_pdf2html)

        # 3. PDF.js Custom Folder Path
        self.edit_pdfjs = QLineEdit(self)
        self.edit_pdfjs.setPlaceholderText(self.tr("Auto-detected by default"))
        self.btn_browse_pdfjs = QPushButton(self.tr("Browse..."), self)
        self.btn_browse_pdfjs.setObjectName("BrowseBtn")
        self.btn_browse_pdfjs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_browse_pdfjs.clicked.connect(self._browse_pdfjs)

        lay_pdfjs = QHBoxLayout()
        lay_pdfjs.addWidget(self.edit_pdfjs, 1)
        lay_pdfjs.addWidget(self.btn_browse_pdfjs)
        form.addRow(self.tr("PDF.js Folder Override"), lay_pdfjs)

        layout.addLayout(form)

        # Bottom informational label
        info_lbl = QLabel(
            self.tr(
                "Leave the executable paths empty to allow RockTranslate "
                "to automatically use default pre-compiled binaries."
            ),
            self
        )
        info_lbl.setWordWrap(True)
        info_lbl.setStyleSheet("color: #718096; font-size: 14px; font-weight: normal; margin-top: 5px;")
        layout.addWidget(info_lbl)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #edf2f7;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                color: #2d3748;
                padding: 6px 16px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f8ef7;
                color: white;
                border-color: #4f8ef7;
            }
        """)
        buttons.accepted.connect(self._on_save_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_settings(self) -> None:
        """ Loads stored paths and checkbox states from system registry. """
        # Fetch system-level configuration defaults directly
        clear_cache = self.settings.value("clear_cache_on_exit", True, type=bool)
        pdf2htmlex_path = self.settings.value("pdf2htmlex_path_override", "", type=str)
        pdfjs_path = self.settings.value("pdfjs_path_override", "", type=str)

        self.chk_clear_cache.setChecked(clear_cache)
        self.edit_pdf2html.setText(pdf2htmlex_path)
        self.edit_pdfjs.setText(pdfjs_path)

    def _browse_pdf2html(self) -> None:
        """ Opens a file dialog to browse for the pdf2htmlEX binary file. """
        file_filter = "Executables (*.exe)" if os.name == "nt" else "All Files (*)"
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Select pdf2htmlEX Executable"), "", file_filter)
        if path:
            self.edit_pdf2html.setText(os.path.normpath(path))

    def _browse_pdfjs(self) -> None:
        """ Opens a directory dialog to browse for the PDF.js web distribution folder. """
        path = QFileDialog.getExistingDirectory(self, self.tr("Select PDF.js Folder"), "")
        if path:
            self.edit_pdfjs.setText(os.path.normpath(path))

    def _on_save_settings(self) -> None:
        """ Saves selected paths to persistent storage. """
        self.settings.setValue("clear_cache_on_exit", self.chk_clear_cache.isChecked())
        self.settings.setValue("pdf2htmlex_path_override", self.edit_pdf2html.text().strip())
        self.settings.setValue("pdfjs_path_override", self.edit_pdfjs.text().strip())
        self.accept()