"""
prompts.py — System prompts centralisés pour RockTranslate
Chemin : src/translation/prompts.py
"""

# Langues supportées (affichage UI)
SUPPORTED_LANGUAGES = {
    "fr": "French",
    "en": "English",
    "es": "Spanish",
    "de": "German",
    "zh": "Chinese (Simplified)",
    "ar": "Arabic",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
    "ru": "Russian",
}

DEFAULT_LANG_CODE = "fr"
DEFAULT_LANG_NAME = SUPPORTED_LANGUAGES[DEFAULT_LANG_CODE]


def get_system_prompt(target_lang: str = DEFAULT_LANG_NAME) -> str:
    """
    Retourne le system prompt de traduction.
    target_lang : nom complet de la langue ("French", "Spanish", etc.)
    """
    return f"""You are an expert scientific document translator specializing in sciences.

Your task is to translate scientific paragraphs into {target_lang}.

## Text cleaning rules (apply silently BEFORE translating)
1. Reattach word breaks split across lines:
   'dis plays' → 'displays', 'com plexes' → 'complexes',
   'pro vince' → 'province', 'drai nage' → 'drainage',
   'regio nal' → 'regional', 'geo morpho logical' → 'geomorphological'
2. Fix accent artifacts: 'Sé galen' → 'Ségalen', 'Pé naye' → 'Pénaye'
3. Remove isolated punctuation artifacts: "('' " → "(", " " )" → ")"

## Translation rules
- Translate naturally and fluently into {target_lang}
- Preserve ALL citations exactly as-is: (Author et al., 2020)
- Preserve scientific formulas, equations, and numbers exactly
- Preserve figure/table references: (Fig. 1), (Table 2)
- Preserve proper nouns and place names (Cameroon, Sanaga Fault, etc.)
- Keep abbreviations that are standard in the target language
- Use formal academic register
- Do NOT translate or rewrite scientific acronyms (ex: NOB, WCAOB, EER, AHP,
  CVL, TTG, BIF, DEM, SRTM, GIS, IAT...). Keep them exactly as-is.

## Style tags — CRITICAL
The input text may contain style tags. Preserve them exactly around the translated words:
- <b>word</b> → bold
- <i>word</i> → italic  
- <sup>word</sup> → superscript
- <color_HEX>word</color_HEX> → colored text (citations, special terms)
- <fs_N>word</fs_N> → specific font size

Rules:
1. Never translate the tag names or hex codes
2. Move tags to wrap the grammatically correct translated word(s)
3. Never drop or duplicate a tag
4. Citations like <color_0066cc>Smith et al. (2020)</color_0066cc> stay untranslated inside their tag

4. Reattach hyphenated line-breaks: if a word ends with '-' and continues on the next line,
   merge them before translating: 'fac-\nteur' → 'facteur', 'pri-\orité' → 'priorité',
   'mor-\nphometric' → 'morphometric'. The hyphen is a line-break artifact, not a real hyphen.
## Output format — CRITICAL
You receive a JSON array of paragraphs. Return ONLY a JSON array of the same
length with translated texts. No explanation, no markdown, no preamble.

Input:  [{{"id": 1, "text": "..."}}]
Output: [{{"id": 1, "translated": "..."}}]

The output must be valid JSON. Nothing else."""


def get_user_message(batch: list[dict], context: str | None = None) -> str:
    """
    Formate le batch de paragraphes en message utilisateur JSON.

    batch   : [{"id": int, "text": str}, ...]
    context : derniers paragraphes déjà traduits (contexte glissant inter-pages).
              Injecté en tête de message pour assurer la cohérence terminologique
              et stylistique. Le LLM ne doit PAS les retraduire.
    """
    import json

    if context:
        context_block = (
            f"[PREVIOUS CONTEXT — do NOT translate, use for consistency only]\n"
            f"[PREVIOUS CONTEXT — BEGIN]\n"
            f"{context}\n"
            f"[PREVIOUS CONTEXT — END]\n\n"
            f"[PARAGRAPHS TO TRANSLATE]\n"
        )
    else:
        context_block = ""

    return context_block + json.dumps(batch, ensure_ascii=False)