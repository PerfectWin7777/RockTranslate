"""
chunker.py — Découpage intelligent des paragraphes en batches LLM
Chemin : /src/translation/chunker.py

Stratégie :
  - Estime les tokens par paragraphe (heuristique : chars / 4)
  - Groupe les paragraphes en batches sans dépasser max_tokens
  - Respecte les limites par modèle
  - Un paragraphe > max_tokens est passé seul (jamais coupé)
"""
import re
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


def should_translate(line: FitzLine) -> bool:
    """
    Evaluates whether a physical line should be translated.
    Works on FitzLine instead of FitzBlock — same logic, smaller unit.
    """
    text = line.text.strip()

    # if len(text) < 5:
    #     # Keep short numeric tokens — likely table cells (e.g. "1", "3", "0.58")
    #     if re.match(r'^[\d\s,\.]+$', text):
    #         return True
    #     return False

    tl = text.lower()

    # Academic headings — always translate
    # if text.lower() in ["abstract", "keywords", "introduction", "references",
    #                      "conclusions", "acknowledgements"]:
    #     return True


    # if re.match(r'^\d+(\.\d+)*\.?\s+[A-Z]', text.strip()):
    #     return True

    # Isolated URLs / DOIs
    # if any(x in tl for x in ["http", "doi.org", "www.", "@"]):
    #     if len(text.split()) < 10:
    #         return False

    # Not enough real words
    # clean_words = [
    #     re.sub(r'[^a-zA-Z]', '', w)
    #     for w in text.split()
    # ]
    # clean_words = [w for w in clean_words if len(w) > 2]
    # if len(clean_words) < 3:  # 3 au lieu de 4 — les lignes sont plus courtes que les blocs
    #     return False

    # Too many digit tokens (formulas, raw data)
    # digit_tokens = sum(1 for w in text.split() if w.isdigit())
    # if digit_tokens / max(len(text.split()), 1) > 0.3:
    #     return False
    
    if getattr(line, 'skip_translation', False):
        
        return False
    
    return True


def should_translateSSSS(block: FitzBlock) -> bool:
    """
    Version instrumentée pour observer en temps réel pourquoi les blocs 
    sont acceptés ou rejetés du pipeline de traduction.
    """
    # Sécurité absolue : On traduit TOUJOURS les cellules de tableaux
    if type(block).__name__ == "FitzTableBlock":
        return True
    
    text = block.text.strip()
    
    # ── BLOC DE DÉBOGAGE VISUEL POUR LES PARAGRAPHES TRÈS LONGS OU RECHERCHÉS ──
    is_target = "consistency" in text.lower() or "matrix" in text.lower() or len(text) > 40
    
    if is_target:
        print(f"\n📢 [DEBUG should_translate] Analyse du Bloc ID: {block.block_id} (Page {block.page_number})")
        print(f"   -> Texte extrait brut : '{text[:120]}...'")
        print(f"   -> Découpage par espace (text.split()) : {text.split()[:4]} (Taille de la liste: {len(text.split())})")

    # Règle 1 : Trop court
    if len(text) < 5:
        if is_target:
            print("   ❌ REJETÉ : Le texte brut fait moins de 5 caractères.")
        return False
    
    tl = text.lower()
    
    # Règle 2 : Titres académiques
    is_academic_heading = False
    if text.strip().lower() in ["abstract", "keywords", "introduction", "references", "conclusions", "acknowledgements"]:
        is_academic_heading = True
        
    import re
    if re.match(r'^\d+(\.\d+)*\.?\s+[A-Z]', text.strip()):
        is_academic_heading = True
        
    if is_academic_heading:
        if is_target:
            print("   ✅ ACCEPTÉ : Détecté comme titre académique.")
        return True

    # Règle 3 : URLs ou DOIs isolés
    if any(x in tl for x in ["http", "doi.org", "www.", "@"]):
        words_count = len(text.split())
        if words_count < 10:
            if is_target:
                print(f"   ❌ REJETÉ : Détecté comme URL ou DOI isolé ({words_count} mots).")
            return False

    # Règle 4 : Filtrage par mots valides (C'est ici que l'absence d'espaces pose problème !)
    clean_words = []
    for w in text.split():
        cleaned = re.sub(r'[^a-zA-Z]', '', w)
        if len(cleaned) > 2:
            clean_words.append(cleaned)
            
    if is_target:
        print(f"   -> Mots nettoyés trouvés (len > 2) : {clean_words[:5]} (Total compté: {len(clean_words)})")
            
    if len(clean_words) < 4:
        if is_target:
            print(f"   ❌ REJETÉ : Pas assez de mots distincts détectés (Seulement {len(clean_words)} trouvés, minimum requis: 4).")
        return False
    
    # Règle 5 : Trop de chiffres
    digit_tokens = sum(1 for w in text.split() if w.isdigit())
    if digit_tokens / max(len(text.split()), 1) > 0.3:
        if is_target:
            print("   ❌ REJETÉ : Densité numérique trop élevée (formules ou données brutes).")
        return False

    if getattr(block, 'skip_translation', False):
        if is_target:
            print("   ❌ REJETÉ : skip_translation est à True.")
        return False
    
    if is_target:
        print("   🎉 ACCEPTÉ POUR TRADUCTION !")
    return True




@dataclass
class Batch:
    """A batch of physical lines to send to the LLM in a single call."""
    lines: list[FitzLine]
    estimated_tokens: int

    @property
    def ids(self) -> list[int]:
        return [id(l) for l in self.lines]




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
    lines: list[FitzLine],
    model: str = "gemini/gemini-2.5-flash-lite",
    max_tokens: int | None = None,
) -> list[Batch]:
    """
    Splits a list of FitzLine objects into optimal LLM batches.
    Same logic as before — only the input type changes.
    """
    if not lines:
        return []

    budget = max_tokens or get_max_source_tokens(model)
    batches: list[Batch] = []
    current: list = []
    current_tokens = 0

    for item in lines:
        # item is a tuple (block, line_idx, line)
        block, line_idx, line = item
        text = (line.styled_text or line.text or "").strip()
        if not text:
            continue

        tokens = _estimate_tokens(text)

        if tokens > budget:
            if current:
                batches.append(Batch(lines=current, estimated_tokens=current_tokens))
                current, current_tokens = [], 0
            batches.append(Batch(lines=[item], estimated_tokens=tokens))
            continue

        if current_tokens + tokens <= budget:
            current.append(item)
            current_tokens += tokens
        else:
            batches.append(Batch(lines=current, estimated_tokens=current_tokens))
            current = [item]
            current_tokens = tokens

    if current:
        batches.append(Batch(lines=current, estimated_tokens=current_tokens))

    return batches


def filter_noise(lines: list[FitzLine]) -> list[FitzLine]:
    """Filters non-translatable lines by structural analysis."""
    kept = [l for l in lines if should_translate(l)]
    logger.debug(f"Filter: {len(lines)} → {len(kept)} lines")
    return kept


def batches_summary(batches: list[Batch]) -> str:
    """Résumé lisible des batches pour le logging."""
    total_paras  = sum(len(b.lines) for b in batches)
    total_tokens = sum(b.estimated_tokens for b in batches)
    lines = [
        f"  {len(batches)} batch(es) | "
        f"{total_paras} paragraphes | "
        f"~{total_tokens:,} tokens estimés"
    ]
    for i, b in enumerate(batches):
        lines.append(
            f"  Batch {i+1:02d} : "
            f"{len(b.lines)} para(s), "
            f"~{b.estimated_tokens:,} tokens"
        )
    return "\n".join(lines)