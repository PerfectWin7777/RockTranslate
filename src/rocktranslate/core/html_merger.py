"""
RockTranslate — pdf2htmlEX Slice Merger (CSS-namespaced, fidelity-preserving)
Path: src/rocktranslate/core/html_merger.py

Merges several independently converted pdf2htmlEX slices (each a standalone
HTML document) into ONE document that is geometrically identical to what a
single whole-document conversion would produce.

Why namespacing is required
---------------------------
pdf2htmlEX reuses small class names across documents (.m3, .y6d, ._27, .ff1…)
but the VALUES behind those names depend on each document's content (matrices,
positions, font subsets). Concatenating two slices' CSS naively lets the last
definition win and silently misaligns the first slice. The merger therefore:

1. Renames every generated class token per slice (suffix "_s<k>") in BOTH the
   CSS rules and the body class attributes — consistency guaranteed because a
   single rename map drives both. The only exception is the shared page class
   "pf", whose definition is identical across slices of the same document.
2. Renames @font-face families the same way (font subsets differ per slice).
3. Prefixes every slice rule with its wrapper id (#rt-s<k>) so that even a
   hypothetical un-renamed leftover can never leak across slices. Global rules
   (body/html/@page/#page-container) are taken from the first slice only.
4. Renumbers page ids (#pf<hex>) and internal anchors (#pf<hex>) to GLOBAL
   page numbers so scroll-sync and links keep working on the merged document.

What is NEVER touched: transform matrices, spacer widths, positions, colors,
font sizes, text content, and the body DOM structure (only class/id attribute
tokens are rewritten). The base64 font payloads are copied verbatim.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from loguru import logger

# The one class pdf2htmlEX defines identically in every document of the same source
SHARED_CLASSES = {"pf"}

# Suffix builder per slice index
def _s(idx: int) -> str:
    return f"_s{idx}"


# ─────────────────────────────────────────────────────────────────────────────
# CSS transformation (tinycss2-based, token-exact)
#
# pdf2htmlEX's stylesheet mixes a license comment, top-level geometry rules,
# and the vast majority of values nested inside @media print blocks (plus a
# nested @-moz-document). Regex surgery on that structure is fragile, so the
# transformation operates on the token AST: class selectors are renamed token
# by token, font-family identifiers are renamed inside @font-face values, and
# structural @-rules are preserved verbatim.
# ─────────────────────────────────────────────────────────────────────────────
import tinycss2

_FF_TOKEN_RE = re.compile(r"ff[0-9a-zA-Z]+")

_GLOBAL_SELECTOR_RE = re.compile(r"^(html|body)[\s\.{,:#\[]", re.IGNORECASE)
_ID_SELECTOR_RE = re.compile(r"#([A-Za-z][A-Za-z0-9_-]*)")


def _rename_selector_tokens(tokens: List[Any], ns: "_SliceNamespace") -> List[Any]:
    """Returns selector prelude tokens where every .class identifier is
    replaced by its namespaced name. All other tokens pass through untouched."""
    out: List[Any] = []
    pending_dot = False
    for tok in tokens:
        if tok.type == "literal" and getattr(tok, "value", "") == ".":
            pending_dot = True
            out.append(tok)
            continue
        if pending_dot and tok.type == "ident":
            tok.value = ns.rename(tok.value)
            if hasattr(tok, "lower_value"):
                tok.lower_value = ns.rename(tok.value)
            pending_dot = False
            out.append(tok)
            continue
        pending_dot = False
        out.append(tok)
    return out


def _rename_font_refs_in_content(tokens: List[Any], ns: "_SliceNamespace") -> List[Any]:
    """Renames ff* identifiers inside font-family declaration values."""
    out = list(tokens)
    for node in out:
        if getattr(node, "type", "") == "decl" and node.lower_name == "font-family":
            for tok in node.value:
                if tok.type == "ident" and _FF_TOKEN_RE.fullmatch(tok.value or ""):
                    tok.value = ns.rename(tok.value)
                    if hasattr(tok, "lower_value"):
                        tok.lower_value = ns.rename(tok.value)
    return out


def _selector_text(rule: Any) -> str:
    try:
        return tinycss2.serialize(rule.prelude).strip()
    except Exception:
        return ""


def _transform_rules(rules: List[Any], ns: "_SliceNamespace", wrapper_id: str,
                     slice_css: List[str], global_css: List[str],
                     stats: Dict[str, int], depth: int = 0) -> None:
    for rule in rules:
        if rule.type == "error":
            continue

        if rule.type == "qualified-rule":
            sel = _selector_text(rule)
            id_match = _ID_SELECTOR_RE.search(sel)
            is_global = (_GLOBAL_SELECTOR_RE.search(sel) is not None
                         or (id_match is not None and id_match.group(1) == "page-container"))
            if is_global:
                if ns.idx == 0:
                    global_css.append(tinycss2.serialize([rule]))
                else:
                    stats["dropped"] += 1
                continue
            if _ID_SELECTOR_RE.search(sel):
                # sidebar/outline and other chrome ids: their elements are dropped
                stats["dropped"] += 1
                continue
            rule.prelude = _rename_selector_tokens(rule.prelude, ns)
            if rule.content is not None:
                rule.content = _rename_font_refs_in_content(rule.content, ns)
            slice_css.append(tinycss2.serialize([rule]))
            stats["rules"] += 1
            continue

        if rule.type != "at-rule":
            continue

        kw = rule.lower_at_keyword
        if kw == "font-face":
            if rule.content is not None:
                rule.content = _rename_font_refs_in_content(rule.content, ns)
            slice_css.append(tinycss2.serialize([rule]))
            stats["fontfaces"] += 1
        elif kw in ("keyframes", "-webkit-keyframes", "-moz-keyframes", "-o-keyframes"):
            # Identical animation definitions in every slice: keep once, verbatim
            if ns.idx == 0:
                global_css.append(tinycss2.serialize([rule]))
        elif kw == "page":
            # Same page geometry for every slice of the same document
            if ns.idx == 0:
                global_css.append(tinycss2.serialize([rule]))
        elif kw in ("media", "supports", "-moz-document"):
            if depth >= 4 or rule.content is None:
                continue
            nested = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
            inner: List[str] = []
            _transform_rules(nested, ns, wrapper_id, inner, global_css, stats, depth + 1)
            if inner:
                prelude = tinycss2.serialize(rule.prelude) or ""
                slice_css.append(f"@{rule.at_keyword}{prelude}{{{''.join(inner)}}}")
                stats["rules"] += 1
        else:
            # Unknown at-rule: keep it once, from the first slice, verbatim
            if ns.idx == 0:
                global_css.append(tinycss2.serialize([rule]))


def _transform_css(css_text: str, ns: "_SliceNamespace", wrapper_id: str,
                   slice_css: List[str], global_css: List[str],
                   stats: Dict[str, int]) -> None:
    rules = tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True)
    _transform_rules(rules, ns, wrapper_id, slice_css, global_css, stats)


class _SliceNamespace:
    """Rename map for one slice: class token / font family -> namespaced token."""

    def __init__(self, idx: int):
        self.idx = idx
        self.suffix = _s(idx)
        self._map: Dict[str, str] = {}

    def rename(self, token: str) -> str:
        if token in SHARED_CLASSES:
            return token
        mapped = self._map.get(token)
        if mapped is None:
            mapped = f"{token}{self.suffix}"
            self._map[token] = mapped
        return mapped

    @property
    def size(self) -> int:
        return len(self._map)


def _rewrite_body(soup: BeautifulSoup, ns: _SliceNamespace, page_offset: int,
                  wrapper_id: str) -> Tuple[Dict[str, int], List]:
    """
    Renames class tokens, renumbers page ids and anchors to global numbers,
    strips scripts and pdf2htmlEX chrome (sidebar/outline). Returns
    (stats, retained_page_nodes_in_document_order).
    """
    stats = {"pages": 0, "ids_renumbered": 0, "anchors_renumbered": 0, "elements_renamed": 0}

    page_container = soup.find(id="page-container")
    page_nodes = []
    if page_container is not None:
        page_nodes = [el for el in page_container.find_all(id=re.compile(r"^pf[0-9a-fA-F]+$"))]
    if not page_nodes:
        # Fallback: pages as direct body children (older layouts)
        page_nodes = [el for el in soup.body.find_all(id=re.compile(r"^pf[0-9a-fA-F]+$"))] if soup.body else []

    # Page-id numbering depends on how the slice was produced: converting a
    # page RANGE of the original file (-f/-l) yields ids numbered by the
    # SOURCE page (already global), while converting an extracted slice PDF
    # restarts at 1 and needs the offset shift. Auto-detect: local ids can
    # never exceed the slice's own page count.
    local_nums = []
    for el in page_nodes:
        try:
            local_nums.append(int(el.get("id")[2:], 16))
        except ValueError:
            pass
    already_global = bool(local_nums) and max(local_nums) > len(page_nodes)
    shift = 0 if already_global else page_offset

    for el in page_nodes:
        # Global page number: pdf2htmlEX ids are 1-based hex page numbers
        hex_part = el.get("id")[2:]
        try:
            local_page = int(hex_part, 16)
        except ValueError:
            logger.warning(f"Unparsable page id '{el.get('id')}' in slice {ns.idx}; skipped.")
            continue
        global_page = local_page + shift
        el["id"] = f"pf{global_page:x}"
        stats["ids_renumbered"] += 1
        stats["pages"] += 1

        # Rewrite anchors targeting pages inside this slice
        for a in el.find_all("a", href=re.compile(r"^#pf[0-9a-fA-F]+$")):
            target = a["href"][1:][2:]
            try:
                a["href"] = f"#pf{int(target, 16) + shift:x}"
                stats["anchors_renumbered"] += 1
            except ValueError:
                pass

    # Drop pdf2htmlEX chrome entirely (bookmark sidebar, outline tree, scripts)
    for chrome_id in ("sidebar", "outline"):
        chrome = soup.find(id=chrome_id)
        if chrome is not None:
            chrome.decompose()
    for script in soup.find_all("script"):
        script.decompose()

    # Rename class tokens on every element kept in the document
    for el in soup.find_all(class_=True):
        classes = el.get("class") or []
        el["class"] = [ns.rename(c) for c in classes]
        stats["elements_renamed"] += 1

    # Mark the retained pages so the assembler can collect exactly them
    return stats, page_nodes


def _strip_suffix(token: str) -> str:
    return re.sub(r"_s\d+$", "", token)


def merge_pdf2htmlex_slices(slice_html_paths: List[str], page_offsets: List[int],
                            output_path: str) -> Dict[str, object]:
    """
    Merges independently converted pdf2htmlEX slice documents into one
    geometrically-faithful document.

    Args:
        slice_html_paths: Absolute paths to the raw slice HTML files, in page order.
        page_offsets: For each slice, the number of pages that precede it in the
            source document (e.g. a slice covering pages 11-20 has offset 10).
        output_path: Where the merged HTML document is written.

    Returns:
        Statistics dictionary (rules, renames, font-faces, pages, anchors…).
    """
    if len(slice_html_paths) != len(page_offsets):
        raise ValueError("slice_html_paths and page_offsets must have the same length")

    global_css: List[str] = []
    total_stats: Dict[str, object] = {
        "slices": len(slice_html_paths),
        "pages": 0,
        "ids_renumbered": 0,
        "anchors_renumbered": 0,
        "elements_renamed": 0,
        "fontfaces": 0,
        "css_rules": 0,
        "dropped_rules": 0,
        "renamed_tokens": 0,
        "body_class": "",
    }

    page_wrappers: List[str] = []
    all_slice_css: List[str] = []

    for idx, (path, offset) in enumerate(zip(slice_html_paths, page_offsets)):
        wrapper_id = f"rt-s{idx}"
        ns = _SliceNamespace(idx)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "lxml")

        if idx == 0:
            body = soup.body
            if body is not None and body.get("class"):
                total_stats["body_class"] = " ".join(body.get("class"))

        # 1. CSS: transform every style block of this slice
        slice_stats: Dict[str, int] = {"fontfaces": 0, "rules": 0, "dropped": 0}
        slice_css: List[str] = []
        for style in soup.find_all("style"):
            css_text = style.string or style.get_text()
            if not css_text or not css_text.strip():
                continue
            _transform_css(css_text, ns, wrapper_id, slice_css, global_css, slice_stats)
        all_slice_css.extend(slice_css)
        total_stats["fontfaces"] = int(total_stats["fontfaces"]) + slice_stats["fontfaces"]
        total_stats["css_rules"] = int(total_stats["css_rules"]) + slice_stats["rules"]
        total_stats["dropped_rules"] = int(total_stats["dropped_rules"]) + slice_stats["dropped"]

        # 2. Body: rename tokens, renumber ids/anchors, drop chrome & scripts
        bstats, page_nodes = _rewrite_body(soup, ns, offset, wrapper_id)
        total_stats["pages"] = int(total_stats["pages"]) + bstats["pages"]
        total_stats["ids_renumbered"] = int(total_stats["ids_renumbered"]) + bstats["ids_renumbered"]
        total_stats["anchors_renumbered"] = int(total_stats["anchors_renumbered"]) + bstats["anchors_renumbered"]
        total_stats["elements_renamed"] = int(total_stats["elements_renamed"]) + bstats["elements_renamed"]
        total_stats["renamed_tokens"] = int(total_stats["renamed_tokens"]) + ns.size

        # 3. Collect this slice's pages wrapped in its namespace div
        inner = "".join(str(node.extract()) for node in page_nodes)
        page_wrappers.append(f'<div id="{wrapper_id}" class="rt-slice">{inner}</div>')

    # Duplicate pf ids would break scroll-sync: hard validation
    all_ids = re.findall(r'id="(pf[0-9a-f]+)"', "".join(page_wrappers))
    if len(all_ids) != len(set(all_ids)):
        duplicates = sorted({i for i in all_ids if all_ids.count(i) > 1})
        raise ValueError(f"Duplicate page ids after merge: {duplicates[:10]}")

    css_out = "\n".join(global_css + all_slice_css)
    merged = (
        "<!DOCTYPE html>\n<html>\n<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>Merged workspace</title>\n"
        f"<style>{css_out}</style>\n"
        "</head>\n"
        f'<body class="{total_stats["body_class"]}">\n'
        '<div id="page-container">\n'
        + "\n".join(page_wrappers) +
        '\n</div>\n</body>\n</html>\n'
    )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(merged)

    logger.info(
        f"Merged {len(slice_html_paths)} slices -> {output_path} "
        f"({total_stats['pages']} pages, {total_stats['css_rules']} rules, "
        f"{total_stats['fontfaces']} font-faces, {total_stats['renamed_tokens']} renamed tokens)"
    )
    return total_stats
