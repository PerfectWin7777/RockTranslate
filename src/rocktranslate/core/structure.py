"""
RockTranslate — Layout -> structured elements
Path: src/rocktranslate/core/structure.py

Turns the instrumented pdf2htmlEX workspace (the same one the translator
uses: paragraphs regrouped, table cells split, superscripts attached) into
typed elements. Positions come from pdf2htmlEX's own CSS (left/bottom/height
of every text line, exact), widths from the measured geometry when a browser
is available, otherwise from a font-size estimate.

Classification is geometric and typographic, never document-specific:
font size relative to the body text, numbering patterns, position on the
page, repetition across pages, line structure (cells), and the section the
element belongs to.

License: MIT License
"""

import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup
from loguru import logger

from ..document import (FIGURE_CAPTION, FIGURE_TEXT, FOOTER, FOOTNOTE, FORMULA, HEADER, LIST_ITEM, NARRATIVE, REFERENCE,
                        SECTION, TABLE, TABLE_CAPTION, TITLE, UNCATEGORIZED, Document, Element, inline_html,
                        make_element_id, strip_markup)
from .chunker import should_translate

# pdf2htmlEX converts at --zoom 1.3: CSS pixels / 1.3 = PDF points
PX_PER_PT = 1.3

_CSS_RULE = re.compile(r"\.(x|y|h|w|fs)([0-9a-f]+)\{(?:left|bottom|height|width|font-size):(-?[\d.]+)px;\}")
_NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVXLC]+\.|[A-Z]\.)\s+\S")
_CAPTION = re.compile(r"^(?:Fig(?:ure)?s?\.?|Table|Tab\.|Scheme|Plate|Chart)\s*[A-Z0-9IVX]+[.:\-–— ]", re.I)
_TABLE_CAPTION = re.compile(r"^(?:Table|Tab\.)\s*[A-Z0-9IVX]+", re.I)
_LIST_ITEM = re.compile(r"^(?:[•▪◦‣∙●○■□–—-]\s+|\(?[a-z0-9]{1,3}\)\s+|\[\d+\]\s*)")
_REFERENCES_HEADING = re.compile(r"^(?:\d+\.?\s*)?(references|bibliography|literature cited|works cited|"
                                 r"références|bibliographie|literatur|referencias)\b", re.I)
_KNOWN_HEADINGS = re.compile(r"^(?:abstract|résumé|resumen|zusammenfassung|introduction|conclusions?|"
                             r"acknowledge?ments?|keywords?|highlights|methods?|results?|discussion|"
                             r"materials? and methods|appendix|supplementary material|declaration of .*|"
                             r"data availability|funding|credit authorship .*|article info)\b[\s:.]*$", re.I)


def _css_values(soup: BeautifulSoup) -> Dict[str, float]:
    """'x1' -> 241.2 ... from pdf2htmlEX's screen CSS (the first definition wins:
    the later @media print block repeats the classes in points)."""
    values: Dict[str, float] = {}
    for style in soup.find_all("style"):
        for kind, ident, value in _CSS_RULE.findall(style.get_text()):
            values.setdefault(f"{kind}{ident}", float(value))
    return values


class _Line:
    """One pdf2htmlEX text line (div.t) and the segments it carries."""
    __slots__ = ("page", "index", "left", "bottom", "height", "font", "width", "segments", "page_h")

    def __init__(self, page: int, index: int, left: float, bottom: float, height: float, font: float,
                 width: float, segments: List[str], page_h: float) -> None:
        self.page, self.index = page, index
        self.left, self.bottom, self.height, self.font = left, bottom, height, font
        self.width, self.segments, self.page_h = width, segments, page_h

    @property
    def top(self) -> float:
        return self.page_h - self.bottom - self.height


