# table_detector.py
# Détection heuristique robuste de tableaux scientifiques / académiques
# Compatible PyMuPDF (fitz)
#
# Détecte :
# - tableaux avec bordures
# - tableaux sans bordures
# - tableaux scientifiques
# - tableaux alignés par colonnes
# - tableaux avec seulement spacing
# - tableaux mixtes texte/chiffres
#
# Approche :
# 1. Analyse vectorielle
# 2. Analyse spatiale des mots
# 3. Détection alignements colonnes
# 4. Régularité des lignes
# 5. Densité documentaire
# 6. Fragmentation linguistique
#
# Auteur : adapté pour moteur documentaire avancé

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple

import fitz


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block_no: int
    line_no: int
    word_no: int

    @property
    def width(self):
        return self.x1 - self.x0

    @property
    def height(self):
        return self.y1 - self.y0

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2


@dataclass
class TextLine:
    y: float
    words: List[Word]

    @property
    def min_x(self):
        return min(w.x0 for w in self.words)

    @property
    def max_x(self):
        return max(w.x1 for w in self.words)

    @property
    def width(self):
        return self.max_x - self.min_x

    @property
    def text(self):
        return " ".join(w.text for w in self.words)

    @property
    def avg_word_len(self):
        if not self.words:
            return 0
        return statistics.mean(len(w.text) for w in self.words)


# ============================================================
# TABLE DETECTOR
# ============================================================

