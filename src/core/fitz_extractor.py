# src/core/fitz_extractor.py

import base64
import fitz  # PyMuPDF
from typing import List, Tuple, Optional
from loguru import logger

from core.domain import (
    FitzSpan,
    FitzLine,
    FitzBlock,
    FitzPath,
    FitzPage,
    FitzDocument
)


class FitzExtractor:
    """
    Handles PDF data extraction using PyMuPDF (fitz).
    Converts PDF layout, text, and vector graphics into a structured FitzDocument.
    """

    def __init__(self, pdf_path: str, dpi: int = 150):
        """
        Args:
            pdf_path: Path to the target PDF file.
            dpi: Resolution for the page background PNG generation (150 is optimal for UI preview).
        """
        self.pdf_path = pdf_path
        self.dpi = dpi

    def extract_document(self) -> FitzDocument:
        """
        Parses the entire PDF and returns a structured FitzDocument.
        """
        logger.info(f"Opening document: {self.pdf_path}")
        doc = fitz.open(self.pdf_path)
        fitz_doc = FitzDocument(path=self.pdf_path)

        for page_num in range(len(doc)):
            page = doc[page_num]
            fitz_page = self._extract_page(page, page_num + 1)
            fitz_doc.pages.append(fitz_page)
            logger.info(f"Successfully extracted Page {page_num + 1}/{len(doc)}")

        doc.close()
        return fitz_doc

    def _extract_page(self, page: fitz.Page, page_number: int) -> FitzPage:
        """
        Extracts structural text blocks, vector paths, and the background image of a page.
        """
        page_w = page.rect.width
        page_h = page.rect.height

        # 1. Extract vector elements (Paths) first
        paths = self._extract_paths(page)

        # 2. Generate high-resolution background PNG
        png_b64 = self._generate_page_image_b64(page)

        # 3. Extract text blocks
        blocks = self._extract_text_blocks(page, page_number, paths)

        return FitzPage(
            number=page_number,
            width=page_w,
            height=page_h,
            blocks=blocks,
            paths=paths,
            png_b64=png_b64
        )

    def _extract_paths(self, page: fitz.Page) -> List[FitzPath]:
        """
        Extracts drawings (fills, rectangles, strokes) to map physical visual decorations.
        """
        paths: List[FitzPath] = []
        try:
            drawings = page.get_drawings()
        except Exception as e:
            logger.warning(f"Failed to get drawings for page {page.number + 1}: {e}")
            return paths

        for draw in drawings:
            rect = draw.get("rect")
            if not rect:
                continue

            x0, y0, x1, y1 = rect
            w, h = x1 - x0, y1 - y0

            # Ignore extremely small lines or artifacts
            if w < 2.0 and h < 2.0:
                continue

            fill = draw.get("fill")
            color = draw.get("color")
            stroke_width = draw.get("width", 1.0) or 1.0

            # Convert normalized 0.0-1.0 RGB tuples to "rgb(r,g,b)"
            fill_css = f"rgb({int(fill[0]*255)},{int(fill[1]*255)},{int(fill[2]*255)})" if fill else None
            stroke_css = f"rgb({int(color[0]*255)},{int(color[1]*255)},{int(color[2]*255)})" if color else None

            paths.append(FitzPath(
                left=x0,
                top=y0,
                width=w,
                height=h,
                fill_color=fill_css,
                stroke_color=stroke_css,
                stroke_width=stroke_width
            ))

        return paths

    def _generate_page_image_b64(self, page: fitz.Page) -> str:
        """
        Renders the page to a PNG and encodes it in base64.
        """
        zoom = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img_data = pix.tobytes("png")
        return base64.b64encode(img_data).decode("utf-8")

    def _extract_text_blocks(self, page: fitz.Page, page_number: int, paths: List[FitzPath]) -> List[FitzBlock]:
        """
        Extracts structural text layouts and maps background colors.
        """
        blocks: List[FitzBlock] = []
        
        # Extract rich dictionary layout from PyMuPDF
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        
        block_id_counter = 0

        for b_dict in text_dict.get("blocks", []):
            # Type 0 is text. Ignore images/drawings blocks here
            if b_dict.get("type") != 0:
                continue

            x0, y0, x1, y1 = b_dict["bbox"]
            lines: List[FitzLine] = []

            for l_dict in b_dict.get("lines", []):
                lx0, ly0, lx1, ly1 = l_dict["bbox"]
                spans: List[FitzSpan] = []

                for s_dict in l_dict.get("spans", []):
                    sx0, sy0, sx1, sy1 = s_dict["bbox"]
                    text = s_dict.get("text", "")

                    # Extract styling
                    font = s_dict.get("font", "")
                    size = s_dict.get("size", 9.0)
                    flags = s_dict.get("flags", 0)
                    color_int = s_dict.get("color", 0)

                    # Extract RGB components from fitz integer color (sRGB)
                    r = (color_int >> 16) & 0xFF
                    g = (color_int >> 8) & 0xFF
                    b = color_int & 0xFF
                    color_css = f"rgb({r},{g},{b})"

                    # Detect Bold, Italic, Superscript
                    is_bold, is_italic = self._detect_font_style(font, flags)
                    is_sup = bool(flags & 1)  # Bit 0 indicates superscript

                    spans.append(FitzSpan(
                        text=text,
                        left=sx0,
                        top=sy0,
                        right=sx1,
                        bottom=sy1,
                        font_name=font,
                        font_size=size,
                        color=color_css,
                        is_bold=is_bold,
                        is_italic=is_italic,
                        is_sup=is_sup
                    ))

                if spans:
                    lines.append(FitzLine(
                        spans=spans,
                        left=lx0,
                        top=ly0,
                        right=lx1,
                        bottom=ly1
                    ))

            if not lines:
                continue

            # Compute actual layout line height
            line_height_ratio = self._compute_line_height(lines)

            # Determine if this block sits on top of a non-white vector background (e.g., Abstract grey boxes)
            bg_color = self._detect_background_color(x0, y0, x1, y1, paths)

            blocks.append(FitzBlock(
                block_id=block_id_counter,
                lines=lines,
                left=x0,
                top=y0,
                right=x1,
                bottom=y1,
                page_number=page_number,
                bg_color=bg_color,
                line_height_ratio=line_height_ratio
            ))
            block_id_counter += 1

        return blocks

    def _detect_font_style(self, font_name: str, flags: int) -> Tuple[bool, bool]:
        """
        Uses both font name flags and binary bitwise flags to robustly spot bold/italic variations.
        """
        font_lower = font_name.lower()
        
        # Check standard PyMuPDF flags
        is_bold = bool(flags & 16) or any(x in font_lower for x in ["bold", "black", "heavy", "-b"])
        is_italic = bool(flags & 2) or any(x in font_lower for x in ["italic", "oblique", "-i"])

        return is_bold, is_italic

    def _compute_line_height(self, lines: List[FitzLine]) -> float:
        """
        Computes the visual line spacing ratio (useful for pixel-perfect CSS rendering).
        """
        if len(lines) < 2:
            return 1.1

        spacings = []
        for i in range(1, len(lines)):
            delta = lines[i].top - lines[i-1].top
            if delta > 0:
                spacings.append(delta)

        if not spacings:
            return 1.1

        avg_spacing = sum(spacings) / len(spacings)
        dominant_fs = max(s.font_size for line in lines for s in line.spans) if lines else 9.0
        
        ratio = avg_spacing / max(dominant_fs, 1.0)
        return min(max(ratio, 0.9), 2.0)  # Clamp values to avoid weird layouts

    def _detect_background_color(self, x0: float, y0: float, x1: float, y1: float, paths: List[FitzPath]) -> str:
        """
        Spatially checks if any solid drawing sits directly under this block's center coordinate.
        """
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0

        for path in paths:
            if not path.fill_color:
                continue

            # Check bounding box containment
            px0 = path.left
            py0 = path.top
            px1 = path.left + path.width
            py1 = path.top + path.height

            if (px0 <= cx <= px1) and (py0 <= cy <= py1):
                # Récupère les valeurs RGB de la chaîne "rgb(r,g,b)"
                try:
                    parts = [int(v) for v in path.fill_color.replace("rgb(", "").replace(")", "").split(",")]
                    # Si toutes les composantes sont > 240 (gris très clair / blanc), on ignore
                    if all(c > 240 for c in parts):
                        continue
                except ValueError:
                    continue
                
                return path.fill_color

        return "white"