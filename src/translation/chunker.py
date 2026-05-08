"""
chunker.py — Découpage intelligent des paragraphes en batches LLM
Chemin : /src/translation/chunker.py

Stratégie :
  - Estime les tokens par paragraphe (heuristique : chars / 4)
  - Groupe les paragraphes en batches sans dépasser max_tokens
  - Respecte les limites par modèle
  - Un paragraphe > max_tokens est passé seul (jamais coupé)
"""

from loguru import logger
from dataclasses import dataclass
from core.domain import Paragraph

# ── Limites par modèle (tokens contexte utilisable pour le texte source) ──────
MODEL_TOKEN_LIMITS: dict[str, int] = {
    "gemini/gemini-3.1-flash-lite":      800_000,
    "gemini/gemini-2.5-pro":            800_000,
    "gemini/gemini-2.5-flash":          800_000,
    "gemini/gemini-2.0-flash":          800_000,
    "gemini/gemini-1.5-pro":            800_000,
    "gpt-4o":                            16_000,
    "gpt-4o-mini":                       16_000,
    "claude-sonnet-4-20250514":          80_000,
    "claude-haiku-4-5-20251001":         80_000,
    "ollama/mistral":                     6_000,
    "ollama/llama3":                      6_000,
}

# Limite par défaut si le modèle n'est pas listé
_DEFAULT_LIMIT = 16_000

# Fraction de la fenêtre réservée au texte source (le reste = réponse + prompt)
_SOURCE_FRACTION = 0.40


def is_content(para) -> bool:
    t = para.text.strip()
    
    # 1. Trop court pour être du contenu
    if len(t) < 40:
        return False
    
    # 2. Ratio URL trop élevé (headers web, DOI, liens)
    url_chars = sum(len(w) for w in t.split() if '://' in w or w.startswith('www.'))
    if url_chars / len(t) > 0.3:
        return False
    
    # 3. Pas assez de mots réels (headers = peu de mots, beaucoup de symboles)
    words = [w for w in t.split() if w.isalpha() and len(w) > 2]
    if len(words) < 5:
        return False
    
    # 4. Trop de chiffres isolés (numéros de page, références isolées)
    digit_tokens = sum(1 for w in t.split() if w.isdigit())
    if digit_tokens / max(len(t.split()), 1) > 0.4:
        return False
    
    return True



@dataclass
class Batch:
    """Un batch de paragraphes à envoyer au LLM en un seul appel."""
    paragraphs: list[Paragraph]
    estimated_tokens: int

    @property
    def ids(self) -> list[int]:
        return [id(p) for p in self.paragraphs]


def _estimate_tokens(text: str) -> int:
    """
    Estimation rapide du nombre de tokens.
    Heuristique universelle : 1 token ≈ 4 caractères (Latin/Latin-ext).
    Pour le CJK (chinois/japonais) : 1 token ≈ 1.5 caractères.
    """
    # Détecte si le texte contient des caractères CJK
    if not text:
        return 0
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(text) * 0.3:
        return int(len(text) / 1.5)
    # × 1.3 pour anticiper l'expansion à la traduction
    return max(1, int(len(text) / 4 * 1.3))


def get_max_source_tokens(model: str) -> int:
    """Retourne le budget tokens source pour un modèle donné."""
    limit = MODEL_TOKEN_LIMITS.get(model, _DEFAULT_LIMIT)
    return int(limit * _SOURCE_FRACTION)


def build_batches(
    paragraphs: list[Paragraph],
    model: str = "gemini/gemini-2.0-flash",
    max_tokens: int | None = None,
) -> list[Batch]:
    """
    Découpe une liste de paragraphes en batches optimaux.

    Paramètres :
        paragraphs : liste de Paragraph à traduire
        model      : nom du modèle LiteLLM (détermine la limite)
        max_tokens : override manuel (None = auto depuis MODEL_TOKEN_LIMITS)

    Retourne :
        Liste de Batch, chacun prêt pour un appel LLM.
    """
    if not paragraphs:
        return []

    budget = max_tokens or get_max_source_tokens(model)
    batches: list[Batch] = []
    current: list[Paragraph] = []
    current_tokens = 0

    for para in paragraphs:
        if not para.text or not para.text.strip():
            continue  # ignore les paragraphes vides

        tokens = _estimate_tokens(para.text)

        # Paragraphe trop grand seul → batch solo
        if tokens > budget:
            if current:
                batches.append(Batch(paragraphs=current,
                                     estimated_tokens=current_tokens))
                current, current_tokens = [], 0
            batches.append(Batch(paragraphs=[para], estimated_tokens=tokens))
            continue

        # Ajout au batch courant si ça rentre
        if current_tokens + tokens <= budget:
            current.append(para)
            current_tokens += tokens
        else:
            # Batch courant plein → flush et nouveau batch
            batches.append(Batch(paragraphs=current,
                                 estimated_tokens=current_tokens))
            current = [para]
            current_tokens = tokens

    if current:
        batches.append(Batch(paragraphs=current, estimated_tokens=current_tokens))

    return batches


def filter_noise(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Filtre les paragraphes non-traductibles par analyse structurelle."""
    kept = [p for p in paragraphs if is_content(p)]
    logger.debug(f"Filtrage : {len(paragraphs)} → {len(kept)} paragraphes")
    return kept


def batches_summary(batches: list[Batch]) -> str:
    """Résumé lisible des batches pour le logging."""
    total_paras  = sum(len(b.paragraphs) for b in batches)
    total_tokens = sum(b.estimated_tokens for b in batches)
    lines = [
        f"  {len(batches)} batch(es) | "
        f"{total_paras} paragraphes | "
        f"~{total_tokens:,} tokens estimés"
    ]
    for i, b in enumerate(batches):
        lines.append(
            f"  Batch {i+1:02d} : "
            f"{len(b.paragraphs)} para(s), "
            f"~{b.estimated_tokens:,} tokens"
        )
    return "\n".join(lines)