def build_document(workspace_html: str, original_texts: Dict[str, str], tid_to_page: Dict[str, int],
                   filename: str, page_offset: int = 0,
                   boxes: Optional[List[List[Tuple[float, float, float, float]]]] = None) -> Document:
    """
    Args:
        workspace_html: instrumented workspace written by instrument_html().
        original_texts / tid_to_page: segment maps returned by instrument_html().
        filename: source PDF name (element ids, metadata).
        page_offset: document page number of the first converted page minus 1
            (a conversion of pages 5-6 has page_offset 4).
        boxes: measured line boxes per page (geometry.measure_line_boxes), optional.
    """
    with open(workspace_html, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    css = _css_values(soup)

    # ── 1. Lines with their exact positions (CSS pixels) ──
    lines: List[_Line] = []
    page_sizes: Dict[int, Tuple[float, float]] = {}
    for p_idx, pf in enumerate(soup.select("div.pf")):
        classes = pf.get("class", [])
        width = next((css[c] for c in classes if re.fullmatch(r"w[0-9a-f]+", c) and c in css), 0.0)
        height = next((css[c] for c in classes if re.fullmatch(r"h[0-9a-f]+", c) and c in css), 0.0)
        page_no = p_idx + 1 + page_offset
        page_sizes[page_no] = (round(width / PX_PER_PT, 2), round(height / PX_PER_PT, 2))
        page_boxes = boxes[p_idx] if boxes and p_idx < len(boxes) else None
        divs = pf.select("div.t")
        if page_boxes is not None and len(page_boxes) != len(divs):
            page_boxes = None   # instrumentation changed the line count: estimates instead
        for d_idx, div in enumerate(divs):
            seg_ids: List[str] = []
            for span in div.select("span[data-trans-id]"):
                seg = span.get("data-para") or span.get("data-trans-id")
                if seg in original_texts and seg not in seg_ids:
                    seg_ids.append(seg)
            if not seg_ids:
                continue
            cls = div.get("class", [])
            val = lambda kind: next((css[c] for c in cls if re.fullmatch(kind + r"[0-9a-f]+", c) and c in css), 0.0)
            sy = 1.0
            first = div.select_one("span[data-sy]")
            if first is not None:
                try:
                    sy = abs(float(first.get("data-sy")))
                except ValueError:
                    sy = 1.0
            font = val("fs") * sy
            if page_boxes is not None:
                l, r, _t, _b = page_boxes[d_idx]
                w = r - l
            else:
                text_len = sum(len(strip_markup(original_texts[s])) for s in seg_ids)
                w = 0.5 * font * text_len
            lines.append(_Line(page_no, d_idx, val("x"), val("y"), val("h") or font, font, w, seg_ids, height))

    # ── 2. Segments: union of their line boxes, in reading (DOM) order ──
    seg_lines: Dict[str, List[_Line]] = defaultdict(list)
    order: List[str] = []
    for line in lines:
        for seg in line.segments:
            if seg not in seg_lines:
                order.append(seg)
            seg_lines[seg].append(line)

    # Body text size: the font size carrying the most characters
    size_weight: Counter = Counter()
    for seg in order:
        n = len(strip_markup(original_texts[seg]))
        for line in seg_lines[seg]:
            size_weight[round(line.font / PX_PER_PT, 1)] += n / max(1, len(seg_lines[seg]))
    body = size_weight.most_common(1)[0][0] if size_weight else 10.0

    # Repeated lines across pages (running headers/footers), digits normalized
    norm = lambda t: re.sub(r"\d+", "#", strip_markup(t)).strip().lower()
    repeated = Counter()
    for seg in order:
        repeated[norm(original_texts[seg])] += 1
    multi_page = len(page_sizes) > 1

    # ── 3. Rows of cells -> tables (lines that carry 2+ separate segments) ──
    table_of: Dict[str, int] = {}
    tables: List[List[_Line]] = []
    current: List[_Line] = []
    def is_table_row(line: _Line) -> bool:
        cells = [s for s in line.segments if not s.startswith("p-")]
        if len(cells) < 2:
            return False
        first = strip_markup(original_texts[cells[0]])
        if len(cells) == 2 and re.fullmatch(r"\d+(?:\.\d+)*\.?", first):
            return False        # "3.5" + "Positional Encoding": a numbered heading
        lengths = sorted(len(strip_markup(original_texts[c])) for c in cells)
        # Table cells are short; a sentence broken by an inline formula is not a row
        return lengths[len(lengths) // 2] <= 40

    for line in lines:
        is_row = is_table_row(line)
        if (is_row and current and line.page == current[-1].page
                and abs(current[-1].bottom - line.bottom) <= 2.5 * max(line.height, 1)):
            current.append(line)
        else:
            if len(current) >= 2:
                tables.append(current)
            current = [line] if is_row else []
    if len(current) >= 2:
        tables.append(current)
    # A header row separated by a slightly larger gap belongs to the table below
    merged: List[List[_Line]] = []
    for t in tables:
        prev = merged[-1] if merged else None
        if (prev and prev[-1].page == t[0].page
                and abs(prev[-1].bottom - t[0].bottom) <= 4.5 * max(t[0].height, 1)):
            prev.extend(t)
        else:
            merged.append(list(t))
    # A real table has several rows of several cells
    tables = [t for t in merged if len(t) >= 3 or sum(len(l.segments) for l in t) >= 6]
    for t_idx, rows in enumerate(tables):
        for line in rows:
            for seg in line.segments:
                if not seg.startswith("p-"):
                    table_of[seg] = t_idx

    # ── 4. Classify, then assemble elements in reading order ──
    elements: List[Element] = []
    emitted_tables = set()
    in_references = False
    title_done = False
    first_page = min(page_sizes) if page_sizes else 1
    for index, seg in enumerate(order):
        raw = original_texts[seg]
        text = strip_markup(raw)
        if not text:
            continue
        seg_ls = seg_lines[seg]
        page = seg_ls[0].page
        page_w_px, page_h_px = (page_sizes[page][0] * PX_PER_PT, page_sizes[page][1] * PX_PER_PT)
        x0 = min(l.left for l in seg_ls)
        x1 = max(l.left + l.width for l in seg_ls)
        y0 = min(l.top for l in seg_ls)
        y1 = max(l.top + l.height for l in seg_ls)
        bbox = tuple(round(v / PX_PER_PT, 2) for v in (x0, y0, x1, y1))
        size = round(max(l.font for l in seg_ls) / PX_PER_PT, 2)

        if seg in table_of:
            t_idx = table_of[seg]
            if t_idx in emitted_tables:
                continue
            emitted_tables.add(t_idx)
            elements.append(_table_element(tables[t_idx], original_texts, filename, index, page_sizes))
            continue

        kind = _classify(text, raw, seg, size, body, y0 / page_h_px if page_h_px else 0.5,
                         y1 / page_h_px if page_h_px else 0.5, len(seg_ls),
                         repeated[norm(raw)] >= 2 and multi_page, in_references,
                         page == first_page and not title_done)
        depth = 0
        if kind == TITLE:
            title_done = True
        elif kind == SECTION:
            m = re.match(r"^(\d+(?:\.\d+)*)", text)
            depth = (m.group(1).count(".") + 0) if m else 0
            in_references = bool(_REFERENCES_HEADING.match(text))
        elements.append(Element(type=kind, text=text, page=page, bbox=bbox, font_size=size,
                                html=inline_html(raw), segment_ids=[seg], depth=depth,
                                element_id=make_element_id(filename, page, index, text)))

    _merge_same_line(elements)
    _merge_continuations(elements)
    _group_display_math(elements)
    _merge_title_lines(elements)
    _mark_margin_text(elements, page_sizes)
    _demote_stacked_headings(elements)
    _set_heading_depths(elements)
    _title_first(elements)
    _link_parents(elements)
    logger.info(f"Structured {len(elements)} elements from {len(order)} segments "
                f"({len(tables)} tables, body text {body} pt).")
    return Document(elements, os.path.basename(filename), page_sizes)


def _classify(text: str, raw: str, seg: str, size: float, body: float, top_ratio: float, bottom_ratio: float,
              n_lines: int, repeated: bool, in_references: bool, title_candidate: bool) -> str:
    """Category of one segment, from typography and position only."""
    short = len(text) <= 160
    # Running headers / footers: page margins + repeated across pages (or a bare page number)
    if (top_ratio < 0.07 or bottom_ratio > 0.94) and short and (repeated or re.fullmatch(r"\d{1,4}", text)):
        return HEADER if top_ratio < 0.5 else FOOTER
    if _CAPTION.match(text):
        return TABLE_CAPTION if _TABLE_CAPTION.match(text) else FIGURE_CAPTION
    if not should_translate(text) and re.search(r"[=+\-×·∑∫√≤≥≈∂∇λμσπθαβγδ]", text):
        return FORMULA
    # Document title: clearly the largest text near the top of the first page
    # (a real title has several words: a big one-word journal name is not it)
    if (title_candidate and size >= 1.3 * body and top_ratio < 0.5 and len(text) <= 320
            and len(text.split()) >= 3):
        return TITLE
    if short and n_lines <= 3:
        bigger = size >= 1.12 * body
        # (numbered rows of a table use a smaller font than the body text)
        numbered = (bool(_NUMBERED_HEADING.match(text)) and len(text) < 120 and not text[-1:] in ".;,"
                    and size >= 0.95 * body and re.search(r"[A-Za-zÀ-ÿ]{3}", text) is not None)
        known = bool(_KNOWN_HEADINGS.match(text))
        words = len(text.split())
        wordy = re.search(r"[A-Za-zÀ-ÿ]{2}", text) is not None     # not a lone symbol / letter
        if wordy and ((bigger and words <= 14 and not text.endswith(".")) or (numbered and n_lines <= 2) or known):
            return SECTION
    if in_references:
        return REFERENCE
    if size < 0.85 * body and bottom_ratio > 0.75 and (len(text) >= 25 or re.match(r"^[∗*†‡§¶\d]", text)):
        return FOOTNOTE
    if _LIST_ITEM.match(text):
        return LIST_ITEM
    if len(text) < 4 or not re.search(r"[A-Za-zÀ-ÿ]{2}", text):
        return UNCATEGORIZED
    return NARRATIVE


def _overlap_ratio(a: Element, b: Element) -> float:
    """Vertical overlap of two boxes, relative to the smaller one."""
    inter = min(a.bbox[3], b.bbox[3]) - max(a.bbox[1], b.bbox[1])
    smaller = max(1e-6, min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1]))
    return inter / smaller


