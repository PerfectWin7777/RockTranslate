"""
progress_panel.py — Barre de progression + stats temps réel
Chemin : D:/Projets/RockTranslate/src/ui/progress_panel.py
"""

import time
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer


class LabeledProgressBar(QWidget):
    """
    Sous-widget réutilisable regroupant une ligne de labels (Gauche/Droite)
    et une barre de progression stylisée en-dessous.
    """
    def __init__(self, title_template: str, bar_color: str, bar_height: int = 6):
        super().__init__()
        self.title_template = title_template

        # Layout vertical pour empiler l'en-tête de texte et la barre
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Ligne de labels (Horizontale)
        label_row = QHBoxLayout()
        self.lbl_left = QLabel(self.title_template.format(done=0, total=0), self)
        self.lbl_right = QLabel("", self)

        # Application du style visuel
        self.lbl_left.setStyleSheet("font-size: 11px;  font-weight: 500;")
        self.lbl_right.setStyleSheet("font-size: 11px; ")
        self.lbl_right.setAlignment(Qt.AlignmentFlag.AlignRight)

        label_row.addWidget(self.lbl_left)
        label_row.addStretch()
        label_row.addWidget(self.lbl_right)
        layout.addLayout(label_row)

        # Barre de progression personnalisée
        self.bar = QProgressBar(self)
        self.bar.setFixedHeight(bar_height)
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        
        # Style moderne (Flat design)
        radius = bar_height // 2
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background: #1e2130;
                border-radius: {radius}px;
            }}
            QProgressBar::chunk {{
                background: {bar_color};
                border-radius: {radius}px;
            }}
        """)
        layout.addWidget(self.bar)

    def update_values(self, done: int, total: int, right_text: str = ""):
        """Met à jour les valeurs de progression et les textes des étiquettes."""
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.lbl_left.setText(self.title_template.format(done=done, total=total))
        if right_text:
            self.lbl_right.setText(right_text)


class ProgressPanel(QWidget):
    """
    Panneau principal contenant la progression globale (Document - Bleue)
    et la progression locale (Page active - Verte).
    """
    def __init__(self):
        super().__init__()
        # On augmente légèrement la hauteur à 90px pour donner de l'espace à nos deux widgets labellisés
        self.setFixedHeight(90)
        self._total     = 0
        self._done      = 0
        self._batches_done  = 0
        self._batches_total = 0
        self._start_time    = None

        self._build_ui()

        # Timer pour l'actualisation de l'ETA (temps restant)
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_eta)
        self._timer.setInterval(1000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # 1. Barre Globale (Bleu #4f8ef7) pour le document entier
        self.global_progress = LabeledProgressBar(
            title_template="Progression du document : {done} / {total} pages traduites",
            bar_color="#4f8ef7",
            bar_height=6
        )
        layout.addWidget(self.global_progress)

        # 2. Barre Locale (Verte #48bb78) pour la page en cours de traduction
        self.local_progress = LabeledProgressBar(
            title_template="Analyse de la page active : lot {done} / {total} traités",
            bar_color="#48bb78",
            bar_height=5
        )
        layout.addWidget(self.local_progress)

    def reset(self, total: int):
        self._total          = total
        self._done           = 0
        self._batches_done   = 0
        self._batches_total  = 0
        self._start_time     = time.time()

        self.global_progress.update_values(0, total, "Calcul en cours...")
        self.local_progress.update_values(0, 1, "Vitesse : --")
        self._timer.start()

    def increment(self):
        self._done += 1
        pct = int((self._done / max(self._total, 1)) * 100)
        self.global_progress.update_values(self._done, self._total)
        
        if self._done >= self._total:
            self._timer.stop()
            self.global_progress.lbl_right.setText("Terminé ✓")
            self.local_progress.update_values(self._batches_total, self._batches_total, "Vitesse : --")

    def set_batches(self, done: int, total: int):
        self._batches_done  = done
        self._batches_total = total
        
        # Calcul de la vitesse estimée de traitement
        elapsed = time.time() - (self._start_time or time.time())
        lines_done = (self._done * 30) + (done * 4)  # estimation arbitraire du nombre de lignes
        speed = lines_done / max(elapsed, 0.1)
        
        self.local_progress.update_values(done, total, f"Vitesse : {speed:.1f} l/sec")

    def _update_eta(self):
        if not self._start_time or self._done == 0:
            return
        elapsed = time.time() - self._start_time
        rate    = self._done / elapsed
        remaining = (self._total - self._done) / max(rate, 0.001)

        mins = int(remaining // 60)
        secs = int(remaining % 60)
        
        if mins > 0:
            eta_str = f"~{mins}m {secs:02d}s restantes"
        else:
            eta_str = f"~{secs}s restantes"

        pct = int((self._done / max(self._total, 1)) * 100)
        self.global_progress.lbl_right.setText(f"{eta_str} | {pct}%")