# src/ui_pyqt/widget/zoom_widget.py

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal

class ZoomWidget(QWidget):
    """
    Widget autonome de contrôle du zoom bilatéral et synchrone.
    """
    zoom_changed = pyqtSignal(float)  # Émet le facteur de zoom (ex: 1.0 pour 100%)

    def __init__(self, parent=None):
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

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(6)

        # Bouton décrémentation (-)
        self.btn_minus = QPushButton("-", self)
        self.btn_minus.setFixedHeight(20)
        self.btn_minus.setFixedWidth(20)
        self.btn_minus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minus.clicked.connect(self._decrement)

        # Slider réglé par défaut à 100%
        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setRange(50, 250)
        self.slider.setValue(100)
        self.slider.setFixedWidth(150)
        self.slider.valueChanged.connect(self._on_slider_changed)

        # Bouton incrémentation (+)
        self.btn_plus = QPushButton("+", self)
        self.btn_plus.setFixedHeight(20)
        self.btn_plus.setFixedWidth(20)
        self.btn_plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_plus.clicked.connect(self._increment)

        # Affichage texte de la valeur
        self.lbl_percent = QLabel("100%", self)
        self.lbl_percent.setFixedWidth(35)
        self.lbl_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        
        layout.addStretch()
        layout.addWidget(self.btn_minus)
        layout.addWidget(self.slider)
        layout.addWidget(self.btn_plus)
        layout.addWidget(self.lbl_percent)

    def _on_slider_changed(self, value):
        self.lbl_percent.setText(f"{value}%")
        self.zoom_changed.emit(value / 100.0)

    def _decrement(self):
        self.slider.setValue(max(50, self.slider.value() - 10))

    def _increment(self):
        self.slider.setValue(min(250, self.slider.value() + 10))

    def set_zoom_factor(self, factor: float):
        """Met à jour le slider sans déclencher de boucle de signaux."""
        self.slider.blockSignals(True)
        val = int(factor * 100)
        self.slider.setValue(val)
        self.lbl_percent.setText(f"{val}%")
        self.slider.blockSignals(False)