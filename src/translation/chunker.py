
# src/translation/chunker.py

import re
from dataclasses import dataclass
from loguru import logger

# ── Limites par modèle (tokens de contexte utilisables pour le texte source) ──
MODEL_TOKEN_LIMITS: dict[str, int] = {
    # Modèles Lite / Mini (max 1000 tokens ≈ 4000 caractères, idéal pour les gros volumes)
    "gemini/gemini-3.1-flash-lite":      1000,
    "gemini/gemini-2.5-flash-lite":      1000,
    "gemini/gemini-3-flash-preview":      1000,
    
    # Modèles standard Flash (max 1500 tokens)
    "gemini/gemini-2.5-flash":          1500,
    "ollama/mistral":                     800,
    "ollama/llama3":                      800,

    # Modèles Pro / Large (max 2500 tokens, idéal pour les paragraphes complexes)
    "gemini/gemini-2.5-pro":            2500,
    "gpt-4o":                            2500,
    "claude-sonnet-4-20250514":          2500,
}

_DEFAULT_LIMIT = 1000  # Budget de tokens par défaut si le modèle n'est pas listé


@dataclass
class Batch:
    """Représente un lot de lignes de texte à envoyer au LLM en un seul appel."""
    segments: list[dict]  # Liste de {"id": str, "text": str}
    estimated_tokens: int

    @property
    def ids(self) -> list[str]:
        return [s["id"] for s in self.segments]


def should_translate(text: str) -> bool:
    """
    Évalue si un segment de texte brut doit être envoyé à la traduction.
    Filtre le bruit géométrique, les numéros isolés et les formules mathématiques simples.
    """
    text = text.strip()
    if not text:
        return False

    # Élimine les numéros de page isolés ou chiffres seuls (ex: "1", "24", "0.58")
    if text.isdigit() or re.match(r'^[\d\s,\.\-\+]+$', text):
        return False

    # Élimine les références de citation isolées (ex: "[12]", "(5)")
    if re.match(r'^\[\d+\]$', text) or re.match(r'^\(\d+\)$', text):
        return False

    # Élimine les éléments trop courts de bruit (ex: "a", "x", "by")
    # if len(text) < 2:
    #     return False
    
    # MODIFICATION CIBLÉE : On garde les mots d'une seule lettre (comme "a" ou "I")
    if len(text) == 1 and not text.isalpha():
        return False

    return True


def _estimate_tokens(text: str) -> int:
    """
    Estimation rapide et sécurisée du nombre de tokens.
    Heuristique universelle : 1 token ≈ 4 caractères (Latin/Latin-ext).
    Pour le CJK (chinois/japonais) : 1 token ≈ 1.5 caractères.
    """
    if not text:
        return 0
    # Détection des caractères CJK
    cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if cjk_chars > len(text) * 0.3:
        return int(len(text) / 1.5)
    
    # Coefficient d'expansion de sécurité de 1.3
    return max(1, int(len(text) / 4 * 1.3))


def get_max_source_tokens(model: str) -> int:
    """Retourne le budget de tokens source pour un modèle donné."""
    return MODEL_TOKEN_LIMITS.get(model, _DEFAULT_LIMIT)


def build_batches(
    segments: dict[str, str],
    model: str = "gemini/gemini-2.5-flash-lite",
    max_tokens: int | None = None,
) -> list[Batch]:
    """
    Regroupe un dictionnaire de segments de texte sémantiques en lots (batches) optimisés pour le LLM.
    """
    if not segments:
        return []

    budget = max_tokens or get_max_source_tokens(model)
    batches: list[Batch] = []
    current_segments: list[dict] = []
    current_tokens = 0

    # Sécurité : Pas plus de 60 lignes/segments par lot pour garantir la rigueur du JSON de l'IA
    MAX_SEGMENTS_PER_BATCH = 60

    for text_id, text in segments.items():
        # Filtrage systématique du bruit avant intégration
        # if not should_translate(text):
        #     continue

        tokens = _estimate_tokens(text)
        item = {"id": text_id, "text": text}

        # Si un seul paragraphe dépasse le budget global, il est envoyé seul (jamais coupé)
        if tokens > budget:
            if current_segments:
                batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))
                current_segments, current_tokens = [], 0
            batches.append(Batch(segments=[item], estimated_tokens=tokens))
            continue

        # Accumulation dans le lot en cours
        # CORRECTIF : On ajoute le segment si on ne dépasse ni le budget de tokens, ni la limite physique d'éléments
        if (current_tokens + tokens <= budget) and (len(current_segments) < MAX_SEGMENTS_PER_BATCH):
            current_segments.append(item)
            current_tokens += tokens
        else:
            batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))
            current_segments = [item]
            current_tokens = tokens

    # Ajout du dernier lot résiduel
    if current_segments:
        batches.append(Batch(segments=current_segments, estimated_tokens=current_tokens))

    return batches


def filter_noise(segments: dict[str, str]) -> dict[str, str]:
    """Filtre les segments non traduisibles d'un dictionnaire."""
    filtered = {text_id: text for text_id, text in segments.items() if should_translate(text)}
    logger.debug(f"Filtrage : {len(segments)} -> {len(filtered)} segments d'intérêt retenus.")
    return filtered


def batches_summary(batches: list[Batch]) -> str:
    """Génère un résumé lisible du plan d'envoi en lots pour la console."""
    total_segments = sum(len(b.segments) for b in batches)
    total_tokens = sum(b.estimated_tokens for b in batches)
    
    summary_lines = [
        f"📋 Plan de découpage sémantique : {len(batches)} lot(s) | "
        f"{total_segments} segment(s) retenu(s) | ~{total_tokens:,} tokens estimés."
    ]
    for i, b in enumerate(batches):
        summary_lines.append(
            f"  -> Lot {i+1:02d} : {len(b.segments)} segment(s), ~{b.estimated_tokens:,} tokens"
        )
    return "\n".join(summary_lines)