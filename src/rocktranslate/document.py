"""
RockTranslate — Structured document model
Path: src/rocktranslate/document.py

A PDF becomes a list of typed *elements* (the schema popularized by
Unstructured: Title, NarrativeText, ListItem, Table, FigureCaption, Header,
Footer, Formula...), each with its page, its exact position in PDF points and
its parent section. RockTranslate adds what layout-only extractors do not
have: every element can carry its translation, aligned paragraph by paragraph.

    >>> import rocktranslate
    >>> doc = rocktranslate.extract("paper.pdf")
    >>> doc.to_markdown()                     # clean Markdown (headings, tables)
    >>> doc.to_json("paper.json")             # Unstructured-compatible elements
    >>> for chunk in doc.chunks(1500): ...    # section-aware chunks for RAG

License: MIT License
"""

import hashlib
import html as html_lib
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

# Element categories (Unstructured-compatible names)
TITLE = "Title"
SECTION = "Section"              # a heading inside the document (Unstructured: Title with depth)
NARRATIVE = "NarrativeText"
LIST_ITEM = "ListItem"
TABLE = "Table"
FIGURE_CAPTION = "FigureCaption"
TABLE_CAPTION = "TableCaption"
FORMULA = "Formula"
FOOTNOTE = "Footnote"
REFERENCE = "Reference"
HEADER = "Header"
FOOTER = "Footer"
UNCATEGORIZED = "UncategorizedText"
FIGURE_TEXT = "FigureText"       # labels drawn inside figures (axis ticks, rotated words)

# Categories left out of Markdown / chunks by default (page furniture, figure labels)
FURNITURE = {HEADER, FOOTER, FIGURE_TEXT}

# Unstructured's own names for a few of our categories (to_json(unstructured=True))
_UNSTRUCTURED_NAMES = {SECTION: "Title", TABLE_CAPTION: "FigureCaption", REFERENCE: "ListItem",
                       FOOTNOTE: "Footnote", FIGURE_TEXT: "UncategorizedText"}


@dataclass
class Element:
    """One block of the document: a heading, a paragraph, a table, a caption..."""

    type: str
    text: str
    page: int                                    # 1-based page number in the source PDF
    bbox: Tuple[float, float, float, float]      # x0, y0, x1, y1 in PDF points, origin top-left
    element_id: str = ""
    parent_id: Optional[str] = None              # enclosing section heading
    depth: int = 0                               # heading depth (0 = document title / top level)
    font_size: float = 0.0                       # in points
    html: str = ""                               # text with inline markup (<sup>, <sub>, tables)
    translation: Optional[str] = None            # filled by rocktranslate.translate()
    translation_html: Optional[str] = None
    table: Optional[List[List[str]]] = None      # rows x cells, for Table elements
    table_translation: Optional[List[List[str]]] = None
    segment_ids: List[str] = field(default_factory=list)   # internal ids (translation mapping)

    def to_dict(self, unstructured: bool = False) -> Dict[str, Any]:
        """Element as a dict; `unstructured=True` uses Unstructured's exact field layout."""
        x0, y0, x1, y1 = self.bbox
        metadata: Dict[str, Any] = {
            "page_number": self.page,
            "coordinates": {
                # Same layout as Unstructured: 4 corner points, then the system
                "points": [[x0, y0], [x0, y1], [x1, y1], [x1, y0]],
                "system": "PDFPoints",
                "origin": "top-left",
            },
            "parent_id": self.parent_id,
        }
        if self.type in (TITLE, SECTION):
            metadata["category_depth"] = self.depth
        if self.font_size:
            metadata["font_size"] = round(self.font_size, 2)
        if self.html and self.html != self.text:
            metadata["text_as_html"] = self.html
        if self.translation is not None:
            metadata["translation"] = self.translation
            if self.translation_html and self.translation_html != self.translation:
                metadata["translation_as_html"] = self.translation_html
        if self.table_translation is not None:
            metadata["table_translation"] = self.table_translation
        category = _UNSTRUCTURED_NAMES.get(self.type, self.type) if unstructured else self.type
        return {"type": category, "element_id": self.element_id, "text": self.text, "metadata": metadata}


