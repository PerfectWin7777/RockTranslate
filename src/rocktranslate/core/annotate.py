"""
RockTranslate — highlights written back into the PDF.

The reader's highlights (page + rectangles as fractions of the page shown by
PDF.js, color, note) become real /Highlight annotations in a copy of the PDF,
so they show in Acrobat, Edge, Zotero, Okular... The note of a highlight is
the annotation's comment. The source PDF is never modified.

    >>> write_highlights("paper.pdf", "paper_highlights.pdf", items)

Path: src/rocktranslate/core/annotate.py
Author: RockTranslate Contributors
License: MIT License
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Highlight
from pypdf.generic import ArrayObject, FloatObject, NameObject, TextStringObject

Fraction = Tuple[float, float, float, float]          # x, y, width, height in [0, 1], origin top-left


def rotate_fraction(rect: Sequence[float], degrees: int) -> Fraction:
    """A page-fraction rectangle seen after turning the page clockwise by `degrees` (0/90/180/270)."""
    x, y, w, h = (float(v) for v in rect)
    d = degrees % 360
    if d == 90:
        return (1 - y - h, x, h, w)
    if d == 180:
        return (1 - x - w, 1 - y - h, w, h)
    if d == 270:
        return (y, 1 - x - w, h, w)
    return (x, y, w, h)


def _color(value: str) -> str:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return value.lower() if len(value) == 6 and all(c in "0123456789abcdefABCDEF" for c in value) else "ffe066"


def _quads(page: Any, rects: Iterable[Sequence[float]]) -> Tuple[List[float], Tuple[float, float, float, float]]:
    """PDF quad points (x1 y1 x2 y2 x3 y3 x4 y4 per rectangle) and their bounding box, in user space."""
    box = page.cropbox
    left, bottom, right, top = float(box.left), float(box.bottom), float(box.right), float(box.top)
    width, height = right - left, top - bottom
    rotation = int(page.get("/Rotate", 0) or 0) % 360
    quads: List[float] = []
    xs: List[float] = []
    ys: List[float] = []
    for rect in rects:
        # PDF.js shows the page turned by /Rotate: undo it to get unrotated fractions
        x, y, w, h = rotate_fraction(rect, -rotation)
        x0, x1 = left + x * width, left + (x + w) * width
        y_top, y_bottom = top - y * height, top - (y + h) * height
        quads += [x0, y_top, x1, y_top, x0, y_bottom, x1, y_bottom]
        xs += [x0, x1]
        ys += [y_top, y_bottom]
    return quads, (min(xs), min(ys), max(xs), max(ys))


def write_highlights(pdf_in: str, pdf_out: str, highlights: Iterable[Dict[str, Any]],
                     password: Optional[str] = None, author: str = "RockTranslate") -> int:
    """
    Copies `pdf_in` to `pdf_out` with one /Highlight annotation per highlight.
    Highlights: {page (1-based), rects [[x, y, w, h], ...], color '#rrggbb', note, text}.
    Returns the number of annotations written.
    """
    reader = PdfReader(pdf_in)
    if reader.is_encrypted:
        reader.decrypt(password or "")
    writer = PdfWriter(clone_from=reader)
    count = 0
    for item in highlights:
        page_no = int(item.get("page") or 0)
        rects = [r for r in (item.get("rects") or []) if len(r) == 4 and r[2] > 0 and r[3] > 0]
        if not (1 <= page_no <= len(writer.pages)) or not rects:
            continue
        page = writer.pages[page_no - 1]
        quads, rect = _quads(page, rects)
        annotation = Highlight(rect=rect, quad_points=ArrayObject(FloatObject(v) for v in quads),
                               highlight_color=_color(item.get("color", "")))
        note = str(item.get("note") or "").strip()
        if note:
            annotation[NameObject("/Contents")] = TextStringObject(note)
        annotation[NameObject("/T")] = TextStringObject(author)
        writer.add_annotation(page_number=page_no - 1, annotation=annotation)
        count += 1
    with open(pdf_out, "wb") as f:
        writer.write(f)
    return count