_BULLET = re.compile(r"^[•▪◦‣∙●○■□–—-]$")
_MARKER = re.compile(r"^(?:[∗*†‡§¶#,\s]+|[•▪◦‣∙●○■□]|\d{1,3}|[a-z]|[ivx]{1,4}|\[|\]|\d+(?:\.\d+)*\.?|[A-Za-z][a-z]{0,10}:)$")


def _merge_same_line(elements: List[Element]) -> None:
    """
    Pieces of ONE visual line that pdf2htmlEX emitted separately are joined:
    a section number and its title ("1" + "Introduction"), a name and its
    affiliation mark ("Vaswani" + "∗"), a footnote mark and its text, a
    citation cut around a bracket. Only when one side is a short marker, so
    real columns or table cells are never glued together.
    """
    i = 0
    while i < len(elements) - 1:
        a, b = elements[i], elements[i + 1]
        em = max(a.font_size, b.font_size, 1)
        same_line = (a.page == b.page and TABLE not in (a.type, b.type) and _overlap_ratio(a, b) >= 0.5
                     and b.bbox[0] >= a.bbox[0] - 1 and b.bbox[0] - a.bbox[2] < 3 * em)
        bullet = (_BULLET.match(a.text.strip()) is not None and a.page == b.page
                  and abs(b.bbox[1] - a.bbox[1]) < 1.2 * em and b.bbox[0] > a.bbox[0])
        if bullet:
            same_line = True
        footnote_mark = (a.type == FOOTNOTE and _MARKER.match(a.text) and a.page == b.page
                         and abs(b.bbox[1] - a.bbox[1]) < 1.5 * em and b.type != TABLE)
        inline_math = (same_line and FORMULA in (a.type, b.type) and b.bbox[0] - a.bbox[2] < 1.5 * em)
        if footnote_mark or inline_math or (same_line and (_MARKER.match(a.text) or _MARKER.match(b.text)
                                                           or b.text[:1] in ",.;:)]")):
            small_b = b.font_size and b.font_size < 0.85 * a.font_size
            glue = "" if (small_b or b.text[:1] in ",.;:)]" or a.text.endswith(("[", "("))) else " "
            a.html = a.html + (f"<sup>{b.html}</sup>" if small_b else glue + b.html)
            a.text = a.text + glue + b.text
            # Resulting type: the marker's role when it leads (footnote mark,
            # section number), otherwise the substantial part's type
            if _BULLET.match(a.text.strip()):
                a.type = LIST_ITEM
            elif footnote_mark:
                a.type = FOOTNOTE
            elif inline_math:
                a.type = NARRATIVE
            elif (_NUMBERED_HEADING.match(a.text) and len(a.text) < 90 and not a.text.endswith(".")
                  and b.type in (SECTION, NARRATIVE, UNCATEGORIZED) and len(b.text) < 80):
                a.type = SECTION          # "3.2" + "Attention"
            elif len(b.text) > len(a.text) / 2 and b.type not in (UNCATEGORIZED, FOOTNOTE):
                a.type = b.type
            elif a.type == UNCATEGORIZED:
                a.type = b.type
            a.bbox = (min(a.bbox[0], b.bbox[0]), min(a.bbox[1], b.bbox[1]),
                      max(a.bbox[2], b.bbox[2]), max(a.bbox[3], b.bbox[3]))
            a.font_size = max(a.font_size, b.font_size)
            a.segment_ids += b.segment_ids
            del elements[i + 1]
            continue
        i += 1


