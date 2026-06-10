"""
progress_panel.py — Barre de progression + stats temps réel
src/ui_pyqt/widget/progress_panel.py
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
        self._total_pages     = 1
        self._done_pages      = 0
        self._total_segments  = 0
        self._done_segments   = 0
        self._batches_done    = 0
        self._batches_total   = 0
        self._start_time      = None

        self._build_ui()

        # Timer pour l'actualisation de l'ETA (temps restant)
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_eta)
        self._timer.setInterval(1000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # 1. Barre Globale (Bleu) dédiée aux Pages du document
        self.global_progress = LabeledProgressBar(
            title_template="Progression du document : {done} / {total} pages traduites",
            bar_color="#4f8ef7",
            bar_height=6
        )
        layout.addWidget(self.global_progress)

        # 2. Barre Locale (Verte) dédiée aux Segments et Lots
        self.local_progress = LabeledProgressBar(
            title_template="Progression locale : {done} / {total} segments traduits",
            bar_color="#48bb78",
            bar_height=5
        )
        layout.addWidget(self.local_progress)

    def reset(self, total_pages: int, total_segments: int):
        self._total_pages     = total_pages
        self._done_pages      = 0
        self._total_segments  = total_segments
        self._done_segments   = 0
        self._batches_done    = 0
        self._batches_total   = 0
        self._start_time      = time.time()

        self.global_progress.update_values(0, total_pages, "Calcul en cours...")
        self.local_progress.update_values(0, total_segments, "Vitesse : --")
        self._timer.start()

    def set_page(self, page_num: int):
        """Met à jour l'avancement de la page active sur la barre globale."""
        self._done_pages = page_num
        self.global_progress.update_values(self._done_pages, self._total_pages)

    def increment_segment(self):
        """Incrémente un segment traduit sur la barre locale."""
        self._done_segments += 1
        
        batch_info = f"Lot {self._batches_done}/{self._batches_total}" if self._batches_total else ""
        self.local_progress.update_values(self._done_segments, self._total_segments, batch_info)
        
        if self._done_segments >= self._total_segments:
            self._timer.stop()
            self.global_progress.lbl_right.setText("Terminé ✓")
            self.global_progress.update_values(self._total_pages, self._total_pages)

    def set_batches(self, done_batches: int, total_batches: int):
        """Met à jour l'indicateur de lot et la vitesse estimée."""
        self._batches_done  = done_batches
        self._batches_total = total_batches
        
        elapsed = time.time() - (self._start_time or time.time())
        speed = self._done_segments / max(elapsed, 0.1)
        
        batch_info = f"Lot {done_batches}/{total_batches}"
        self.local_progress.update_values(self._done_segments, self._total_segments, f"{batch_info} | {speed:.1f} seg/sec")

    def _update_eta(self):
        if not self._start_time or self._done_segments == 0:
            return
        elapsed = time.time() - self._start_time
        rate    = self._done_segments / elapsed
        remaining = (self._total_segments - self._done_segments) / max(rate, 0.001)

        mins = int(remaining // 60)
        secs = int(remaining % 60)
        
        eta_str = f"~{mins}m {secs:02d}s" if mins > 0 else f"~{secs}s"
        pct = int((self._done_segments / max(self._total_segments, 1)) * 100)
        self.global_progress.lbl_right.setText(f"{eta_str} restantes | {pct}%")