import sys
import os
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsTextItem, QGraphicsPixmapItem, QLabel
)
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPixmap, QPainter
from loguru import logger
# Essaye de charger votre image de fond existante, sinon crée un fond blanc factice
BACKGROUND_PATH = "output_files/background_page.png"


# ── 1. WIDGET SQUELETTE AVEC EFFET SHIMMER ENTIÈREMENT NATIF ──

class SkeletonItem(QGraphicsRectItem):
    """
    Un rectangle squelette personnalisé.
    Utilise un timer interne et un dégradé linéaire mouvant pour simuler
    l'effet de balayage brillant (shimmer) sans aucune surcharge CPU.
    """
    def __init__(self, rect: QRectF, parent=None):
        super().__init__(rect, parent)
        # self.setPen(Qt.PenStyle.NoPen)
        self.phase = 0.0
        
        # Petit Timer pour animer le balayage
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(30)  # ~30 images par seconde
        
        self.update_brush()

    def tick(self):
        # On décale la phase du dégradé à chaque cycle
        self.phase = (self.phase + 0.04) % 1.0
        self.update_brush()

    def update_brush(self):
        # Création du dégradé linéaire horizontal
        r = self.rect()
        grad = QLinearGradient(r.left(), 0, r.right(), 0)
        
        p1 = max(0.0, self.phase - 0.15)
        p2 = self.phase
        p3 = min(1.0, self.phase + 0.15)
        
        # Couleurs de balayage (Gris doux et blanc brillant au milieu)
        grad.setColorAt(0.0, QColor("#e2e8f0"))
        if p1 > 0.0:
            grad.setColorAt(p1, QColor("#e2e8f0"))
        grad.setColorAt(p2, QColor("#f1f5f9"))
        if p3 < 1.0:
            grad.setColorAt(p3, QColor("#e2e8f0"))
        grad.setColorAt(1.0, QColor("#e2e8f0"))
        
        self.setBrush(QBrush(grad))


# ── 2. WIDGET TEXTE TRADUIT AVEC SÉLECTION NATIVE SANS MARGES ──

class TranslatedTextItem(QGraphicsTextItem):
    """
    Un conteneur de texte traduit qui supporte le gras, l'italique et la couleur.
    Il autorise la sélection à la souris et supprime toutes les marges internes
    par défaut pour garantir un calage parfait sur les coordonnées d'origine.
    """
    def __init__(self, html_text: str, font_size: float, parent=None):
        super().__init__(parent)
        self.setHtml(html_text)
        
        # Rendre le texte sélectionnable et copiable de manière native
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        
        # SUPPRESSION CRUCIALE DES MARGES INTERNES DE QT
        # Sans cette ligne, Qt ajoute un padding de 4px autour de chaque texte
        self.document().setDocumentMargin(0)
        
        # Configuration de la police globale
        font = self.font()
        font.setFamily("Times New Roman")
        font.setPointSizeF(font_size)
        self.setFont(font)


# ── 3. FENÊTRE DE TEST PRINCIPALE ──

class TestPreviewWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockTranslate — Prototype Scene Graphique (QGraphicsView)")
        self.resize(1200, 800)
        
        self.simulated_step = 0
        self._build_ui()
        self._load_background_and_skeletons()

    def _build_ui(self):
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── VOLET GAUCHE : PANNEAU DE CONTRÔLE ──
        left_panel = QWidget(self)
        left_panel.setFixedWidth(280)
        left_panel.setStyleSheet("background-color: #1e2130; border-right: 1px solid #2d3142;")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(20, 20, 20, 20)
        left_layout.setSpacing(15)

        title = QLabel("Simulation Temps Réel", self)
        title.setStyleSheet("color: white; font-size: 16px; font-weight: bold; border: none;")
        left_layout.addWidget(title)

        desc = QLabel(
            "Ce prototype remplace Chromium par QGraphicsView.\n\n"
            "1. Les squelettes grises vibrent de manière fluide.\n"
            "2. Cliquez sur le bouton ci-dessous pour simuler la réception unitaire "
            "des réponses du LLM.\n"
            "3. Le texte traduit s'affiche instantanément et reste sélectionnable.",
            self
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a0aec0; font-size: 11px; line-height: 1.4; border: none;")
        left_layout.addWidget(desc)

        self.btn_next = QPushButton("▶  Simuler Ligne Suivante", self)
        self.btn_next.setStyleSheet("""
            QPushButton {
                background-color: #48bb78;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #38a169; }
        """)
        self.btn_next.clicked.connect(self._simulate_next_translation)
        left_layout.addWidget(self.btn_next)

        left_layout.addStretch()
        layout.addWidget(left_panel)

        # ── VOLET DROIT : LA SCÈNE GRAPHIQUE (QGRAPHICSVIEW) ──
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setStyleSheet("background-color: #2b2e3c; border: none;")
        
        # Options de lissage graphique pour un texte propre
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        
        layout.addWidget(self.view, 1)

    def _load_background_and_skeletons(self):
        """Initialise l'image de fond et dessine les squelettes de test."""
        # 1. Image de fond
        if os.path.exists(BACKGROUND_PATH):
            pixmap = QPixmap(BACKGROUND_PATH)
        else:
            # Création d'une page blanche factice de taille A4 (595x842pt) si le fichier est absent
            logger.warning(f"Fond d'origine absent à '{BACKGROUND_PATH}'. Génération d'une page blanche.")
            pixmap = QPixmap(595, 842)
            pixmap.fill(Qt.GlobalColor.white)

        self.bg_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.bg_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))

        # 2. Données géométriques simulées d'une page (Lignes physiques)
        self.test_lines = [
            {
                "left": 50, "top": 120, "width": 480, "height": 22, "size": 16.0,
                "text": "<b>Application</b> of Analytical Hierarchy Process in evaluation"
            },
            {
                "left": 50, "top": 150, "width": 450, "height": 22, "size": 16.0,
                "text": "of neotectonic variability on drainage basin systems..."
            },
            {
                "left": 50, "top": 210, "width": 80, "height": 14, "size": 11.0,
                "text": "<b>Résumé</b>"
            },
            {
                "left": 50, "top": 240, "width": 490, "height": 12, "size": 9.0,
                "text": "La géologie et la tectonique complexes de la côte sud-ouest du Cameroun"
            },
            {
                "left": 50, "top": 258, "width": 470, "height": 12, "size": 9.0,
                "text": "sont responsables des paysages actuels de la région d'Edea."
            },
            {
                "left": 50, "top": 276, "width": 490, "height": 12, "size": 9.0,
                "text": "L'étude montre également une <span style='color: #0080ad;'>activité néotectonique</span> active."
            }
        ]

        # Dessiner un squelette animé pour chaque ligne
        self.skeleton_items = {}
        for idx, line in enumerate(self.test_lines):
            rect = QRectF(line["left"], line["top"], line["width"], line["height"])
            skeleton = SkeletonItem(rect)
            self.scene.addItem(skeleton)
            self.skeleton_items[idx] = skeleton

    def _simulate_next_translation(self):
        """Simule la réception unitaire d'une traduction du LLM."""
        if self.simulated_step >= len(self.test_lines):
            self.status_bar = self.statusBar().showMessage("Toutes les lignes sont traduites !")
            return

        idx = self.simulated_step
        line_data = self.test_lines[idx]

        # 1. Supprime le squelette de cette ligne
        skeleton = self.skeleton_items.get(idx)
        if skeleton:
            self.scene.removeItem(skeleton)
            del self.skeleton_items[idx]

        # 2. Ajoute le texte enrichi sélectionnable à la place géométrique exacte
        html_formatted_text = line_data["text"]
        text_item = TranslatedTextItem(html_formatted_text, line_data["size"])
        text_item.setPos(line_data["left"], line_data["top"])
        
        # On définit la largeur maximale de saisie pour s'assurer que le texte s'aligne bien
        text_item.setTextWidth(line_data["width"])
        
        self.scene.addItem(text_item)

        self.statusBar().showMessage(f"Ligne {idx + 1} traduite et injectée.")
        self.simulated_step += 1


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TestPreviewWindow()
    win.show()
    sys.exit(app.exec())