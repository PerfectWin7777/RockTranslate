"""
RockTranslate — Figures of a structured document, as images
Path: src/rocktranslate/core/figures.py

Figures are rarely one embedded picture: curves, diagrams and LaTeX plots are
vector drawings. So every figure is located from its caption and rendered
from the page itself:

- the figure lies between the caption ("Figure 3: ...") and the closest text
  block above it in the same column (or below the caption when nothing fits
  above), across the column, or the whole text width for a wide caption;
- labels drawn inside the figure (FigureText) belong to it;
- the regions are rendered as PNG by a headless browser from the pdf2htmlEX
  page (the original look, embedded pictures and vector drawings alike), in
  one session for the whole document.

Each figure becomes an Image element placed next to its caption.

Author: RockTranslate Contributors
License: MIT License
"""

import re
from typing import Dict, List, Optional, Tuple

from loguru import logger

from ..document import (FIGURE_CAPTION, FIGURE_TEXT, FOOTER, HEADER, IMAGE, Document, Element,
                        make_element_id, strip_markup)

MIN_HEIGHT_PT = 30.0       # smaller "figures" are rules or stray symbols
MARGIN_PT = 3.0

Box = Tuple[float, float, float, float]


def _alt_text(caption: str) -> str:
    """'Figure 3: Training loss...' -> 'Figure 3'."""
    text = strip_markup(caption).strip()
    m = re.match(r"^((?:Figure|Fig\.?|Figura|Abbildung|Image|Photo|Plate|Chart|Graph)\s*[A-Z]?\d+[a-z]?)", text, re.I)
    return m.group(1) if m else text[:60]


def locate_figures(doc: Document) -> List[Tuple[int, int, Box, bool]]:
    """
    Figure regions of the document: (caption index, page, box in PDF points
    from the top-left, above_caption).
    """
    by_page: Dict[int, List[Tuple[int, Element]]] = {}
    for i, e in enumerate(doc.elements):
        by_page.setdefault(e.page, []).append((i, e))
    out = []
    for i, cap in enumerate(doc.elements):
        if cap.type != FIGURE_CAPTION:
            continue
        page_w, page_h = doc.page_sizes.get(cap.page, (0.0, 0.0))
        if not page_w:
            continue
        others = [e for _, e in by_page.get(cap.page, []) if e is not cap]
        text_blocks = [e for e in others if e.type not in (FIGURE_TEXT, IMAGE)]
        body = [e for e in text_blocks if e.type not in (HEADER, FOOTER)]
        cx0, _, cx1, _ = cap.bbox
        # Column of the caption: full text width for a wide caption
        if body and (cx1 - cx0) > 0.5 * page_w:
            cx0, cx1 = min(e.bbox[0] for e in body), max(e.bbox[2] for e in body)
        else:
            center = (cx0 + cx1) / 2
            column = [e for e in body if e.bbox[0] <= center <= e.bbox[2]]
            if column:
                cx0, cx1 = min(cx0, min(e.bbox[0] for e in column)), max(cx1, max(e.bbox[2] for e in column))

        def overlaps(e: Element) -> bool:
            return min(cx1, e.bbox[2]) - max(cx0, e.bbox[0]) > 0.25 * min(cx1 - cx0, e.bbox[2] - e.bbox[0])

        candidates = []   # (area, region, is_above)

        # Above the caption (usual for figures)
        above = [e.bbox[3] for e in text_blocks if overlaps(e) and e.bbox[3] <= cap.bbox[1] + 1]
        top = (max(above) if above else 0.0) + MARGIN_PT
        bottom = cap.bbox[1] - MARGIN_PT
        if bottom - top >= MIN_HEIGHT_PT:
            candidates.append(((bottom - top) * (cx1 - cx0), (cx0, top, cx1, bottom), True))
        # Below the caption (captions placed on top of their figure)
        below = [e.bbox[1] for e in text_blocks if overlaps(e) and e.bbox[1] >= cap.bbox[3] - 1]
        top2, bottom2 = cap.bbox[3] + MARGIN_PT, (min(below) if below else page_h) - MARGIN_PT
        if bottom2 - top2 >= MIN_HEIGHT_PT and not candidates:
            candidates.append(((bottom2 - top2) * (cx1 - cx0), (cx0, top2, cx1, bottom2), False))
        # Beside a narrow caption (side captions of journals: figure on the right)
        if body and (cap.bbox[2] - cap.bbox[0]) < 0.45 * page_w:
            sx0, sx1 = cap.bbox[2] + 3 * MARGIN_PT, max(e.bbox[2] for e in body)
            if sx1 - sx0 > 0.3 * page_w:
                def in_side(e: Element) -> bool:
                    return min(sx1, e.bbox[2]) - max(sx0, e.bbox[0]) > 0.25 * (e.bbox[2] - e.bbox[0])
                ups = [e.bbox[3] for e in text_blocks if in_side(e) and e.bbox[3] <= cap.bbox[1] + 1]
                downs = [e.bbox[1] for e in text_blocks if in_side(e) and e.bbox[1] >= cap.bbox[1] - 1]
                sy0 = (max(ups) if ups else 0.0) + MARGIN_PT
                sy1 = (min(downs) if downs else page_h) - MARGIN_PT
                if sy1 - sy0 >= MIN_HEIGHT_PT:
                    candidates.append(((sy1 - sy0) * (sx1 - sx0), (sx0, sy0, sx1, sy1), True))
        if not candidates:
            continue
        # The largest text-free area is the figure
        _, region, is_above = max(candidates, key=lambda c: c[0])
        # Labels drawn in the figure may stick out of the column: include them
        x0, y0, x1, y1 = region
        for e in others:
            if e.type == FIGURE_TEXT and e.bbox[1] >= y0 - 2 and e.bbox[3] <= y1 + 2:
                x0, x1 = min(x0, e.bbox[0]), max(x1, e.bbox[2])
        x0, y0 = max(0.0, x0 - MARGIN_PT), max(0.0, y0)
        x1, y1 = min(page_w, x1 + MARGIN_PT), min(page_h, y1)
        out.append((i, cap.page, (round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)), is_above))
    return out


def attach_figure_images(doc: Document, raw_html: str, page_offset: int = 0,
                         browser: Optional[str] = None, scale: float = 2.0) -> int:
    """
    Adds an Image element (PNG) for every captioned figure of `doc`, rendered
    from the pdf2htmlEX page `raw_html`. `page_offset`: document page number
    of the first converted page minus 1. Returns the number of images added.
    """
    regions = locate_figures(doc)
    if not regions:
        return 0
    from .cdp import screenshot_regions
    if browser is None:
        from .renderer import resolve_pdf_renderer
        browser = resolve_pdf_renderer()
    if not browser:
        logger.warning("No browser available: figures are not rendered as images.")
        return 0
    shots = screenshot_regions(browser, raw_html, [
        (page - page_offset - 1, box, doc.page_sizes[page]) for _, page, box, _ in regions], scale=scale)
    if not shots:
        return 0
    added = 0
    # Insert from the end so the caption indexes stay valid
    for (cap_index, page, box, is_above), png in sorted(zip(regions, shots), key=lambda r: -r[0][0]):
        if not png:
            continue
        cap = doc.elements[cap_index]
        image = Element(type=IMAGE, text=_alt_text(cap.text), page=page, bbox=box, parent_id=cap.parent_id,
                        element_id=make_element_id(doc.filename, page, cap_index, "image:" + cap.text[:40]),
                        image_png=png)
        doc.elements.insert(cap_index if is_above else cap_index + 1, image)
        added += 1
    logger.info(f"Figures rendered as images: {added}")
    return added