def _group_display_math(elements: List[Element]) -> None:
    """
    A displayed equation reaches us as scattered pieces (symbols, sub- and
    superscripts, the equation number): consecutive math-like pieces of one
    page that touch each other vertically become ONE Formula element.
    """
    def mathy(e: Element) -> bool:
        return e.type in (FORMULA, UNCATEGORIZED) or (e.type == FOOTNOTE and len(e.text) <= 12)

    i = 0
    while i < len(elements):
        a = elements[i]
        if not mathy(a):
            i += 1
            continue
        j = i + 1
        while j < len(elements):
            b = elements[j]
            em = max(a.font_size, b.font_size, 1)
            if not (mathy(b) and b.page == a.page and b.bbox[1] <= a.bbox[3] + 1.2 * em
                    and b.bbox[3] >= a.bbox[1] - 1.2 * em):
                break
            a.text = f"{a.text} {b.text}"
            a.html = f"{a.html} {b.html}"
            a.bbox = (min(a.bbox[0], b.bbox[0]), min(a.bbox[1], b.bbox[1]),
                      max(a.bbox[2], b.bbox[2]), max(a.bbox[3], b.bbox[3]))
            a.segment_ids += b.segment_ids
            a.type = FORMULA
            j += 1
        del elements[i + 1:j]
        if a.type == UNCATEGORIZED and re.search(r"[=+×·∑∫√≤≥≈∂∇]|\(\d+\)$", a.text):
            a.type = FORMULA
        i += 1


