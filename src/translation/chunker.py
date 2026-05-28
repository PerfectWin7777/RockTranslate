"""
chunker.py — Découpage intelligent des paragraphes en batches LLM
Chemin : /src/translation/chunker.py

Stratégie :
  - Estime les tokens par paragraphe (heuristique : chars / 4)
  - Groupe les paragraphes en batches sans dépasser max_tokens
  - Respecte les limites par modèle
  - Un paragraphe > max_tokens est passé seul (jamais coupé)
"""
from collections import Counter
from loguru import logger
from dataclasses import dataclass
from core.domain import FitzBlock, FitzLine, FitzSpan

# ── Limites par modèle (tokens contexte utilisable pour le texte source) ──────
MODEL_TOKEN_LIMITS: dict[str, int] = {
    # Modèles Lite / Mini (max 1000 tokens ≈ 4000 caractères, idéal pour éviter les boucles)
    "gemini/gemini-3.1-flash-lite":      1000,
    "gemini/gemini-2.5-flash-lite":      1000,
    "gpt-4o-mini":                       1000,
    "claude-haiku-4-5-20251001":         1000,
    
    # Modèles standard Flash (max 1500 tokens)
    "gemini/gemini-2.5-flash":          1500,
    "gemini/gemini-2.0-flash":          1500,
    "ollama/mistral":                     800,
    "ollama/llama3":                      800,

    # Modèles Pro / Large (max 2500 tokens, car ils raisonnent mieux sur les longues listes)
    "gemini/gemini-2.5-pro":            2500,
    "gemini/gemini-1.5-pro":            2500,
    "gpt-4o":                            2500,
    "claude-sonnet-4-20250514":          2500,
}

# Limite par défaut si le modèle n'est pas listé
# Par — budget basé sur la réponse max, pas le contexte
_DEFAULT_LIMIT = 1000  # tokens source par batch → réponse ~7500 tokens

# Fraction de la fenêtre réservée au texte source (le reste = réponse + prompt)
_SOURCE_FRACTION = 0.10


def _dominant_color(block: FitzBlock) -> tuple[int, int, int]:
    """
    Retourne la couleur dominante du bloc (vote par nombre de caractères).
    Couleur en RGB 0-255.
    """
    counts: Counter = Counter()
    for line in block.lines:
        for span in line.spans:
            for obj in span.raw_objects:
                # obj.color est en float (0.0-1.0) depuis pdf_extractor
                # On convertit en int 0-255 pour la comparaison
                c = tuple(int(v * 255) for v in obj.color)
                counts[c] += len(obj.text)
    if not counts:
        return (0, 0, 0)
    return counts.most_common(1)[0][0]


def should_translate(block: FitzBlock) -> bool:
    """
    Evaluates whether a visual block should be translated or preserved as-is.
    Filters out math equations, isolated numbers, URLs, and non-black styled spans (links/citations).
    """

    # --- FORCE LA TRADUCTION DES TABLEAUX ---
    if type(block).__name__ == "FitzTableBlock":
        return True
    
    text = block.text.strip()
    
    # 1. Trop court
    if len(text) < 5:
        return False
    
    # 2. URL / DOI / email
    tl = text.lower()
    if any(x in tl for x in ["http", "doi.org", "www.", "@"]):
        return False
    
    # 3. Pas assez de vrais mots
    words = [w for w in text.split() if w.isalpha() and len(w) > 2]
    if len(words) < 4:
        return False
    
    # 4. Trop de chiffres isolés (tableaux, formules)
    digit_tokens = sum(1 for w in text.split() if w.isdigit())
    if digit_tokens / max(len(text.split()), 1) > 0.3:
        return False
    
    # 5. Non-black text check (e.g., colored hyperlinks, blue citations)
    # FitzSpan.color uses "rgb(r,g,b)". We inspect the first span to check dominant text color
    # if block.lines and block.lines[0].spans:
    #     first_span = block.lines[0].spans[0]
    #     try:
    #         color_str = first_span.color.replace("rgb(", "").replace(")", "")
    #         r, g, b = [int(v.strip()) for v in color_str.split(",")]
    #         # If text is distinctly colored (not black or dark grey), preserve it
    #         if not (r < 50 and g < 50 and b < 50):
    #             return False
    #     except Exception:
    #         pass


    # Références et sections marquées
    if getattr(block, 'skip_translation', False):
        return False
    
    return True



@dataclass
class Batch:
    """Un batch de paragraphes à envoyer au LLM en un seul appel."""
    paragraphs: list[FitzBlock]
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
    return MODEL_TOKEN_LIMITS.get(model, 4000)


def build_batches(
    paragraphs: list[FitzBlock],
    model: str = "gemini/gemini-2.5-flash-lite",
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
    current: list[FitzBlock] = []
    current_tokens = 0

    for block in paragraphs:
        if not block.text or not block.text.strip():
            continue  # ignore les paragraphes vides

        tokens = _estimate_tokens(block.text)

        # Paragraphe trop grand seul → batch solo
        if tokens > budget:
            if current:
                batches.append(Batch(paragraphs=current,
                                     estimated_tokens=current_tokens))
                current, current_tokens = [], 0
            batches.append(Batch(paragraphs=[block], estimated_tokens=tokens))
            continue

        # Ajout au batch courant si ça rentre
        if current_tokens + tokens <= budget:
            current.append(block)
            current_tokens += tokens
        else:
            # Batch courant plein → flush et nouveau batch
            batches.append(Batch(paragraphs=current,
                                 estimated_tokens=current_tokens))
            current = [block]
            current_tokens = tokens

    if current:
        batches.append(Batch(paragraphs=current, estimated_tokens=current_tokens))

    return batches


def filter_noise(paragraphs: list[FitzBlock]) -> list[FitzBlock]:
    """Filtre les paragraphes non-traductibles par analyse structurelle."""
    kept = [p for p in paragraphs if should_translate(p)]
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