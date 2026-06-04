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
# 7. Signature multi-gouttières (Alignement multicomptes)
# 8. Signature booktabs (Lignes de démarcation horizontales larges)

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
            "multi_gutter_grid": self._detect_multi_gutter_grid(lines), # Indice 2
            "booktabs_rules": self._detect_booktabs_rules(page, lines), # Indice 3
        }

        score = self._compute_score(features)

        # Seuil ajusté à 12 à la suite de l'ajout des deux nouvelles signatures majeures
        has_table = score >= 12
        
        # --- FILTRE SÉMANTIQUE DE SÉCURITÉ CONSOLIDÉ ---
        # Un vrai tableau doit posséder au moins un des indicateurs structurels ou sémantiques forts
        if has_table:
            strong_signals = [
                features["numeric_pattern"],
                features["fragmented_text"],
                features["multi_gutter_grid"],
                features["booktabs_rules"]
            ]
            if not any(strong_signals):
                has_table = False

        return {
            "has_table": has_table,
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
            rot_matrix = page.rotation_matrix # On récupère la matrice de la page
            horizontal = 0
            vertical = 0

            for d in drawings:

                rect = d.get("rect")

                if not rect:
                    continue

                rotated_rect = fitz.Rect(rect) * rot_matrix
                w = rotated_rect.x1 - rotated_rect.x0
                h = rotated_rect.y1 - rotated_rect.y0

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
    # INDICE 2 : ALIGNEMENT MULTICOMPTES (MULTI-GUTTER)
    # ========================================================

    def _detect_multi_gutter_grid(self, lines: List[TextLine]) -> bool:
        """
        Détecte si au moins 3 lignes consécutives présentent des vides (gouttières)
        alignés verticalement sur au moins 2 colonnes (ce qui dessine un tableau à 3 colonnes).
        """
        if len(lines) < 3:
            return False

        # Balayage par fenêtre glissante de 3 lignes
        for idx in range(len(lines) - 2):
            window_lines = lines[idx:idx+3]
            
            # Extraction des segments d'espaces vides (gouttières) sur chaque ligne
            line_gaps = []
            for line in window_lines:
                gaps = []
                for i in range(1, len(line.words)):
                    gap_x0 = line.words[i-1].x1
                    gap_x1 = line.words[i].x0
                    if gap_x1 - gap_x0 > 6.0: # Écart d'au moins 6pt
                        gaps.append((gap_x0, gap_x1))
                line_gaps.append(gaps)
                
            # Vérification de l'alignement (intersection d'intervalles X sur les 3 lignes)
            aligned_count = 0
            for g1_x0, g1_x1 in line_gaps[0]:
                # Intersection avec la ligne 2
                ov2 = [g2 for g2 in line_gaps[1] if max(g1_x0, g2[0]) < min(g1_x1, g2[1])]
                if ov2:
                    # Intersection des résidus avec la ligne 3
                    for g2_x0, g2_x1 in ov2:
                        overlap_x0 = max(g1_x0, g2_x0)
                        overlap_x1 = min(g1_x1, g2_x1)
                        ov3 = [g3 for g3 in line_gaps[2] if max(overlap_x0, g3[0]) < min(overlap_x1, g3[1])]
                        if ov3:
                            aligned_count += 1
                            break # On a validé cet alignement vertical
            
            if aligned_count >= 2: # Au moins 2 gouttières alignées (définissant 3 colonnes)
                return True

        return False

    # ========================================================
    # INDICE 3 : LIGNES DE DÉMARCATION HORIZONTALES (BOOKTABS)
    # ========================================================

    def _detect_booktabs_rules(self, page: fitz.Page, lines: List[TextLine]) -> bool:
        """
        Repère si un bloc de données textuelles se retrouve entouré de lignes
        vectorielles horizontales très larges (style booktabs académique).
        """
        try:
            drawings = page.get_drawings()
        except Exception:
            return False

        page_w = page.rect.width
        horizontal_rules = []

        for d in drawings:
            rect = d.get("rect")
            if not rect:
                continue
            x0, y0, x1, y1 = rect
            w = x1 - x0
            h = y1 - y0
            
            # Ligne horizontale fine (h < 4.0) et large (> 30% de la page)
            if w > page_w * 0.30 and h < 4.0:
                horizontal_rules.append(y0)

        if len(horizontal_rules) < 2:
            return False

        horizontal_rules.sort()

        # Évaluation des bandes de texte situées entre deux lignes vectorielles consécutives
        for i in range(len(horizontal_rules) - 1):
            y_top = horizontal_rules[i]
            y_bot = horizontal_rules[i+1]
            
            # Captures des lignes textuelles s'insérant dans cet intervalle
            lines_in_between = [l for l in lines if y_top < l.y < y_bot]
            
            if len(lines_in_between) >= 2:
                total_words = sum(len(l.words) for l in lines_in_between)
                if total_words > 0:
                    # Calcul de la densité numérique du bloc "emprisonné"
                    digit_count = sum(sum(1 for c in w.text if c.isdigit()) for l in lines_in_between for w in l.words)
                    digit_ratio = digit_count / total_words
                    
                    # RÈGLE D'INTELLIGENCE : Pour être un tableau, ce bloc emprisonné doit :
                    # 1. Soit contenir une vraie densité de données (chiffres > 15%)
                    if digit_ratio > 0.15:
                        return True
                        
                    # 2. Soit présenter une vraie structure de grille (au moins 3 colonnes / 2 gouttières alignées)
                    if self._detect_multi_gutter_grid(lines_in_between):
                        return True

        return False

    # ========================================================
    # SCORE ENGINE
    # ========================================================

    def _compute_score(self, f: Dict) -> int:

        score = 0

        if f["vector_lines"]:
            score += 3

        if f["aligned_columns"]:
            score += 2

        if f["regular_rows"]:
            score += 1

        if f["high_density"]:
            score += 4

        if f["fragmented_text"]:
            score += 2

        if f["numeric_pattern"]:
            score += 4

        if f["grid_structure"]:
            score += 5
            
        if f["multi_gutter_grid"]:
            score += 5 # Poids important car signature d'alignement géométrique forte

        if f["booktabs_rules"]:
            score += 4 # Poids important car signature vectorielle académique forte

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