"""
RockTranslate — Translation Engine and Workflow Settings Dialog
Path: ui_pyqt/widget/translation_settings_dialog.py

This module implements the configuration panel for fine-tuning the LLM translation
parameters (temperature, context size, batch size) and physical layout spacing thresholds
using global default constants.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QDoubleSpinBox, QSpinBox,
    QPushButton, QDialogButtonBox, QLabel, QWidget
)
from PyQt6.QtCore import Qt, QSettings

# Import default fallback values directly from the centralized constants module
try:
    from core.constants import THRESHOLD_PX, SLIDING_CONTEXT_MAX_SIZE, MAX_SEGMENTS_PER_BATCH, MAX_RETRIES
except ImportError:
    from src.core.constants import THRESHOLD_PX, SLIDING_CONTEXT_MAX_SIZE, MAX_SEGMENTS_PER_BATCH, MAX_RETRIES


class TranslationWorkflowDialog(QDialog):
    """
    Modular configuration dialog for fine-tuning the translation engine
    parameters, including temperature, sliding context depth, and layout thresholds.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the dialog window, loading stylesheets and persisted settings.

        Args:
            parent: Optional parent QWidget container.
        """
        super().__init__(parent)
        self.setWindowTitle(self.tr("Translation Engine Settings"))
        self.resize(500, 280)
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
            QDoubleSpinBox, QSpinBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e0;
                border-radius: 4px;
                padding: 6px;
                padding-right: 20px; /* Leave space for the smaller buttons */
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2d3748;
            }
            QDoubleSpinBox:focus, QSpinBox:focus {
                border-color: #4f8ef7;
            }
            
            /* Compact, minimalist spinbox arrow buttons styling */
            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px; /* Narrower width for a sleek look */
                border-left: 1px solid #cbd5e0;
                border-bottom: 1px solid #cbd5e0;
                background: #f7fafc;
                border-top-right-radius: 4px;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {
                background: #edf2f7;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px; /* Narrower width for a sleek look */
                border-left: 1px solid #cbd5e0;
                background: #f7fafc;
                border-bottom-right-radius: 4px;
            }
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background: #edf2f7;
            }
        """)

        self.settings = QSettings("RockTranslate", "TranslationConfig")
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        """ Renders the workflow configuration input form. """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        form = QFormLayout()
        form.setSpacing(12)

        # 1. Model Temperature (0.0 to 2.0)
        self.spin_temp = QDoubleSpinBox(self)
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setToolTip(self.tr("Controls the randomness of the translation output (lower is more deterministic)."))
        form.addRow(self.tr("Model Temperature"), self.spin_temp)

        # 2. Sliding Context Depth
        self.spin_context_size = QSpinBox(self)
        self.spin_context_size.setRange(1, 30)
        self.spin_context_size.setToolTip(self.tr("Number of previous paragraphs kept in memory for contextual consistency."))
        form.addRow(self.tr("Sliding Context Depth"), self.spin_context_size)

        # 3. Maximum Segments per Batch
        self.spin_batch_size = QSpinBox(self)
        self.spin_batch_size.setRange(5, 200)
        self.spin_batch_size.setToolTip(self.tr("Maximum number of text elements processed in a single API concurrent request."))
        form.addRow(self.tr("Max Segments Per Batch"), self.spin_batch_size)

        # 4. Column Cut Spacer Width Threshold (THRESHOLD_PX)
        self.spin_threshold_px = QDoubleSpinBox(self)
        self.spin_threshold_px.setRange(2.0, 50.0)
        self.spin_threshold_px.setSingleStep(0.5)
        self.spin_threshold_px.setToolTip(self.tr("Horizontal distance (pixels) beyond which adjacent text nodes are split into columns."))
        form.addRow(self.tr("Table Column Split Threshold (px)"), self.spin_threshold_px)

        # 5. Maximum Connection Retries (MAX_RETRIES)
        self.spin_retries = QSpinBox(self)
        self.spin_retries.setRange(1, 10)
        self.spin_retries.setToolTip(self.tr("Maximum number of network reconnection attempts before marking a batch request as failed."))
        form.addRow(self.tr("Max Connection Retries"), self.spin_retries)

        layout.addLayout(form)

        # Bottom warning description
        info_lbl = QLabel(
            self.tr(
                "These settings directly impact translation visual grouping "
                "and API context costs. Tweak with care."
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
        """ Loads workflow values, falling back directly to centralized constants module. """
        # Fetching defaults directly from our central constants file
        temperature = self.settings.value("temperature", 1.0, type=float)
        context_size = self.settings.value("sliding_context_size", SLIDING_CONTEXT_MAX_SIZE, type=int)
        batch_size = self.settings.value("max_segments_per_batch", MAX_SEGMENTS_PER_BATCH, type=int)
        threshold_px = self.settings.value("threshold_px", THRESHOLD_PX, type=float)
        max_retries = self.settings.value("max_retries", MAX_RETRIES, type=int)
        
        self.spin_temp.setValue(temperature)
        self.spin_context_size.setValue(context_size)
        self.spin_batch_size.setValue(batch_size)
        self.spin_threshold_px.setValue(threshold_px)
        self.spin_retries.setValue(max_retries)
        

    def _on_save_settings(self) -> None:
        """ Saves selected values to persistent storage. """
        self.settings.setValue("temperature", self.spin_temp.value())
        self.settings.setValue("sliding_context_size", self.spin_context_size.value())
        self.settings.setValue("max_segments_per_batch", self.spin_batch_size.value())
        self.settings.setValue("threshold_px", self.spin_threshold_px.value())
        self.settings.setValue("max_retries", self.spin_retries.value())
        self.accept()