@dataclass
class Chunk:
    """A retrieval-ready piece of text: whole elements of one section, size-bounded."""

    text: str
    section: str
    pages: List[int]
    element_ids: List[str]
    boxes: List[Tuple[int, Tuple[float, float, float, float]]]   # (page, bbox) per element
    translation: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Document:
    """The structured view of a PDF (optionally translated)."""

    def __init__(self, elements: List[Element], filename: str, page_sizes: Dict[int, Tuple[float, float]],
                 target_language: Optional[str] = None) -> None:
        self.elements = elements
        self.filename = filename
        self.page_sizes = page_sizes                 # page -> (width, height) in points
        self.target_language = target_language
        self.report = None              # TranslationReport, set by rocktranslate.translate()
        self.output_pdf: Optional[str] = None
        self.side_by_side_pdf: Optional[str] = None

    # ── Navigation ──────────────────────────────────────────────────────────
    def __iter__(self) -> Iterator[Element]:
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    def __repr__(self) -> str:
        counts: Dict[str, int] = {}
        for e in self.elements:
            counts[e.type] = counts.get(e.type, 0) + 1
        summary = ", ".join(f"{n} {t}" for t, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        return f"<Document {self.filename!r}: {len(self.elements)} elements ({summary})>"

    @property
    def title(self) -> Optional[str]:
        return next((e.text for e in self.elements if e.type == TITLE), None)

    def by_type(self, *types: str) -> List[Element]:
        return [e for e in self.elements if e.type in types]

    @property
    def tables(self) -> List[Element]:
        return self.by_type(TABLE)

    def sections(self) -> List[Tuple[Element, List[Element]]]:
        """(heading, its content) pairs in reading order."""
        result: List[Tuple[Element, List[Element]]] = []
        current: Optional[Tuple[Element, List[Element]]] = None
        for e in self.elements:
            if e.type in (TITLE, SECTION):
                current = (e, [])
                result.append(current)
            elif current is not None and e.type not in FURNITURE:
                current[1].append(e)
        return result

    def toc(self) -> List[Dict[str, Any]]:
        """
        Table of contents built from the detected headings (also for PDFs that
        have no bookmarks): [{"title", "depth", "page"}] in reading order.
        """
        return [{"title": e.text, "depth": e.depth, "page": e.page}
                for e in self.elements if e.type in (TITLE, SECTION)]

    def section_text(self, heading: str, translated: bool = False) -> Optional[str]:
        """
        Text of the section whose heading starts with (or contains) `heading`
        ("3.2", "Results"), sub-sections included. None if not found.
        """
        wanted = heading.strip().lower()
        elements = self.elements
        start = next((i for i, e in enumerate(elements) if e.type == SECTION
                      and strip_markup(e.text).lower().startswith(wanted)), None)
        if start is None:
            start = next((i for i, e in enumerate(elements) if e.type == SECTION
                          and wanted in strip_markup(e.text).lower()), None)
        if start is None:
            return None
        depth = elements[start].depth
        parts = [strip_markup(_pick(elements[start], translated))]
        for e in elements[start + 1:]:
            if e.type in (TITLE, SECTION) and e.depth <= depth:
                break
            if e.type not in FURNITURE:
                parts.append(strip_markup(_pick(e, translated)))
        return "\n\n".join(p for p in parts if p)

    # ── Exports ────────────────────────────────────────────────────────────
    def to_dicts(self, unstructured: bool = False) -> List[Dict[str, Any]]:
        return [e.to_dict(unstructured) for e in self.elements]

    def to_json(self, path: Optional[str] = None, unstructured: bool = False, indent: int = 2) -> str:
        """Elements as JSON (written to `path` when given). Returns the JSON text."""
        payload = json.dumps(self.to_dicts(unstructured), ensure_ascii=False, indent=indent)
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(payload)
        return payload

    def to_text(self, translated: bool = False) -> str:
        return "\n\n".join(_pick(e, translated) for e in self.elements if e.type not in FURNITURE)

    def to_markdown(self, path: Optional[str] = None, translated: bool = False, bilingual: bool = False,
                    page_markers: bool = False) -> str:
        """
        Clean Markdown: headings, paragraphs, lists, tables, captions, formulas.

        translated: write the translation instead of the original.
        bilingual:  original paragraph followed by its translation (quoted).
        page_markers: insert <!-- page N --> comments at page changes.
        """
        out: List[str] = []
        page = None
        for e in self.elements:
            if e.type in FURNITURE:
                continue
            if page_markers and e.page != page:
                out.append(f"<!-- page {e.page} -->")
                page = e.page
            out.append(_markdown_block(e, translated=translated and not bilingual))
            if bilingual and e.translation and e.type not in (TABLE, FORMULA) and not _same_text(e.text, e.translation):
                out.append("> " + _md_inline(e.translation_html or e.translation).replace("\n", "\n> "))
            elif bilingual and e.type == TABLE and e.table_translation:
                out.append(_markdown_table(e.table_translation))
        text = "\n\n".join(b for b in out if b.strip()) + "\n"
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        return text

    def search(self, query: str, in_translation: bool = True) -> List[Element]:
        """
        Elements whose original text (or translation) contains every word of
        `query`, case- and accent-insensitive. A query in either language
        finds the passage: search in French, get the English source.
        """
        words = [_fold(w) for w in query.split() if w.strip()]
        hits = []
        for e in self.elements:
            if e.type in FURNITURE:
                continue
            haystack = _fold(e.text) + " " + (_fold(e.translation) if in_translation and e.translation else "")
            if all(w in haystack for w in words):
                hits.append(e)
        return hits

    def highlight(self, elements: List[Element], source_pdf: str, output_pdf: str,
                  color: Tuple[float, float, float] = (1.0, 0.85, 0.0)) -> str:
        """
        Writes a copy of the ORIGINAL PDF where the given elements are framed
        and highlighted at their exact position: every answer, quote or RAG
        chunk can be shown in its source document.
        """
        from pypdf import PdfReader, PdfWriter
        from pypdf.annotations import Rectangle
        from pypdf.generic import ArrayObject, FloatObject, NameObject

        reader = PdfReader(source_pdf)
        writer = PdfWriter()
        writer.append(reader)
        for e in elements:
            index = e.page - 1
            if not 0 <= index < len(writer.pages):
                continue
            box = writer.pages[index].mediabox
            left, bottom, top = float(box.left), float(box.bottom), float(box.top)
            x0, y0, x1, y1 = e.bbox
            # Our boxes: points from the top-left corner; PDF: from the bottom-left
            rect = (left + x0 - 1, top - y1 - 1, left + x1 + 1, top - y0 + 1)
            if rect[1] < bottom:
                rect = (rect[0], bottom, rect[2], rect[3])
            annot = Rectangle(rect=rect, interior_color="ffd900")
            annot[NameObject("/C")] = ArrayObject([FloatObject(c) for c in color])
            annot[NameObject("/CA")] = FloatObject(0.35)
            writer.add_annotation(page_number=index, annotation=annot)
        with open(output_pdf, "wb") as f:
            writer.write(f)
        return output_pdf

    def chunks(self, max_characters: int = 1500, translated: bool = False) -> List[Chunk]:
        """
        Section-aware chunks for retrieval (like Unstructured's chunk_by_title):
        a chunk never mixes two sections, never cuts an element, and keeps the
        page + box of every element so a hit can be highlighted in the PDF.
        """
        chunks: List[Chunk] = []
        section = self.title or ""
        buf: List[Element] = []

        def flush() -> None:
            if not buf:
                return
            body = "\n\n".join(_pick(e, False) for e in buf)
            trans = None
            if any(e.translation for e in buf):
                trans = "\n\n".join(_pick(e, True) for e in buf)
            chunks.append(Chunk(text=body, section=section, pages=sorted({e.page for e in buf}),
                                element_ids=[e.element_id for e in buf],
                                boxes=[(e.page, e.bbox) for e in buf], translation=trans))
            buf.clear()

        size = 0
        for e in self.elements:
            if e.type in FURNITURE:
                continue
            if e.type in (TITLE, SECTION):
                flush()
                size = 0
                section = e.text
                continue
            text_len = len(_pick(e, translated))
            if buf and size + text_len > max_characters:
                flush()
                size = 0
            buf.append(e)
            size += text_len
        flush()
        return chunks


# ── Rendering helpers ──────────────────────────────────────────────────────

def _fold(text: str) -> str:
    """Lowercase without accents (search)."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _same_text(a: str, b: str) -> bool:
    norm = lambda t: re.sub(r"[\s\W_]+", "", t).lower()
    return norm(a) == norm(b)


def _pick(e: Element, translated: bool) -> str:
    if translated and e.translation:
        return e.translation
    return e.text


def _md_inline(html_text: str) -> str:
    """Inline markup to Markdown-compatible HTML (sup/sub kept, other tags dropped)."""
    text = re.sub(r"</?(?!sup\b|sub\b)[a-zA-Z_][^>]*>", "", html_text)
    return re.sub(r"\s+", " ", text).strip()


def _markdown_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[c.replace("|", "\\|").strip() for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


def _markdown_block(e: Element, translated: bool) -> str:
    text = _md_inline(e.translation_html or e.translation) if translated and e.translation else _md_inline(e.html or e.text)
    if e.type == TITLE:
        return f"# {text}"
    if e.type == SECTION:
        return f"{'#' * min(6, e.depth + 2)} {text}"
    if e.type == TABLE:
        rows = e.table_translation if translated and e.table_translation else e.table
        return _markdown_table(rows or [[text]])
    if e.type in (FIGURE_CAPTION, TABLE_CAPTION):
        return f"*{text}*"
    if e.type == FORMULA:
        return f"```\n{text}\n```"
    if e.type in (LIST_ITEM, REFERENCE):
        return f"- {text}"
    if e.type == FOOTNOTE:
        return f"> <small>{text}</small>"
    return text


def make_element_id(filename: str, page: int, index: int, text: str) -> str:
    """Stable id (same document -> same ids), Unstructured-style 32-hex digest."""
    return hashlib.sha256(f"{filename}|{page}|{index}|{text[:64]}".encode("utf-8")).hexdigest()[:32]


def strip_markup(text: str) -> str:
    """Internal segment markup (<color_X>, <sup>...) to plain text."""
    text = re.sub(r"<sup>(.*?)</sup>", r"\1", text)
    text = re.sub(r"</?[a-zA-Z_][a-zA-Z0-9_]*>", "", text)
    return html_lib.unescape(re.sub(r"\s+", " ", text)).strip()


def inline_html(text: str) -> str:
    """Internal segment markup to HTML: <sup>/<sub> kept, color runs dropped."""
    text = re.sub(r"</?color_[0-9a-fA-F]{6}>", "", text)
    return re.sub(r"\s+", " ", text).strip()
