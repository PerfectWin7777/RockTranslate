"""
RockTranslate — TMX export (translation memory for CAT tools).

TMX 1.4b: one <tu> per aligned pair (source paragraph -> its translation).
Trados, memoQ, OmegaT, Wordfast and others import it, so the work done on a
paper can be reused in a professional translation project.

    >>> write_tmx([("Hello", "Bonjour")], "paper.tmx", "en", "fr")

Inline markup used internally (<color_HEX>, <sup>, <b>...) is removed; pairs
whose translation equals the source (numbers, names, formulas) and exact
duplicates are skipped.

Path: src/rocktranslate/core/tmx.py
Author: RockTranslate Contributors
License: MIT License
"""

import html
import re
import time
from typing import Iterable, List, Optional, Tuple

LANGUAGE_CODES = {
    "english": "en", "french": "fr", "spanish": "es", "german": "de", "portuguese": "pt", "italian": "it",
    "dutch": "nl", "polish": "pl", "russian": "ru", "ukrainian": "uk", "turkish": "tr", "arabic": "ar",
    "hebrew": "he", "persian": "fa", "hindi": "hi", "bengali": "bn", "chinese": "zh", "chinese (simplified)": "zh-CN",
    "chinese (traditional)": "zh-TW", "japanese": "ja", "korean": "ko", "vietnamese": "vi", "thai": "th",
    "indonesian": "id", "malay": "ms", "swahili": "sw", "greek": "el", "czech": "cs", "romanian": "ro",
    "hungarian": "hu", "swedish": "sv", "danish": "da", "norwegian": "no", "finnish": "fi",
}

_TAG = re.compile(r"</?(?:color(?:_[0-9A-Za-z]+)?|sup|sub|b|i|em|strong|u|span)[^>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def language_code(name_or_code: Optional[str], default: str = "en") -> str:
    """'French' -> 'fr'; codes are kept ('pt-BR' stays 'pt-BR')."""
    value = (name_or_code or "").strip()
    if not value:
        return default
    return LANGUAGE_CODES.get(value.lower(), value if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*", value) else default)


def plain(text: str) -> str:
    """Segment text for a CAT tool: internal tags removed, whitespace normalized."""
    return re.sub(r"\s+", " ", _CONTROL.sub("", _TAG.sub("", text or ""))).strip()


def clean_pairs(pairs: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out, seen = [], set()
    for source, target in pairs:
        s, t = plain(source), plain(target)
        if not s or not t or s == t or (s, t) in seen:
            continue
        seen.add((s, t))
        out.append((s, t))
    return out


def tmx_text(pairs: Iterable[Tuple[str, str]], source_lang: str, target_lang: str,
             tool_version: str = "", note: str = "") -> str:
    src, tgt = language_code(source_lang), language_code(target_lang, default="und")
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    esc = lambda s: html.escape(s, quote=False)       # noqa: E731
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE tmx SYSTEM "tmx14.dtd">',
        '<tmx version="1.4">',
        f'  <header creationtool="RockTranslate" creationtoolversion="{esc(tool_version)}" datatype="plaintext" '
        f'segtype="paragraph" adminlang="en" srclang="{src}" o-tmf="RockTranslate" creationdate="{stamp}"/>',
        "  <body>",
    ]
    for source, target in clean_pairs(pairs):
        lines.append("    <tu>")
        if note:
            lines.append(f'      <prop type="x-document">{esc(note)}</prop>')
        lines.append(f'      <tuv xml:lang="{src}"><seg>{esc(source)}</seg></tuv>')
        lines.append(f'      <tuv xml:lang="{tgt}"><seg>{esc(target)}</seg></tuv>')
        lines.append("    </tu>")
    lines += ["  </body>", "</tmx>", ""]
    return "\n".join(lines)


def write_tmx(pairs: Iterable[Tuple[str, str]], path: str, source_lang: str, target_lang: str,
              tool_version: str = "", note: str = "") -> int:
    """Writes the TMX file; returns the number of translation units."""
    pairs = clean_pairs(pairs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tmx_text(pairs, source_lang, target_lang, tool_version, note))
    return len(pairs)
