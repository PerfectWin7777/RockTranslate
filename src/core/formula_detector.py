"""
src/core/formula_detector.py — Détection de blocs mathématiques par signatures spatiales
Zéro ML, zéro regex, zéro hardcode publisher.
Analyse la physique spatiale du bloc via pdfplumber words.
"""
from dataclasses import dataclass
from typing import List


@dataclass
class FormulaFeatures:
    """Features spatiales extraites d'un bloc."""
    token_count: int
    bbox_width: float
    bbox_height: float
    token_density: float          # tokens / largeur → élevé = formule
    baseline_variance: float      # variance des tops → élevé = exposants/indices
    non_alpha_ratio: float        # ratio chars non-alphabétiques
    surface_density: float        # tokens / surface bbox
    is_isolated: bool             # marges verticales larges avant/après
    is_centered: bool             # distance au centre de page faible
    avg_token_width: float        # tokens courts = symboles mathématiques
    score: float = 0.0


class FormulaDetector:
    """
    Détecte si un FitzBlock est une formule mathématique
    par analyse de signatures spatiales multi-critères.

    Utilise les words pdfplumber déjà extraits (x_tolerance=1)
    pour une précision maximale.

    Score >= threshold → formule → skip_translation = True
    """

    def __init__(
        self,
        page_width: float,
        page_height: float,
        all_words: list,           # tous les mots pdfplumber de la page
        threshold: float = 4.0,   # score min pour classifier formule
    ):
        self.page_width  = page_width
        self.page_height = page_height
        self.all_words   = all_words
        self.threshold   = threshold

        # Pré-calcule les tops de toutes les lignes pour détecter l'isolation
        self._line_tops = sorted(set(round(w["top"]) for w in all_words))

    # ── API publique ──────────────────────────────────────────────────────────

    def is_formula(self, block) -> bool:
        """Retourne True si le bloc est une formule mathématique."""
        features = self.extract_features(block)
        return features.score >= self.threshold

    def extract_features(self, block) -> FormulaFeatures:
        """Extrait les features spatiales et calcule le score."""
        # Récupère les mots pdfplumber dans la bbox du bloc
        words = self._get_words_in_block(block)

        if not words:
            return FormulaFeatures(
                token_count=0, bbox_width=0, bbox_height=0,
                token_density=0, baseline_variance=0, non_alpha_ratio=0,
                surface_density=0, is_isolated=False, is_centered=False,
                avg_token_width=0, score=0.0
            )

        bbox_w = block.right - block.left
        bbox_h = block.bottom - block.top
        surface = max(bbox_w * bbox_h, 1.0)
        n = len(words)

        # ── Feature 1 : densité de tokens ────────────────────────────────────
        # Formule : beaucoup de petits tokens dans peu de largeur
        token_density = n / max(bbox_w, 1.0)

        # ── Feature 2 : variance des baselines (exposants/indices) ───────────
        tops = [w["top"] for w in words]
        mean_top = sum(tops) / len(tops)
        baseline_variance = sum((t - mean_top) ** 2 for t in tops) / len(tops)

        # ── Feature 3 : ratio non-alphabétique ───────────────────────────────
        all_chars = "".join(w["text"] for w in words)
        non_alpha = sum(1 for c in all_chars if not c.isalpha())
        non_alpha_ratio = non_alpha / max(len(all_chars), 1)

        # ── Feature 4 : densité surfacique ───────────────────────────────────
        surface_density = n / surface * 1000  # ×1000 pour lisibilité

        # ── Feature 5 : isolation verticale ──────────────────────────────────
        # Un bloc de formule display math a souvent des marges vides avant/après
        is_isolated = self._check_isolation(block)

        # ── Feature 6 : centrage horizontal ──────────────────────────────────
        page_mid = self.page_width / 2.0
        block_mid = (block.left + block.right) / 2.0
        distance_to_center = abs(block_mid - page_mid)
        is_centered = distance_to_center < self.page_width * 0.15

        # ── Feature 7 : largeur moyenne des tokens ────────────────────────────
        # Symboles mathématiques = tokens très courts
        avg_token_width = sum(w["x1"] - w["x0"] for w in words) / n

        # ── Score probabiliste ────────────────────────────────────────────────
        score = 0.0

        # Baseline variance : signal le plus fort (exposants = formule)
        if baseline_variance > 2.0:
            score += 2.0
        elif baseline_variance > 0.5:
            score += 1.0

        # Densité de tokens élevée
        if token_density > 0.3:
            score += 1.0

        # Ratio non-alpha élevé
        if non_alpha_ratio > 0.4:
            score += 1.0
        elif non_alpha_ratio > 0.25:
            score += 0.5

        # Tokens très courts (symboles)
        if avg_token_width < 8.0:
            score += 1.0
        elif avg_token_width < 14.0:
            score += 0.5

        # Isolation verticale (display math)
        if is_isolated:
            score += 1.5

        # Centrage (display math souvent centré)
        if is_centered and is_isolated:
            score += 1.0

        # Bloc très court (1-2 lignes) avec beaucoup de non-alpha
        if bbox_h < 20 and non_alpha_ratio > 0.3:
            score += 0.5

        # Pénalité : bloc large avec texte courant (paragraphe normal)
        if bbox_w > self.page_width * 0.6 and non_alpha_ratio < 0.15:
            score -= 2.0

        # Pénalité : trop de mots (paragraphe)
        if n > 20 and baseline_variance < 1.0:
            score -= 1.5

        # Pénalité : token unique très court = numéro de page / label isolé
        if n == 1 and avg_token_width < 10.0:
            score -= 3.0

        return FormulaFeatures(
            token_count=n,
            bbox_width=bbox_w,
            bbox_height=bbox_h,
            token_density=token_density,
            baseline_variance=baseline_variance,
            non_alpha_ratio=non_alpha_ratio,
            surface_density=surface_density,
            is_isolated=is_isolated,
            is_centered=is_centered,
            avg_token_width=avg_token_width,
            score=score,
        )

    # ── Helpers privés ────────────────────────────────────────────────────────

    def _get_words_in_block(self, block) -> list:
        """Filtre les mots pdfplumber qui tombent dans la bbox du bloc."""
        return [
            w for w in self.all_words
            if (w["x0"] >= block.left - 3 and
                w["x1"] <= block.right + 3 and
                w["top"] >= block.top - 3 and
                w["bottom"] <= block.bottom + 3)
        ]

    def _check_isolation(self, block) -> bool:
        """
        Vérifie si le bloc a des marges verticales vides avant et après.
        Cherche s'il y a un gap de >8pts sans mots au-dessus et en-dessous.
        """
        margin = 8.0
        top_clear    = not any(
            block.top - margin < w["bottom"] <= block.top
            for w in self.all_words
        )
        bottom_clear = not any(
            block.bottom <= w["top"] < block.bottom + margin
            for w in self.all_words
        )
        return top_clear and bottom_clear