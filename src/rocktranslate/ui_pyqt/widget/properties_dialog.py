"""
RockTranslate — Comprehensive Document Properties and Metadata Dialog
Path: src/rocktranslate/ui_pyqt/widget/properties_dialog.py

This module renders the multi-tab metadata properties interface:
1. General: Physical file specs, sizes, structural flags, and page dimensions.
2. Description: Standard PDF metadata (Author, Subject, Producer, Dates).
3. RockTranslate: Custom translation metrics, alignment scaling, and active AI model.

All UI text rows are localized via self.tr(), and raw backend values are 
dynamically mapped using localized string lookup tables.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

from typing import Dict, Any, Optional
from PyQt6.QtWidgets import QDialog, QTabWidget, QWidget, QFormLayout, QLabel, QVBoxLayout, QDialogButtonBox
from PyQt6.QtCore import Qt


class DocumentPropertiesDialog(QDialog):
    """
    Standard properties modal detailing standard PDF file metadata,
    layout dimensions, and RockTranslate historical translation statistics.
    """

    def __init__(self, metadata: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        """
        Initializes the dialog window, loading geometry bounds and stylesheets.

        Args:
            metadata: Properties dictionary returned by get_pdf_metadata().
            parent: Optional parent QWidget.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Document Properties"))
        self.resize(550, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #f7fafc;
            }
            QTabWidget::pane {
                border: 1px solid #e2e8f0;
                background: #ffffff;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #f7fafc;
                color: #718096;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #2d3748;
                border: 1px solid #e2e8f0;
                border-bottom-color: #ffffff;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2d3748;
            }
            QLabel[class="title"] {
                font-weight: bold;
                color: #4a5568;
            }
        """)
        self.metadata: Dict[str, Any] = metadata
        self._build_ui()

    def _build_ui(self) -> None:
        """ Sets up dialog layout grids, custom tabs, and OK close handles. """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        tab_widget = QTabWidget(self)
        
        # ── TAB 1: General Specs ──
        tab_general = QWidget()
        layout_gen = QFormLayout(tab_general)
        layout_gen.setContentsMargins(15, 15, 15, 15)
        layout_gen.setSpacing(10)
        
        layout_gen.addRow(self._create_label(self.tr("File:"), True), self._create_label(self.metadata["file_path"]))
        layout_gen.addRow(self._create_label(self.tr("File Size:"), True), self._create_label(self.metadata["file_size"]))
        layout_gen.addRow(self._create_label(self.tr("Pages:"), True), self._create_label(str(self.metadata["pages_count"])))
        layout_gen.addRow(self._create_label(self.tr("PDF Version:"), True), self._create_label(self.metadata["pdf_version"]))
        layout_gen.addRow(
            self._create_label(self.tr("Fast Web View (Linearized):"), True), 
            self._create_label(self._localize_value(self.metadata["linearized"]))
        )
        layout_gen.addRow(
            self._create_label(self.tr("Tagged PDF:"), True), 
            self._create_label(self._localize_value(self.metadata["tagged"]))
        )
        layout_gen.addRow(self._create_label(self.tr("Page Size:"), True), self._create_label(self.metadata["page_size"]))
        
        tab_widget.addTab(tab_general, self.tr("General"))
        
        # ── TAB 2: Metadata Descriptions ──
        tab_meta = QWidget()
        layout_meta = QFormLayout(tab_meta)
        layout_meta.setContentsMargins(15, 15, 15, 15)
        layout_meta.setSpacing(10)
        
        layout_meta.addRow(self._create_label(self.tr("Title:"), True), self._create_label(self.metadata["title"]))
        layout_meta.addRow(self._create_label(self.tr("Subject:"), True), self._create_label(self.metadata["subject"]))
        layout_meta.addRow(self._create_label(self.tr("Author:"), True), self._create_label(self.metadata["author"]))
        layout_meta.addRow(self._create_label(self.tr("Creator:"), True), self._create_label(self.metadata["creator"]))
        layout_meta.addRow(self._create_label(self.tr("Producer:"), True), self._create_label(self.metadata["producer"]))
        layout_meta.addRow(self._create_label(self.tr("Keywords:"), True), self._create_label(self._localize_value(self.metadata["keywords"])))
        layout_meta.addRow(self._create_label(self.tr("Created on:"), True), self._create_label(self._localize_value(self.metadata["created_date"])))
        layout_meta.addRow(self._create_label(self.tr("Modified on:"), True), self._create_label(self._localize_value(self.metadata["mod_date"])))
        
        tab_widget.addTab(tab_meta, self.tr("Description"))
        
        # ── TAB 3: RockTranslate Statistics ──
        tab_custom = QWidget()
        layout_cust = QFormLayout(tab_custom)
        layout_cust.setContentsMargins(15, 15, 15, 15)
        layout_cust.setSpacing(10)
        
        layout_cust.addRow(
            self._create_label(self.tr("Translation Status:"), True), 
            self._create_label(self._localize_value(self.metadata.get("trans_status", "Not translated")))
        )
        layout_cust.addRow(
            self._create_label(self.tr("Target Language:"), True), 
            self._create_label(self._localize_value(self.metadata.get("trans_lang", "Unknown")))
        )
        layout_cust.addRow(
            self._create_label(self.tr("AI Model Used:"), True), 
            self._create_label(self._localize_value(self.metadata.get("trans_model", "None")))
        )
        layout_cust.addRow(
            self._create_label(self.tr("Semantic Blocks Translated:"), True), 
            self._create_label(self.metadata.get("trans_segments", "0 / 0"))
        )
        layout_cust.addRow(
            self._create_label(self.tr("Average Layout Scale (scaleX):"), True), 
            self._create_label(self.metadata.get("trans_scale_avg", "100.0%"))
        )
        layout_cust.addRow(
            self._create_label(self.tr("Translation Date:"), True), 
            self._create_label(self._localize_value(self.metadata.get("trans_date", "Unknown")))
        )
        
        tab_widget.addTab(tab_custom, self.tr("RockTranslate 💎"))
        
        layout.addWidget(tab_widget)
        
        # Standard OK Dialog confirmation buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
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
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _localize_value(self, value: Any) -> str:
        """
        Translates standardized backend states into localized UI language sequences.
        Ensures compatibility with both old French stats and new English standard keys.

        Args:
            value: The raw value retrieved from metadata structures.

        Returns:
            str: Translated and human-readable string values.
        """
        if not isinstance(value, str):
            return str(value)

        translation_map = {
            # Standardized English States
            "Unknown": self.tr("Unknown"),
            "None": self.tr("None"),
            "Yes": self.tr("Yes"),
            "No": self.tr("No"),
            "Not translated": self.tr("Not translated"),
            "Fully translated 💎": self.tr("Fully translated 💎"),
            "Partial translation in progress": self.tr("Partial translation in progress"),
            
            # Transitional French States (backward compatibility)
            "Non traduit": self.tr("Not translated"),
            "Inconnue": self.tr("Unknown"),
            "Aucun": self.tr("None"),
            "Traduit d'origine 💎": self.tr("Fully translated 💎"),
            "Traduction partielle en cours": self.tr("Partial translation in progress")
        }
        return translation_map.get(value, value)

    def _create_label(self, text: str, is_title: bool = False) -> QLabel:
        """
        Generates standard formatted text row elements.

        Args:
            text: Contents of the label.
            is_title: Flag styling this label as a row category title header.

        Returns:
            QLabel: Generated and configured UI label node.
        """
        lbl = QLabel(text, self)
        if is_title:
            lbl.setProperty("class", "title")
            lbl.setFixedWidth(180)
        else:
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
        return lbl