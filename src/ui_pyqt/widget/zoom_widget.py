"""
RockTranslate — Autonomous Synchronous Zoom Control Widget
Path: ui_pyqt/widget/zoom_widget.py

This module implements the dual-pane Zoom control widget, featuring 
interactive plus/minus incrementation buttons, a standard range slider,
and tooltips prepared for internationalization (i18n).

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

from typing import Optional
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal


class ZoomWidget(QWidget):
    """
    Independent widget providing interactive zoom factor adjustments
    to both synchronous workspace rendering panes.
    """
    # Signal emitted when the user scales the document, passing the zoom multiplier (e.g., 1.25 for 125%)
    zoom_changed = pyqtSignal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the Zoom widget and applies stylesheet rules.

        Args:
            parent: Optional parent QWidget container.
        """
        super().__init__(parent)
        self.setStyleSheet("""
            ZoomWidget {
                background: transparent;
            }
            QLabel {
                color: #3e444d;
                font-size: 11px;
                font-family: 'Segoe UI', sans-serif;
            }
            QSlider::groove:horizontal {
                border: 1px solid #4a5568;
                height: 2px;
                background: #2d3748;
                border-radius: 1px;
            }
            QSlider::handle:horizontal {
                background: #4f8ef7;
                border: none;
                width: 10px;
                margin-top: -3px;
                margin-bottom: -3px;
                border-radius: 5px;
            }
            QPushButton {
                background: transparent;
                border: #4f8ef7;
                color: #313840;
                font-size: 15px;
                font-weight: bold;
                width: 16px;
            }
            QPushButton:hover {
                background: #4f8ef7;
                color: #f2f5f7;
            }
        """)
        self._build_ui()

    def _build_ui(self) -> None:
        """
        Builds the widget structure, configuring layout spacing, slider limits,
        and localized tooltips.
        """
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(6)

        # Decrement button (-)
        self.btn_minus = QPushButton("-", self)
        self.btn_minus.setFixedHeight(20)
        self.btn_minus.setFixedWidth(20)
        self.btn_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minus.setToolTip(self.tr("Zoom Out"))
        self.btn_minus.clicked.connect(self._decrement)

        # Main percentage slider (Range: 50% to 250%, Default: 100%)
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(50, 250)
        self.slider.setValue(100)
        self.slider.setFixedWidth(150)
        self.slider.setToolTip(self.tr("Adjust zoom level"))
        self.slider.valueChanged.connect(self._on_slider_changed)

        # Increment button (+)
        self.btn_plus = QPushButton("+", self)
        self.btn_plus.setFixedHeight(20)
        self.btn_plus.setFixedWidth(20)
        self.btn_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_plus.setToolTip(self.tr("Zoom In"))
        self.btn_plus.clicked.connect(self._increment)

        # Output text reading the active percentage (e.g., '100%')
        self.lbl_percent = QLabel("100%", self)
        self.lbl_percent.setFixedWidth(35)
        self.lbl_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        layout.addStretch()
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.slider)
        layout.addWidget(self.btn_plus)
        layout.addWidget(self.lbl_percent)

    def _on_slider_changed(self, value: int) -> None:
        """
        Slot triggered when the range slider value is adjusted.

        Args:
            value: Integer percentage value (e.g., 120).
        """
        self.lbl_percent.setText(f"{value}%")
        self.zoom_changed.emit(value / 100.0)

    def _decrement(self) -> None:
        """ Decrements the zoom slider by a step of 10%. """
        self.slider.setValue(max(50, self.slider.value() - 10))

    def _increment(self) -> None:
        """ Increments the zoom slider by a step of 10%. """
        self.slider.setValue(min(250, self.slider.value() + 10))

    def set_zoom_factor(self, factor: float) -> None:
        """
        Programmatically updates the zoom factor slider without emitting loop feedback signals.

        Args:
            factor: Percentage scale multiplier (e.g., 1.50 for 150%).
        """
        self.slider.blockSignals(True)
        percentage_value = int(factor * 100)
        self.slider.setValue(percentage_value)
        self.lbl_percent.setText(f"{percentage_value}%")
        self.slider.blockSignals(False)
        # self.zoom_changed.emit(factor)