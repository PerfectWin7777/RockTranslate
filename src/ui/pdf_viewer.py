"""
pdf_viewer.py — Affichage PDF Natif via QtPdf
Chemin : D:/Projets/RockTranslate/src/ui/pdf_viewer.py
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QFrame
)
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtPdfWidgets import QPdfView
from PyQt6.QtCore import Qt, pyqtSignal, QPointF 

class PDFViewer(QWidget):
    """
    Composant d'affichage PDF haute performance.
    Utilise le moteur natif Chromium (via QtPdf) pour permettre 
    la sélection de texte et un rendu vectoriel parfait.
    """

    page_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.total_pages = 0
        # Le Document (Le moteur de données)
        self._doc = QPdfDocument(self)
        
        # La Vue (Le widget d'affichage)
        self.view = QPdfView(self)
        self.view.setDocument(self._doc)
        
        # Configuration pour le confort (Scroll continu)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Barre de navigation (Optionnelle mais utile) ---
        self.nav_bar = QFrame()
        self.nav_bar.setFixedHeight(35)
        self.nav_bar.setStyleSheet("background-color: #f8f9fa; border-bottom: 1px solid #dee2e6;")
        
        nav_layout = QHBoxLayout(self.nav_bar)
        nav_layout.setContentsMargins(10, 0, 10, 0)

        self.lbl_title = QLabel("Aucun document")
        self.lbl_title.setStyleSheet("font-size: 11px; font-weight: bold; color: #495057;")

        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedSize(28, 24)
        
        self.lbl_page = QLabel("0 / 0")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page.setFixedWidth(60)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedSize(28, 24)

        nav_layout.addWidget(self.lbl_title)
        nav_layout.addStretch()
        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.lbl_page)
        nav_layout.addWidget(self.btn_next)
        
        layout.addWidget(self.nav_bar)
        
        # --- La Vue PDF ---
        layout.addWidget(self.view)

    def _connect_signals(self):
        # Navigation boutons
        self.btn_prev.clicked.connect(lambda: self.goto_page(self.get_current_page_idx() - 1))
        self.btn_next.clicked.connect(lambda: self.goto_page(self.get_current_page_idx() + 1))
        
        # Signal quand l'utilisateur scrolle vers une autre page
        self.view.pageNavigator().currentPageChanged.connect(self._on_page_navigated)

    # --- API Publique (On garde les mêmes méthodes pour MainWindow) ---

    def load_pdf(self, path: str, zoom: float = 1.0):
        """Charge le fichier PDF dans le moteur natif."""
        status = self._doc.load(path)
        if status == QPdfDocument.Status.Ready:
            self.lbl_title.setText(os.path.basename(path))
            self._update_page_info()
            # On force le mode ajusté à la largeur au chargement
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)

            self.total_pages = self._doc.pageCount()
        else:
            print(f"Erreur de chargement PDF : {status}")

    def set_zoom(self, zoom_factor: float):
        """
        Désactive le mode automatique et applique un zoom précis.
        zoom_factor : 1.0 = 100%
        """
        self.view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.view.setZoomFactor(zoom_factor)
        self.lbl_title.setText(f"Zoom: {int(zoom_factor*100)}%")

    def goto_page(self, page_index: int):
        """Navigue vers une page spécifique (0-based)."""
        if 0 <= page_index < self._doc.pageCount():
            self.view.pageNavigator().jump(page_index, QPointF(), 0)

    def get_current_page_idx(self) -> int:
        """Retourne l'index de la page actuelle (0-based)."""
        if self.view.pageNavigator():
            return self.view.pageNavigator().currentPage()
        return 0

    def _on_page_navigated(self, page_index: int):
        self._update_page_info()
        self.page_changed.emit(page_index)

    def _update_page_info(self):
        total = self._doc.pageCount()
        current = self.get_current_page_idx() + 1
        self.lbl_page.setText(f"{current} / {total}")
        self.btn_prev.setEnabled(current > 1)
        self.btn_next.setEnabled(current < total)

    def clear(self):
        """Ferme le document actuel."""
        self._doc.close()
        self.lbl_page.setText("0 / 0")
        self.lbl_title.setText("Aucun document")