class TableDetector:

    def __init__(
        self,
        min_words_per_line: int = 2,
        x_cluster_tolerance: float = 12,
        line_merge_tolerance: float = 4,
    ):
        self.min_words_per_line = min_words_per_line
        self.x_cluster_tolerance = x_cluster_tolerance
        self.line_merge_tolerance = line_merge_tolerance

    # ========================================================
    # PUBLIC API
    # ========================================================

    def detect_tables(self, page: fitz.Page) -> Dict:

        words = self._extract_words(page)

        if not words:
            return {
                "has_table": False,
                "score": 0,
                "features": {}
            }

        lines = self._build_lines(words)

        features = {
            "vector_lines": self._detect_vector_lines(page),
            "aligned_columns": self._detect_aligned_columns(lines),
            "regular_rows": self._detect_regular_rows(lines),
            "high_density": self._detect_density(lines, page),
            "fragmented_text": self._detect_fragmentation(lines),
            "numeric_pattern": self._detect_numeric_patterns(lines),
            "grid_structure": self._detect_grid_structure(lines),
        }

        score = self._compute_score(features)

        return {
            "has_table": score >= 7,
            "score": score,
            "features": features
        }

    # ========================================================
    # WORD EXTRACTION
    # ========================================================

    def _extract_words(self, page: fitz.Page) -> List[Word]:

        raw_words = page.get_text("words")

        words = []

        for w in raw_words:
            try:
                words.append(
                    Word(
                        x0=w[0],
                        y0=w[1],
                        x1=w[2],
                        y1=w[3],
                        text=w[4],
                        block_no=w[5],
                        line_no=w[6],
                        word_no=w[7]
                    )
                )
            except Exception:
                continue

        return words

    # ========================================================
    # LINE RECONSTRUCTION
    # ========================================================

    def _build_lines(self, words: List[Word]) -> List[TextLine]:

        lines_map = defaultdict(list)

        for w in words:
            assigned = False

            for y_key in list(lines_map.keys()):

                if abs(y_key - w.cy) <= self.line_merge_tolerance:
                    lines_map[y_key].append(w)
                    assigned = True
                    break

            if not assigned:
                lines_map[w.cy].append(w)

        lines = []

        for y, line_words in lines_map.items():

            line_words.sort(key=lambda x: x.x0)

            if len(line_words) >= self.min_words_per_line:
                lines.append(TextLine(y=y, words=line_words))

        lines.sort(key=lambda l: l.y)

        return lines

    # ========================================================
    # FEATURE 1 : VECTOR LINES
    # ========================================================

    def _detect_vector_lines(self, page: fitz.Page) -> bool:

        try:
            drawings = page.get_drawings()

            horizontal = 0
            vertical = 0

            for d in drawings:

                rect = d.get("rect")

                if not rect:
                    continue

                x0, y0, x1, y1 = rect

                w = x1 - x0
                h = y1 - y0

                # horizontal line
                if w > 80 and h < 3:
                    horizontal += 1

                # vertical line
                elif h > 40 and w < 3:
                    vertical += 1

            return (
                horizontal >= 2
                or
                (horizontal >= 1 and vertical >= 2)
            )

        except Exception:
            return False

    # ========================================================
    # FEATURE 2 : COLUMN ALIGNMENT
    # ========================================================

    def _detect_aligned_columns(self, lines: List[TextLine]) -> bool:

        x_positions = []

        for line in lines:

            if len(line.words) < 2:
                continue

            for w in line.words:
                x_positions.append(round(w.x0 / self.x_cluster_tolerance))

        if not x_positions:
            return False

        freq = defaultdict(int)

        for x in x_positions:
            freq[x] += 1

        strong_columns = [
            k for k, v in freq.items()
            if v >= 3
        ]

        return len(strong_columns) >= 2

    # ========================================================
    # FEATURE 3 : REGULAR ROWS
    # ========================================================

    def _detect_regular_rows(self, lines: List[TextLine]) -> bool:

        if len(lines) < 4:
            return False

        spacings = []

        for i in range(1, len(lines)):
            dy = lines[i].y - lines[i - 1].y

            if 2 < dy < 80:
                spacings.append(dy)

        if len(spacings) < 3:
            return False

        try:
            variance = statistics.pvariance(spacings)

            return variance < 20

        except Exception:
            return False

    # ========================================================
    # FEATURE 4 : DENSITY
    # ========================================================

    def _detect_density(
        self,
        lines: List[TextLine],
        page: fitz.Page
    ) -> bool:

        if not lines:
            return False

        total_words = sum(len(l.words) for l in lines)

        page_area = page.rect.width * page.rect.height

        density = total_words / max(page_area, 1)

        return density > 0.00045

    # ========================================================
    # FEATURE 5 : FRAGMENTED TEXT
    # ========================================================

    def _detect_fragmentation(self, lines: List[TextLine]) -> bool:

        fragmented = 0

        for line in lines:

            text = line.text.strip()

            if not text:
                continue

            avg_len = line.avg_word_len

            # tableaux = beaucoup de petits tokens
            if avg_len < 5:
                fragmented += 1

        if not lines:
            return False

        ratio = fragmented / len(lines)

        return ratio > 0.45

    # ========================================================
    # FEATURE 6 : NUMERIC STRUCTURE
    # ========================================================

    def _detect_numeric_patterns(self, lines: List[TextLine]) -> bool:

        numeric_lines = 0

        for line in lines:

            numeric_words = 0

            for w in line.words:

                txt = w.text.strip()

                if not txt:
                    continue

                digit_ratio = sum(c.isdigit() for c in txt) / len(txt)

                if digit_ratio > 0.4:
                    numeric_words += 1

            if numeric_words >= 2:
                numeric_lines += 1

        return numeric_lines >= 3

    # ========================================================
    # FEATURE 7 : GRID STRUCTURE
    # ========================================================

    def _detect_grid_structure(self, lines: List[TextLine]) -> bool:

        consistent = 0

        for line in lines:

            if len(line.words) < 3:
                continue

            gaps = []

            for i in range(1, len(line.words)):

                gap = line.words[i].x0 - line.words[i - 1].x1

                if gap > 0:
                    gaps.append(gap)

            if len(gaps) < 2:
                continue

            try:
                var = statistics.pvariance(gaps)

                if var < 100:
                    consistent += 1

            except Exception:
                pass

        return consistent >= 3

    # ========================================================
    # SCORE ENGINE
    # ========================================================

    def _compute_score(self, f: Dict) -> int:

        score = 0

        if f["vector_lines"]:
            score += 3

        if f["aligned_columns"]:
            score += 4

        if f["regular_rows"]:
            score += 3

        if f["high_density"]:
            score += 2

        if f["fragmented_text"]:
            score += 2

        if f["numeric_pattern"]:
            score += 2

        if f["grid_structure"]:
            score += 3

        return score


# ============================================================
# SIMPLE API
# ============================================================

_detector = TableDetector()


def page_has_table(page: fitz.Page) -> bool:
    """
    Détection robuste de tableaux scientifiques.
    """
    result = _detector.detect_tables(page)
    return result["has_table"]


def analyze_page_tables(page: fitz.Page) -> Dict:
    """
    Retourne analyse complète + score heuristique.
    """
    return _detector.detect_tables(page)