def _merge_continuations(elements: List[Element]) -> None:
    """A block cut in two (next part starts lowercase, same size, right below)."""
    i = 0
    while i < len(elements) - 1:
        a, b = elements[i], elements[i + 1]
        if (a.page == b.page and a.type in (NARRATIVE, SECTION) and b.type in (NARRATIVE, SECTION, UNCATEGORIZED)
                and b.text[:1].islower() and abs(a.font_size - b.font_size) < 0.6
                and a.bbox[1] < b.bbox[1] <= a.bbox[3] + 1.5 * a.font_size
                and not a.text.endswith((".", "!", "?", ":"))):
            a.text = f"{a.text} {b.text}"
            a.html = f"{a.html} {b.html}"
            a.type = NARRATIVE
            a.bbox = (min(a.bbox[0], b.bbox[0]), a.bbox[1], max(a.bbox[2], b.bbox[2]), b.bbox[3])
            a.segment_ids += b.segment_ids
            del elements[i + 1]
            continue
        i += 1


def _mark_margin_text(elements: List[Element], page_sizes: Dict[int, Tuple[float, float]]) -> None:
    """Rotated or margin-only text (arXiv stamps, line numbers) is page furniture."""
    for e in elements:
        width = page_sizes.get(e.page, (0, 0))[0]
        if not width:
            continue
        in_margin = e.bbox[2] < 0.12 * width or e.bbox[0] > 0.9 * width
        rotated = e.font_size == 0
        if (rotated or in_margin) and len(e.text) >= 20 and e.type in (NARRATIVE, UNCATEGORIZED, HEADER):
            e.type = HEADER           # arXiv stamp, journal margin line
        elif rotated:
            e.type = FIGURE_TEXT      # words drawn rotated inside a figure


def _demote_stacked_headings(elements: List[Element]) -> None:
    """
    Headings are followed by content, they do not stack: three or more
    'numbered headings' in a row, each right below the previous one, are the
    numbered rows of a list or table ("1 Basin area", "2 Basin shape"...).
    """
    i = 0
    while i < len(elements):
        j = i
        while (j + 1 < len(elements) and elements[j].type == SECTION and elements[j + 1].type == SECTION
               and elements[j + 1].page == elements[j].page
               and elements[j + 1].bbox[1] - elements[j].bbox[3] < 2.5 * max(elements[j].font_size, 1)):
            j += 1
        if elements[i].type == SECTION and j - i + 1 >= 3:
            for e in elements[i:j + 1]:
                e.type = LIST_ITEM
            i = j + 1
        else:
            i += 1


