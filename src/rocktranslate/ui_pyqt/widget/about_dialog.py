

"""
RockTranslate — Contextual and Dynamic about Dialog
Path: src/rocktranslate/ui_pyqt/widget/about_dialog.py

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os 
from PyQt6.QtWidgets import (
    QVBoxLayout,QLabel, QHBoxLayout, QPushButton, QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import  QPixmap, QIcon

# Modular, decoupled imports representing the clean open-source architecture
try:
    from src.rocktranslate.core.constants import DEFAULT_ASSETS_DIR
except ImportError:
    from src.rocktranslate.core.constants import  DEFAULT_ASSETS_DIR
    

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("About RockTranslate"))
        self.resize(600, 300)
        main_layout = QVBoxLayout(self)
        
        logo_label = QLabel()
        logo_path = os.path.join(DEFAULT_ASSETS_DIR, "RockTranslate_icon.png")
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            logo_label.setPixmap(
                pixmap.scaled(
                    110, 80, 
                    Qt.AspectRatioMode.KeepAspectRatio, 
                    Qt.TransformationMode.SmoothTransformation
                )
            )
        
        title = QLabel("<h2>RockTranslate v1.0.0</h2>")
        subtitle = QLabel(
            f"<p><b>{self.tr('Scientific PDF Translation Engine')}</b><br/>"
            f"{self.tr('Preserving Layout. Translating Knowledge.')}</p>"
        )
        head_layout = QHBoxLayout()
        title_layout =  QVBoxLayout()
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)

        head_layout.addWidget(logo_label)
        head_layout.addLayout(title_layout)
        head_layout.addStretch()
        
        main_layout.addLayout(head_layout)
        

        features = QLabel(
            f"<p>"
            f"{self.tr('RockTranslate is a desktop application designed for translating scientific, technical, and academic PDF documents while preserving their original structure, formatting, figures, tables, and visual layout.')}"
            f"</p>"

            f"<p>"
            f"{self.tr('Built with a local-first architecture, RockTranslate prioritizes performance, reliability, and user control. The application combines advanced document analysis, intelligent translation workflows, and high-fidelity PDF reconstruction to deliver professional-quality results.')}"
            f"</p>"

            f"<p>"
            f"• {self.tr('Layout-Preserved PDF Translation')}<br/>"
            f"• {self.tr('Scientific and Technical Document Support')}<br/>"
            f"• {self.tr('High-Fidelity PDF Reconstruction')}<br/>"
            f"• {self.tr('Fast Desktop Performance')}<br/>"
            f"• {self.tr('Lightweight and Responsive User Experience')}<br/>"
            f"• {self.tr('Privacy-Conscious Workflow')}<br/>"
            f"• {self.tr('Open-Source and Community-Driven')}"
            f"</p>"
        )
        features.setWordWrap(True)
        # features.setMaximumWidth(400)

        footer = QLabel(
           f"<p>"
            f"<b>{self.tr('License')}:</b> MIT License<br/>"
            f"<b>{self.tr('Authors')}:</b> RockTranslate Contributors"
            f"</p>"

            f"<p style='color:gray;'>"
            f"© 2026 RockTranslate Contributors"
            f"</p>"
        )
        main_layout.addWidget(features)
        main_layout.addSpacing(20)
        main_layout.addWidget(footer)
        
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)

        main_layout.addSpacing(10)
        main_layout.addWidget(btn)