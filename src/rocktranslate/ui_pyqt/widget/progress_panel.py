"""
RockTranslate — Real-time Progress Tracking and ETA Estimation Panel
Path: src/rocktranslate/ui_pyqt/widget/progress_panel.py

This module implements the dual-progress tracking system:
1. Global Document Progress (tracking pages translated, styled in Blue).
2. Local Batch Progress (tracking individual segments and execution speed, styled in Green).

It dynamically estimates Remaining Time (ETA) based on moving translation averages
and features complete internationalization (i18n) support.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import time
from typing import Optional
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar
from PyQt6.QtCore import Qt, QTimer


class LabeledProgressBar(QWidget):
    """
    A reusable composite widget pairing a stylized flat QProgressBar 
    with a dual-aligned text label row (Left/Right alignment).
    """

    def __init__(
        self, 
        title_template: str, 
        bar_color: str, 
        bar_height: int = 6, 
        parent: Optional[QWidget] = None
    ) -> None:
        """
        Initializes the labeled progress bar.

        Args:
            title_template: String format containing placeholders {done} and {total}.
            bar_color: Hex style background color of the progress bar chunk.
            bar_height: Physical pixel height of the slider.
            parent: Parent QWidget.
        """
        super().__init__(parent)
        self.title_template: str = title_template

        # Vertical layout to stack text alignment headers above the progress bar
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Dynamic labels layout row
        label_row = QHBoxLayout()
        self.lbl_left = QLabel(self.title_template.format(done=0, total=0), self)
        self.lbl_right = QLabel("", self)

        # Apply standardized font aesthetics
        self.lbl_left.setStyleSheet("font-size: 11px; font-weight: 500;")
        self.lbl_right.setStyleSheet("font-size: 11px;")
        self.lbl_right.setAlignment(Qt.AlignmentFlag.AlignRight)

        label_row.addWidget(self.lbl_left)
        label_row.addStretch()
        label_row.addWidget(self.lbl_right)
        layout.addLayout(label_row)

        # Flat stylized QProgressBar
        self.bar = QProgressBar(self)
        self.bar.setFixedHeight(bar_height)
        self.bar.setTextVisible(False)
        self.bar.setValue(0)
        
        # Round handles to give it a modern flat design aspect ratio
        radius: int = bar_height // 2
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

    def update_values(self, done: int, total: int, right_text: str = "") -> None:
        """
        Updates progress bounds and text states.

        Args:
            done: Current progress value.
            total: Maximum target value.
            right_text: Custom contextual metadata (ETA, speed, or status).
        """
        self.bar.setMaximum(max(total, 1))
        self.bar.setValue(done)
        self.lbl_left.setText(self.title_template.format(done=done, total=total))
        if right_text:
            self.lbl_right.setText(right_text)


class ProgressPanel(QWidget):
    """
    Main bottom control panel tracking global document page advances 
    and fast local LLM batch segmentation streams.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """
        Initializes the panel containers, layout styles, and ETA timers.

        Args:
            parent: Parent QWidget.
        """
        super().__init__(parent)
        self.setObjectName("ProgressPanel")
        self.setStyleSheet("""
            #ProgressPanel {
                background-color: #14151f;
                border-top: 1px solid #2d313f;
            }
        """)
        self.setFixedHeight(90)
        
        # Internal state tracking variables
        self._total_pages: int = 1
        self._done_pages: int = 0
        self._total_segments: int = 0
        self._done_segments: int = 0
        self._batches_done: int = 0
        self._batches_total: int = 0
        self._start_time: Optional[float] = None

        self._build_ui()

        # Recurrent timer calculating exact execution averages every second
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_eta)
        self._timer.setInterval(1000)

    def _build_ui(self) -> None:
        """ Instantiates and configures the tracking components. """
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        # 1. Global Document Progress (Blue)
        self.global_progress = LabeledProgressBar(
            title_template=self.tr("Document progress: {done} / {total} pages translated"),
            bar_color="#4f8ef7",
            bar_height=6,
            parent=self
        )
        layout.addWidget(self.global_progress)

        # 2. Local Segment Progress (Green)
        self.local_progress = LabeledProgressBar(
            title_template=self.tr("Local progress: {done} / {total} segments translated"),
            bar_color="#48bb78",
            bar_height=5,
            parent=self
        )
        layout.addWidget(self.local_progress)

    def reset(self, total_pages: int, total_segments: int) -> None:
        """
        Prepares the visual bars and starts calculations for a new translation process.

        Args:
            total_pages: Total page count inside the active document.
            total_segments: Number of segment nodes queued for LLM translation.
        """
        self._total_pages = total_pages
        self._done_pages = 0
        self._total_segments = total_segments
        self._done_segments = 0
        self._batches_done = 0
        self._batches_total = 0
        self._start_time = time.time()

        self.global_progress.update_values(0, total_pages, self.tr("Calculating..."))
        self.local_progress.update_values(0, total_segments, self.tr("Speed: --"))
        self._timer.start()
    
    def clear(self) -> None:
        """ Instantly resets progress bounds and resets labels. """
        self._timer.stop()
        self._total_pages = 1
        self._done_pages = 0
        self._total_segments = 0
        self._done_segments = 0
        self._batches_done = 0
        self._batches_total = 0
        self._start_time = None

        self.global_progress.update_values(0, 1, "")
        self.local_progress.update_values(0, 1, "")
        
    def set_page(self, page_num: int) -> None:
        """
        Updates active global page metrics.

        Args:
            page_num: Active index of the page currently processed.
        """
        self._done_pages = page_num
        self.global_progress.update_values(self._done_pages, self._total_pages)
    
    def set_segments(self, done_segments: int) -> None:
        """
        Sets absolute segment completion, preserving existing layouts on resume operations.

        Args:
            done_segments: Absolute count of successfully translated nodes.
        """
        self._done_segments = done_segments
        batch_info: str = (
            self.tr("Batch {done}/{total}").format(done=self._batches_done, total=self._batches_total)
            if self._batches_total else ""
        )
        self.local_progress.update_values(self._done_segments, self._total_segments, batch_info)

    def increment_segment(self) -> None:
        """ Increments active completion count and forces immediate ETA estimation updates. """
        self._done_segments += 1
        
        batch_info: str = (
            self.tr("Batch {done}/{total}").format(done=self._batches_done, total=self._batches_total)
            if self._batches_total else ""
        )
        self.local_progress.update_values(self._done_segments, self._total_segments, batch_info)
        
        if self._done_segments >= self._total_segments:
            self._timer.stop()
            self.global_progress.lbl_right.setText(self.tr("Finished ✓"))
            self.global_progress.update_values(self._total_pages, self._total_pages)
        else:
            self._update_eta()

    def set_batches(self, done_batches: int, total_batches: int) -> None:
        """
        Updates batch counts and recalculates physical processing speeds.

        Args:
            done_batches: Count of completed network request cycles.
            total_batches: Total batches mapped inside the chunking pipeline.
        """
        self._batches_done = done_batches
        self._batches_total = total_batches
        
        elapsed: float = time.time() - (self._start_time or time.time())
        speed: float = self._done_segments / max(elapsed, 0.1)
        
        batch_label: str = self.tr("Batch {done}/{total}").format(done=done_batches, total=total_batches)
        speed_label: str = self.tr("{speed:.1f} seg/sec").format(speed=speed)
        
        self.local_progress.update_values(
            self._done_segments, 
            self._total_segments, 
            f"{batch_label} | {speed_label}"
        )

    def _update_eta(self) -> None:
        """ Computes execution velocity rules to output remaining completion time. """
        if not self._start_time or self._done_segments == 0:
            return
            
        elapsed: float = time.time() - self._start_time
        rate: float = self._done_segments / elapsed
        remaining: float = (self._total_segments - self._done_segments) / max(rate, 0.001)

        mins: int = int(remaining // 60)
        secs: int = int(remaining % 60)
        
        # Format duration dynamically
        duration_label: str = (
            self.tr("~{mins}m {secs:02d}s").format(mins=mins, secs=secs) 
            if mins > 0 else 
            self.tr("~{secs}s").format(secs=secs)
        )
        
        pct: int = int((self._done_segments / max(self._total_segments, 1)) * 100)
        
        self.global_progress.lbl_right.setText(
            self.tr("{duration} remaining | {percent}%").format(duration=duration_label, percent=pct)
        )