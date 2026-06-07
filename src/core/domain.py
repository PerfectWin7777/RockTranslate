# src/core/domain.py

import re
from dataclasses import dataclass, field
from typing import List, Optional, Union


@dataclass
class FitzSpan:
    """
    Represents a single styled text fragment.
    Maps directly to a PyMuPDF span dictionary.
    """
    text: str
    left: float
    top: float
    right: float
    bottom: float
    font_name: str
    font_size: float
    color: str             # Format: "rgb(r, g, b)"
    is_bold: bool = False
    is_italic: bool = False
    is_sup: bool = False   # Superscript/subscript flag

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class FitzLine:
    """
    Represents a line of text, containing one or more styled Spans.
    Now enriched with layout, translation, and grouping fields
    to serve as the primary rendering unit.
    """
    spans: List[FitzSpan] = field(default_factory=list)
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    # ── Nouveaux champs (nouvelle approche ligne par ligne) ───────────────────
    layout: str = "one_col"               # "one_col" ou "two_col"
    translated_text: Optional[str] = None # Texte traduit final (rendu HTML)
    styled_text: Optional[str] = None     # Texte balisé envoyé au LLM (<b>, <i>, <color_HEX>…)
    block_id: int = 0                     # Identifiant du bloc sémantique auquel appartient la ligne

    @property
    def text(self) -> str:
        """
        Reconstructs the raw line text by joining spans.
        Preserves space separation between inline spans.
        """
        raw = " ".join(s.text for s in self.spans if s.text.strip())
        return re.sub(r'\s+', ' ', raw).strip()

    @property
    def height(self) -> float:
        return self.bottom - self.top
    
    @property
    def width(self) -> float:
        return self.right - self.left


@dataclass
class FitzBlock:
    """
    Represents a structured visual block (paragraph, heading, or caption).
    Kept for compatibility — no longer the primary rendering unit.
    """
    block_id: int
    lines: List[FitzLine] = field(default_factory=list)
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    column: int = 0
    alignment: str = "left"
    bg_color: str = "white"
    line_height_ratio: float = 1.15
    page_number: int = 0

    skip_translation: bool = False
    translated_text: Optional[str] = None
    styled_text: Optional[str] = None

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines if line.text.strip())

    @property
    def first_line_text(self) -> str:
        return self.lines[0].text if self.lines else ""

    @property
    def last_line_text(self) -> str:
        return self.lines[-1].text if self.lines else ""

    @property
    def has_hyphen_end(self) -> bool:
        clean_last = self.last_line_text.strip()
        return clean_last.endswith("-") if clean_last else False

    @property
    def ends_with_punctuation(self) -> bool:
        clean_text = self.text.strip()
        if not clean_text:
            return False
        return clean_text[-1] in {".", "!", "?", ":"}

    @property
    def fs_dominant(self) -> float:
        if not self.lines:
            return 9.0
        sizes = [s.font_size for line in self.lines for s in line.spans]
        if not sizes:
            return 9.0
        return sorted(sizes)[len(sizes) // 2]


@dataclass
class FitzTableBlock:
    """
    Represents a table zone.
    """
    block_id: int
    left: float
    top: float
    right: float
    bottom: float
    page_number: int
    skip_translation: bool = False
    translated_text: Optional[str] = None
    bg_color: str = "white"
    words: list = field(default_factory=list)
    translated_cells: dict = field(default_factory=dict)

    col_boundaries: list = field(default_factory=list)
    cells: list[list[dict]] = field(default_factory=list)

    def get_cells(self) -> list[list[dict]]:
        return self.cells

    @property
    def text(self) -> str:
        cells = self.get_cells()
        phrases = [" ".join(w["text"] for w in cell if w.get("text")) for cell in cells]
        return " | ".join(p for p in phrases if p.strip())

    @property
    def width(self): return self.right - self.left
    @property
    def height(self): return self.bottom - self.top
    @property
    def x_center(self): return (self.left + self.right) / 2.0
    @property
    def y_center(self): return (self.top + self.bottom) / 2.0
    @property
    def fs_dominant(self): return 8.5


@dataclass
class FitzPath:
    """
    Represents vector elements (background fills, dividers).
    """
    left: float
    top: float
    width: float
    height: float
    fill_color: Optional[str] = None
    stroke_color: Optional[str] = None
    stroke_width: float = 0.0


@dataclass
class FitzPage:
    """
    Holds layout data, vector paths, and the base64 background image of a page.
    """
    number: int
    width: float
    height: float
    blocks: list[Union[FitzBlock, FitzTableBlock]] = field(default_factory=list)
    paths: List[FitzPath] = field(default_factory=list)
    png_b64: Optional[str] = None


@dataclass
class FitzDocument:
    """
    The main entry point holding all parsed pages.
    """
    path: str
    pages: List[FitzPage] = field(default_factory=list)