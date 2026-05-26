"""
src/core/cid_normalizer.py — Résolution universelle des CID via ToUnicode embarqué

Stratégie :
1. Lit la vraie table ToUnicode de chaque police embarquée dans le PDF
2. Construit un dict {cid_int: unicode_char} spécifique à CE PDF
3. Fallback sur table heuristique si ToUnicode absent

Fonctionne pour tous les éditeurs (Elsevier, Springer, Wiley, IEEE...)
car on lit la table du PDF lui-même, pas une table hardcodée.
"""

import re
import fitz
from loguru import logger


# ── Fallback heuristique (utilisé UNIQUEMENT si ToUnicode absent) ─────────────
# Valeurs les plus courantes observées empiriquement sur PDFs scientifiques
_FALLBACK_CID_MAP: dict[int, str] = {
    1:   "~",   3:  "≥",   4:  "≤",   5:  "≠",
    6:   "±",   7:  "≥",   8:  "≤",   9:  "÷",
    10:  "∞",   11: "≈",   12: "°",   13: "′",
    14:  "″",   15: "±",   16: "−",
    17:  "α",   18: "β",   19: "γ",   20: "δ",
    21:  "λ",   22: "μ",   23: "π",   24: "σ",
    25:  "θ",   26: "Ω",   27: "Σ",   28: "Δ",
    176: "°",   177: "±",  181: "μ",  183: "·",
    215: "×",   247: "÷",
    8722: "−",  8734: "∞", 8804: "≤", 8805: "≥",
    8800: "≠",  8901: "·",
}

# Regex pour parser les lignes bfchar du CMap stream
# Formats : <0003> <2265>  ou  <03> <2265>
_BFCHAR_RE  = re.compile(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>")
# Format bfrange : <0020> <007E> <0020>
_BFRANGE_RE = re.compile(r"<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>")
# Regex CID dans le texte : (cid:3)
_CID_RE     = re.compile(r"\(cid:(\d+)\)")


def build_cid_map(doc: fitz.Document) -> dict[int, str]:
    """
    Construit la table CID→Unicode en lisant les ToUnicode de toutes les polices
    embarquées dans le document.

    Retourne un dict {cid_int: unicode_char}.
    Si une police n'a pas de ToUnicode, on ignore (fallback appliqué à normalize()).
    """
    cid_map: dict[int, str] = {}
    seen_xrefs: set[int] = set()

    for page in doc:
        for font_info in page.get_fonts(full=True):
            xref = font_info[0]
            if xref in seen_xrefs or xref == 0:
                continue
            seen_xrefs.add(xref)

            try:
                # Récupère le xref du stream ToUnicode
                to_unicode_ref = doc.xref_get_key(xref, "ToUnicode")
                if not to_unicode_ref or to_unicode_ref[0] == "null":
                    continue

                # to_unicode_ref est soit ("xref", "12 0 R") soit ("stream", ...)
                if to_unicode_ref[0] == "xref":
                    # Extrait le numéro de xref du stream
                    stream_xref = int(to_unicode_ref[1].split()[0])
                    cmap_stream = doc.xref_stream(stream_xref).decode("latin-1", errors="ignore")
                elif to_unicode_ref[0] == "stream":
                    cmap_stream = to_unicode_ref[1]
                else:
                    continue

                parsed = _parse_cmap_stream(cmap_stream)
                cid_map.update(parsed)
                if parsed:
                    logger.debug(f"  Font xref={xref} → {len(parsed)} mappings ToUnicode")

            except Exception as e:
                logger.debug(f"  Font xref={xref} ToUnicode failed: {e}")
                continue

    logger.info(f"CID map built: {len(cid_map)} entrées depuis ToUnicode embarqué")
    return cid_map


def _parse_cmap_stream(cmap: str) -> dict[int, str]:
    """
    Parse un stream CMap PostScript et extrait les mappings CID→Unicode.
    Gère les sections beginbfchar et beginbfrange.
    """
    result: dict[int, str] = {}

    # ── Section bfchar : <cid_hex> <unicode_hex> ─────────────────────────────
    in_bfchar = False
    for line in cmap.splitlines():
        line = line.strip()
        if "beginbfchar" in line:
            in_bfchar = True
            continue
        if "endbfchar" in line:
            in_bfchar = False
            continue
        if in_bfchar:
            m = _BFCHAR_RE.search(line)
            if m:
                cid     = int(m.group(1), 16)
                uni_hex = m.group(2)
                try:
                    # Peut être un codepoint simple ou une séquence
                    char = chr(int(uni_hex, 16))
                    result[cid] = char
                except (ValueError, OverflowError):
                    pass

    # ── Section bfrange : <start> <end> <unicode_start> ──────────────────────
    in_bfrange = False
    for line in cmap.splitlines():
        line = line.strip()
        if "beginbfrange" in line:
            in_bfrange = True
            continue
        if "endbfrange" in line:
            in_bfrange = False
            continue
        if in_bfrange:
            m = _BFRANGE_RE.search(line)
            if m:
                start_cid = int(m.group(1), 16)
                end_cid   = int(m.group(2), 16)
                start_uni = int(m.group(3), 16)
                for offset in range(end_cid - start_cid + 1):
                    try:
                        result[start_cid + offset] = chr(start_uni + offset)
                    except (ValueError, OverflowError):
                        pass

    return result


def normalize_cids(text: str, cid_map: dict[int, str]) -> str:
    """
    Remplace tous les (cid:X) dans le texte par leur vrai caractère Unicode.

    Ordre de résolution :
    1. Table ToUnicode embarquée (cid_map) — spécifique au PDF
    2. Table heuristique fallback — si ToUnicode absent pour ce CID
    3. Conservation du (cid:X) original — si inconnu partout
    """
    if not text or "cid" not in text:
        return text

    def replace(m: re.Match) -> str:
        cid_val = int(m.group(1))
        # 1. ToUnicode embarqué
        if cid_val in cid_map:
            return cid_map[cid_val]
        # 2. Fallback heuristique
        if cid_val in _FALLBACK_CID_MAP:
            return _FALLBACK_CID_MAP[cid_val]
        # 3. Inconnu → conserve
        return m.group(0)

    return _CID_RE.sub(replace, text)


def build_and_normalize(doc: fitz.Document, text: str) -> str:
    """Helper one-shot pour les tests."""
    cid_map = build_cid_map(doc)
    return normalize_cids(text, cid_map)