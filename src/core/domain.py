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
        """Calculates the physical width of the span."""
        return self.right - self.left

    @property
    def height(self) -> float:
        """Calculates the physical height of the span."""
        return self.bottom - self.top

    @property
    def x_center(self) -> float:
        """Returns the horizontal midpoint of the span."""
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        """Returns the vertical midpoint of the span."""
        return (self.top + self.bottom) / 2.0


@dataclass
class FitzLine:
    """
    Represents a line of text, containing one or more styled Spans.
    """
    spans: List[FitzSpan] = field(default_factory=list)
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0

    @property
    def text(self) -> str:
        """
        Reconstructs the raw line text by joining spans.
        Preserves space separation between inline spans.
        """
        return " ".join(s.text for s in self.spans if s.text.strip())

    @property
    def height(self) -> float:
        """Calculates the line height based on bounding boxes."""
        return self.bottom - self.top


@dataclass
class FitzBlock:
    """
    Represents a structured visual block (paragraph, heading, or caption).
    Handles layout logic, styling, and text properties for translation context.
    """
    block_id: int
    lines: List[FitzLine] = field(default_factory=list)
    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    
    # Layout and styling attributes
    column: int = 0             # 0 = full-width (1-col), 1 = left column, 2 = right column
    alignment: str = "left"     # "left", "center", "justify"
    bg_color: str = "white"     # Background color detected under this block
    line_height_ratio: float = 1.15
    page_number: int = 0
    
    # Translation lifecycle attributes
    skip_translation: bool = False
    translated_text: Optional[str] = None

    @property
    def width(self) -> float:
        """Returns the physical block width."""
        return self.right - self.left

    @property
    def height(self) -> float:
        """Returns the physical block height."""
        return self.bottom - self.top

    @property
    def x_center(self) -> float:
        """Returns the horizontal midpoint of the block."""
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        """Returns the vertical midpoint of the block."""
        return (self.top + self.bottom) / 2.0

    @property
    def text(self) -> str:
        """Reconstructs the full block text from all lines."""
        return " ".join(line.text for line in self.lines if line.text.strip())

    @property
    def first_line_text(self) -> str:
        """Retrieves text of the first line. Useful for heading checks."""
        return self.lines[0].text if self.lines else ""

    @property
    def last_line_text(self) -> str:
        """Retrieves text of the last line. Useful for cross-page hyphen checks."""
        return self.lines[-1].text if self.lines else ""

    @property
    def has_hyphen_end(self) -> bool:
        """Detects if the block text ends with a hyphen (indicates word split)."""
        clean_last = self.last_line_text.strip()
        return clean_last.endswith("-") if clean_last else False

    @property
    def ends_with_punctuation(self) -> bool:
        """Checks if the block ends with sentence-ending punctuation."""
        clean_text = self.text.strip()
        if not clean_text:
            return False
        return clean_text[-1] in {".", "!", "?", ":"}

    @property
    def fs_dominant(self) -> float:
        """Computes the dominant font size within this block."""
        if not self.lines:
            return 9.0
        sizes = [s.font_size for line in self.lines for s in line.spans]
        return max(sizes) if sizes else 9.0



@dataclass
class FitzTableBlock:
    """
    Represents a structured table extracted semantically.
    Contains the coordinate bounds and a 2D matrix of cell texts.
    """
    block_id: int
    left: float
    top: float
    right: float
    bottom: float
    page_number: int
    
    # 2D List representing [rows][columns] of raw cell texts
    cells_matrix: list[list[str]] = field(default_factory=list)
    
    # 2D List representing translated cell texts (populated after LLM translation)
    translated_cells_matrix: Optional[list[list[str]]] = None
    
    # Stores the raw or translated HTML string generated by Mammoth
    html_content: Optional[str] = None

    skip_translation: bool = False

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return self.bottom - self.top
    
    @property
    def x_center(self) -> float:
        """Returns the horizontal midpoint of the block."""
        return (self.left + self.right) / 2.0

    @property
    def y_center(self) -> float:
        """Returns the vertical midpoint of the block."""
        return (self.top + self.bottom) / 2.0
    
    # @property
    # def text(self) -> str:
    #     """
    #     Flattens and returns all cell texts combined as a single string.
    #     Ensures perfect compatibility with layout filters and HTML builders.
    #     """
    #     flat_texts = []
    #     for row in self.cells_matrix:
    #         for cell in row:
    #             clean_cell = str(cell).strip()
    #             if clean_cell:
    #                 flat_texts.append(clean_cell)
    #     return " ".join(flat_texts)

    @property
    def text(self) -> str:
        """
        Returns a simplified placeholder string to prevent indexer,
        layout analyzer, or translation chunker errors.
        """
        return "[Table Region]"
    
    @property
    def fs_dominant(self) -> float:
        return 9.0  # Standard font size for table cells
    

@dataclass
class FitzPath:
    """
    Represents vector elements (background fills, dividers) to overlay under text.
    """
    left: float
    top: float
    width: float
    height: float
    fill_color: Optional[str] = None      # Format: "rgb(r,g,b)" or None
    stroke_color: Optional[str] = None    # Format: "rgb(r,g,b)" or None
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