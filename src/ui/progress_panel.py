"""
progress_panel.py — Barre de progression + stats temps réel
Chemin : D:/Projets/RockTranslate/src/ui/progress_panel.py
"""

import time
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer


class ProgressPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(54)
        self._total     = 0
        self._done      = 0
        self._batches_done  = 0
        self._batches_total = 0
        self._start_time    = None

        self._build_ui()

        # Timer pour mettre à jour le temps restant
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_eta)
        self._timer.setInterval(1000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(2)

        # Ligne stats
        stats_row = QHBoxLayout()

        self.lbl_done    = QLabel("0 / 0 paragraphes")
        self.lbl_batches = QLabel("0 / 0 batches")
        self.lbl_eta     = QLabel("")
        self.lbl_pct     = QLabel("0 %")
        self.lbl_pct.setAlignment(Qt.AlignmentFlag.AlignRight)

        for lbl in [self.lbl_done, self.lbl_batches, self.lbl_eta]:
            lbl.setStyleSheet("font-size: 11px; color: gray;")

        self.lbl_pct.setStyleSheet("font-size: 11px; font-weight: bold;")

        stats_row.addWidget(self.lbl_done)
        stats_row.addWidget(QLabel("·", styleSheet="color:gray;font-size:11px;"))
        stats_row.addWidget(self.lbl_batches)
        stats_row.addWidget(QLabel("·", styleSheet="color:gray;font-size:11px;"))
        stats_row.addWidget(self.lbl_eta)
        stats_row.addStretch()
        stats_row.addWidget(self.lbl_pct)
        layout.addLayout(stats_row)

        # Barre de progression
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        self.bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background: #2a2d3e;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: #4f8ef7;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.bar)

    def reset(self, total: int):
        self._total          = total
        self._done           = 0
        self._batches_done   = 0
        self._batches_total  = 0
        self._start_time     = time.time()

        self.bar.setMaximum(total)
        self.bar.setValue(0)
        self.lbl_done.setText(f"0 / {total} pages")
        self.lbl_batches.setText("batches : -")
        self.lbl_eta.setText("calcul...")
        self.lbl_pct.setText("0 %")
        self._timer.start()

    def increment(self):
        self._done += 1
        self.bar.setValue(self._done)
        pct = int(self._done / max(self._total, 1) * 100)
        self.lbl_done.setText(f"{self._done} / {self._total} pages")
        self.lbl_pct.setText(f"{pct} %")

        if self._done >= self._total:
            self._timer.stop()
            self.lbl_eta.setText("Terminé ✓")

    def set_batches(self, done: int, total: int):
        self._batches_done  = done
        self._batches_total = total
        self.lbl_batches.setText(f"batch {done}/{total}")

    def _update_eta(self):
        if not self._start_time or self._done == 0:
            return
        elapsed = time.time() - self._start_time
        rate    = self._done / elapsed          # paras/sec
        remaining = (self._total - self._done) / max(rate, 0.001)

        mins = int(remaining // 60)
        secs = int(remaining % 60)
        if mins > 0:
            self.lbl_eta.setText(f"~{mins}m {secs:02d}s restantes")
        else:
            self.lbl_eta.setText(f"~{secs}s restantes")