def _set_heading_depths(elements: List[Element]) -> None:
    """Depth from the numbering: '3' -> 0, '3.2' -> 1, '3.2.1' -> 2."""
    for e in elements:
        if e.type == SECTION:
            m = re.match(r"^(\d+(?:\.\d+)*)", e.text)
            e.depth = m.group(1).rstrip(".").count(".") if m else 0


def _table_element(rows: List["_Line"], texts: Dict[str, str], filename: str, index: int,
                   page_sizes: Dict[int, Tuple[float, float]]) -> Element:
    """A Table element from consecutive rows of cells (text, HTML, rows x cells)."""
    grid = [[strip_markup(texts[s]) for s in line.segments if not s.startswith("p-")] for line in rows]
    segs = [s for line in rows for s in line.segments if not s.startswith("p-")]
    page = rows[0].page
    x0 = min(l.left for l in rows) / PX_PER_PT
    x1 = max(l.left + l.width for l in rows) / PX_PER_PT
    y0 = min(l.top for l in rows) / PX_PER_PT
    y1 = max(l.top + l.height for l in rows) / PX_PER_PT
    html_rows = "".join("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>" for r in grid)
    text = "\n".join(" | ".join(r) for r in grid)
    return Element(type=TABLE, text=text, page=page, bbox=(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)),
                   html=f"<table>{html_rows}</table>", table=grid, segment_ids=segs,
                   font_size=round(rows[0].font / PX_PER_PT, 2),
                   element_id=make_element_id(filename, page, index, text))


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _merge_title_lines(elements: List[Element]) -> None:
    """A title spread over several segments (one per line) becomes one element."""
    i = 0
    while i < len(elements) - 1:
        a, b = elements[i], elements[i + 1]
        if a.type == TITLE and b.page == a.page and abs(b.font_size - a.font_size) < 0.5 and \
                b.type in (TITLE, SECTION, NARRATIVE) and b.bbox[1] - a.bbox[3] < 2 * a.font_size:
            a.text = f"{a.text} {b.text}"
            a.html = f"{a.html} {b.html}"
            a.bbox = (min(a.bbox[0], b.bbox[0]), a.bbox[1], max(a.bbox[2], b.bbox[2]), b.bbox[3])
            a.segment_ids += b.segment_ids
            del elements[i + 1]
            continue
        i += 1


def _title_first(elements: List[Element]) -> None:
    """The document title opens the element list (side columns may precede it)."""
    idx = next((i for i, e in enumerate(elements) if e.type == TITLE), None)
    if idx:
        title = elements.pop(idx)
        first_same_page = next((i for i, e in enumerate(elements) if e.page == title.page), 0)
        elements.insert(first_same_page, title)


def _link_parents(elements: List[Element]) -> None:
    """parent_id = the enclosing heading (a heading's parent: a shallower one)."""
    stack: List[Element] = []
    for e in elements:
        if e.type in (TITLE, SECTION):
            level = -1 if e.type == TITLE else e.depth
            while stack and (stack[-1].depth if stack[-1].type == SECTION else -1) >= level:
                stack.pop()
            e.parent_id = stack[-1].element_id if stack else None
            stack.append(e)
        else:
            e.parent_id = stack[-1].element_id if stack else None


def attach_translations(doc: Document, translations: Dict[str, str], original_texts: Dict[str, str],
                        target_language: str) -> None:
    """
    Fills every element's translation from the segment translations. Segments
    left untranslated on purpose (numbers, formulas, symbols) keep their
    original text, so an element's translation is always complete.
    """
    def seg_text(seg: str) -> str:
        return translations.get(seg) or original_texts.get(seg, "")

    for e in doc.elements:
        if e.type == TABLE and e.table:
            # Cells were collected row by row in segment order
            cells = iter(e.segment_ids)
            e.table_translation = [[strip_markup(seg_text(next(cells, ""))) for _ in row] for row in e.table]
            e.translation = "\n".join(" | ".join(r) for r in e.table_translation)
            continue
        parts = [seg_text(s) for s in e.segment_ids]
        if not any(s in translations for s in e.segment_ids):
            continue
        e.translation = strip_markup(" ".join(parts))
        e.translation_html = inline_html(" ".join(parts))
    doc.target_language = target_language
