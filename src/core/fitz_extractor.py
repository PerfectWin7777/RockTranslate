# src/core/fitz_extractor.py
 
import base64
import os, re 
import fitz
from typing import List, Tuple, Optional
from loguru import logger
 
from core.domain import (
    FitzSpan,
    FitzLine,
    FitzBlock,
    FitzPath,
    FitzPage,
    FitzDocument,
    FitzTableBlock,
)
from core.cid_normalizer import build_cid_maps, normalize_cids
 
class FitzExtractor:
    """
    Handles PDF data extraction using PyMuPDF (fitz).
    Converts PDF layout into a structured FitzDocument where each FitzLine
    is the primary rendering unit, enriched with styled_text and layout info.
    """
 
    def __init__(self, pdf_path: str, dpi: int = 150):
        self.pdf_path = pdf_path
        self.dpi = dpi
        self.cid_maps = None
 
    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────
 
    def extract_document(
        self,
        page_number: int = None,
        max_pages: int = None,
    ) -> FitzDocument:
        """
        Parses the PDF and returns a structured FitzDocument.
        - page_number : extract only that page (1-based).
        - max_pages   : limit extraction to N pages.
        - both None   : extract the full document.
        """
        logger.info(f"Opening document: {self.pdf_path}")
        doc = fitz.open(self.pdf_path)
        fitz_doc = FitzDocument(path=self.pdf_path)
 
        total_pages = len(doc)
 
        if page_number is not None:
            start = max(0, page_number - 1)
            end = min(start + 1, total_pages)
        else:
            start = 0
            end = total_pages if max_pages is None else min(max_pages, total_pages)
 
        for page_num in range(start, end):
            page = doc[page_num]
            fitz_page = self._extract_page(page, page_num + 1)
            fitz_doc.pages.append(fitz_page)
            logger.info(f"Extracted page {page_num + 1}/{total_pages}")
 
        doc.close()
        return fitz_doc
 
    # ──────────────────────────────────────────────────────────────────────────
    # PAGE EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────
 
    def _extract_page(self, page: fitz.Page, page_number: int) -> FitzPage:
        """
        Extracts one page: background image, vector paths, and text blocks
        whose lines are fully enriched (styled_text + layout).
        """
        # Lazy-load CID maps from the parent document
        if not self.cid_maps:
            self.cid_maps = build_cid_maps(page.parent)
 
        page_w = page.rect.width
        page_h = page.rect.height
 
        paths       = self._extract_paths(page)
        image_rects = self._extract_image_rects(page)
 
        # 1. Extract text FIRST
        blocks = self._extract_text_blocks(page, page_number, paths, image_rects)

        # 2. THEN blank words
        for word in page.get_text("words"):
            page.draw_rect(
                fitz.Rect(word[0], word[1], word[2], word[3]),
                color=(1, 1, 1), fill=(1, 1, 1)
            )

        # 3. THEN generate PNG
        png_b64 = self._generate_page_image_b64(page)

        return FitzPage(
            number=page_number,
            width=page_w,
            height=page_h,
            blocks=blocks,
            paths=paths,
            png_b64=png_b64,
        )
 
    # ──────────────────────────────────────────────────────────────────────────
    # LINE CLUSTERING  (ported from test_piste_b — same logic, works on FitzLine)
    # ──────────────────────────────────────────────────────────────────────────
 
    @staticmethod
    def _should_group_lines(a: FitzLine, b: FitzLine) -> bool:
        """
        Determines if two physical lines belong to the same semantic block.
        Ported directly from test_piste_b should_group_lines.
        """
        top, bot = (a, b) if a.top <= b.top else (b, a)
        v_gap  = bot.top - top.bottom
        line_h = max(top.height, bot.height)
 
        if v_gap < -2.0:
            h_gap = max(0.0, max(top.left, bot.left) - min(top.right, bot.right))
            return h_gap < 40.0
 
        if v_gap > line_h * 1.5:
            return False
 
        overlap_x = min(top.right, bot.right) - max(top.left, bot.left)
        if overlap_x > 0:
            return True
 
        h_gap = max(top.left, bot.left) - min(top.right, bot.right)
        return h_gap < 15.0
 
    @staticmethod
    def _cluster_lines_into_blocks(lines: List[FitzLine]) -> List[List[FitzLine]]:
        """
        Groups physical FitzLines into semantic blocks using connectivity.
        Ported directly from test_piste_b cluster_lines_into_blocks.
        """
        from collections import defaultdict
        n   = len(lines)
        adj = defaultdict(list)
 
        for i in range(n):
            for j in range(i + 1, n):
                if FitzExtractor._should_group_lines(lines[i], lines[j]):
                    adj[i].append(j)
                    adj[j].append(i)
 
        visited = set()
        groups: List[List[FitzLine]] = []
 
        for i in range(n):
            if i not in visited:
                component = []
                queue = [i]
                visited.add(i)
                while queue:
                    curr = queue.pop(0)
                    component.append(lines[curr])
                    for neighbor in adj[curr]:
                        if neighbor not in visited:
                            visited.add(neighbor)
                            queue.append(neighbor)
                groups.append(component)
 
        return groups
 
    # ──────────────────────────────────────────────────────────────────────────
    # TEXT BLOCK EXTRACTION  (core of the new approach)
    # ──────────────────────────────────────────────────────────────────────────
 
    def _extract_text_blocks(
        self,
        page: fitz.Page,
        page_number: int,
        paths: List[FitzPath],
        image_rects: List[tuple],
    ) -> List[FitzBlock]:
        """
        Extracts FitzBlock objects whose FitzLines are the primary rendering unit.
 
        Pipeline mirrors test_piste_b exactly:
          1. Extract ALL raw lines from PyMuPDF — no skip zones, no filters
          2. Cluster lines into semantic blocks (_cluster_lines_into_blocks)
          3. Assign one_col / two_col layout (_detect_line_layouts)
          4. Build styled_text per line (_build_styled_text_for_line)
          5. Wrap each cluster into a FitzBlock
        """
        page_w     = page.rect.width
        rot_matrix = page.rotation_matrix
        text_dict  = page.get_text("dict")
 
        # ── Step 1 : collect ALL raw lines — no filtering ─────────────────────
        all_lines_flat: List[FitzLine] = []
 
        for b_dict in text_dict.get("blocks", []):
            if b_dict.get("type") != 0:
                continue
 
            for l_dict in b_dict.get("lines", []):
                r_line = fitz.Rect(l_dict["bbox"]) * rot_matrix
                lx0, ly0, lx1, ly1 = r_line.x0, r_line.y0, r_line.x1, r_line.y1
 
                spans: List[FitzSpan] = []
 
                for s_dict in l_dict.get("spans", []):
                    r_span = fitz.Rect(s_dict["bbox"]) * rot_matrix
                    sx0, sy0, sx1, sy1 = r_span.x0, r_span.y0, r_span.x1, r_span.y1
 
                    raw_text  = s_dict.get("text", "")
                    font      = s_dict.get("font", "")
                    size      = s_dict.get("size", 9.0)
                    flags     = s_dict.get("flags", 0)
                    color_int = s_dict.get("color", 0)
 
                    r = (color_int >> 16) & 0xFF
                    g = (color_int >> 8)  & 0xFF
                    b = color_int         & 0xFF
                    color_css = f"rgb({r},{g},{b})"
 
                    is_bold, is_italic = self._detect_font_style(font, flags)
                    is_sup = bool(flags & 1)
                    text   = normalize_cids(raw_text, font, self.cid_maps)
 
                    spans.append(FitzSpan(
                        text=text,
                        left=sx0, top=sy0, right=sx1, bottom=sy1,
                        font_name=font, font_size=size, color=color_css,
                        is_bold=is_bold, is_italic=is_italic, is_sup=is_sup,
                    ))
 
                if spans:
                    line_text = " ".join(s.text for s in spans if s.text.strip())
                    if line_text.strip():
                        all_lines_flat.append(FitzLine(
                            spans=spans,
                            left=lx0, top=ly0, right=lx1, bottom=ly1,
                        ))
 
        logger.info(f"Raw lines extracted: {len(all_lines_flat)}")
 
        # ── Step 2 : cluster lines into semantic blocks ───────────────────────
        clusters = self._cluster_lines_into_blocks(all_lines_flat)
        logger.info(f"Semantic blocks after clustering: {len(clusters)}")
 
        # ── Step 3 : assign layout to every line ──────────────────────────────
        self._detect_line_layouts(all_lines_flat, page_w)
 
        # ── Step 4 & 5 : styled_text + assemble FitzBlocks ───────────────────
        blocks: List[FitzBlock] = []
 
        for block_id_counter, cluster in enumerate(clusters):
            cluster_sorted = sorted(cluster, key=lambda l: l.top)
 
            bx0 = min(l.left   for l in cluster_sorted)
            by0 = min(l.top    for l in cluster_sorted)
            bx1 = max(l.right  for l in cluster_sorted)
            by1 = max(l.bottom for l in cluster_sorted)
 
            bg_color          = self._detect_background_color(bx0, by0, bx1, by1, paths)
            line_height_ratio = self._compute_line_height(cluster_sorted)
            is_over_image     = self._is_over_image(bx0, by0, bx1, by1, image_rects)
 
            for line in cluster_sorted:
                line.block_id    = block_id_counter
                line.styled_text = self._build_styled_text_for_line(line)
 
            block = FitzBlock(
                block_id=block_id_counter,
                lines=cluster_sorted,
                left=bx0, top=by0, right=bx1, bottom=by1,
                page_number=page_number,
                bg_color="transparent" if is_over_image else bg_color,
                line_height_ratio=line_height_ratio,
            )
            blocks.append(block)
 
        return blocks
 
    # ──────────────────────────────────────────────────────────────────────────
    # LAYOUT DETECTION  (isolated — easy to swap later)
    # ──────────────────────────────────────────────────────────────────────────
 
    def _detect_line_layouts(self, lines: List[FitzLine], page_width: float) -> None:
        """
        Assigns layout = 'one_col' or 'two_col' to every FitzLine in-place.
 
        Strategy: Y-band analysis across the whole page.
          - Divide the page into horizontal bands of BAND_HEIGHT points.
          - For each band, count how many lines cross the page center.
          - If > 30% of lines in a band cross the center → one_col band.
          - Each line inherits the layout of its band.
 
        This function mutates lines directly and returns nothing.
        Keeping it isolated means the detection strategy can be replaced
        without touching any other part of the pipeline.
        """
        if not lines:
            return
 
        BAND_HEIGHT  = 50.0
        page_center  = page_width / 2.0
 
        y_min = min(l.top    for l in lines)
        y_max = max(l.bottom for l in lines)
 
        # Build band → layout mapping
        band_layout: dict[float, str] = {}
        y = y_min
        while y < y_max:
            band_lines = [l for l in lines if y <= l.top < y + BAND_HEIGHT]
            if band_lines:
                # A line "crosses the center" if it spans across page_center
                crossing = [
                    l for l in band_lines
                    if l.left < page_center and l.right > page_center
                ]
                ratio = len(crossing) / len(band_lines)
                band_layout[y] = "one_col" if ratio > 0.30 else "two_col"
            y += BAND_HEIGHT
 
        if not band_layout:
            # Fallback: if no bands were computed, treat everything as one_col
            for line in lines:
                line.layout = "one_col"
            return
 
        # Assign layout to each line by finding its closest band
        band_keys = list(band_layout.keys())
        for line in lines:
            closest_band = min(band_keys, key=lambda by: abs(by - line.top))
            line.layout = band_layout[closest_band]
 
    # ──────────────────────────────────────────────────────────────────────────
    # STYLED TEXT  (per line — same tag logic as the original per-block version)
    # ──────────────────────────────────────────────────────────────────────────
 
    def _build_styled_text_for_line(self, line: FitzLine) -> str:
        """
        Builds the tagged styled_text string for a single FitzLine.
        Tags used: <b>, <i>, <sup>, <color_HEX>, <fs_N>.
        Same logic as the original _build_styled_text but scoped to one line.
        The LLM receives this string and must preserve the tags around
        the translated words.
        """
        # Dominant font size for this line (median across spans)
        sizes = [s.font_size for s in line.spans if s.font_size]
        dominant_size = sorted(sizes)[len(sizes) // 2] if sizes else 9.0
 
        parts = []
 
        for span in line.spans:
            chunk = span.text.strip()
            if not chunk:
                continue
 
            # ── Color tag (non-black text only) ───────────────────────────────
            try:
                rgb = span.color.replace("rgb(", "").replace(")", "").split(",")
                r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
                is_dark = r < 50 and g < 50 and b < 50
            except Exception:
                is_dark = True
 
            if not is_dark:
                hex_color = f"{r:02x}{g:02x}{b:02x}"
                chunk = f"<color_{hex_color}>{chunk}</color_{hex_color}>"
 
            # ── Font size tag (only when significantly different from dominant) ─
            if abs(span.font_size - dominant_size) > 1.5:
                size_int = int(round(span.font_size))
                chunk = f"<fs_{size_int}>{chunk}</fs_{size_int}>"
 
            # ── Superscript ───────────────────────────────────────────────────
            if span.is_sup:
                chunk = f"<sup>{chunk}</sup>"
 
            # ── Italic ────────────────────────────────────────────────────────
            if span.is_italic:
                chunk = f"<i>{chunk}</i>"
 
            # ── Bold ──────────────────────────────────────────────────────────
            if span.is_bold:
                chunk = f"<b>{chunk}</b>"
 
            parts.append(chunk)
 
        result = " ".join(parts)
        return re.sub(r'\s+', ' ', result).strip()
 
    # ──────────────────────────────────────────────────────────────────────────
    # PATHS, IMAGE, BACKGROUND HELPERS  (unchanged from original)
    # ──────────────────────────────────────────────────────────────────────────
 
    def _extract_paths(self, page: fitz.Page) -> List[FitzPath]:
        """Extracts vector drawings (fills, rectangles, strokes)."""
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
            if w < 2.0 and h < 2.0:
                continue
 
            fill         = draw.get("fill")
            color        = draw.get("color")
            stroke_width = draw.get("width", 1.0) or 1.0
 
            fill_css   = f"rgb({int(fill[0]*255)},{int(fill[1]*255)},{int(fill[2]*255)})"   if fill  else None
            stroke_css = f"rgb({int(color[0]*255)},{int(color[1]*255)},{int(color[2]*255)})" if color else None
 
            paths.append(FitzPath(
                left=x0, top=y0, width=w, height=h,
                fill_color=fill_css,
                stroke_color=stroke_css,
                stroke_width=stroke_width,
            ))
 
        return paths
 
    def _generate_page_image_b64(self, page: fitz.Page) -> str:
        """Renders the page to PNG and returns it as a base64 string."""
        zoom   = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix    = page.get_pixmap(matrix=matrix, alpha=False)
        return base64.b64encode(pix.tobytes("png")).decode("utf-8")
 
    def _extract_image_rects(self, page: fitz.Page) -> List[tuple]:
        """Returns bounding boxes of all physical images on the page."""
        rects = []
        try:
            for img_info in page.get_image_info(hashes=True, xrefs=True):
                bbox = img_info.get("bbox")
                if bbox:
                    rects.append(tuple(bbox))
        except Exception as e:
            logger.warning(f"Image rect detection failed: {e}")
        return rects
 
    def _is_over_image(self, x0, y0, x1, y1, image_rects) -> bool:
        """Returns True if the block bbox overlaps any image zone."""
        for ix0, iy0, ix1, iy1 in image_rects:
            if max(0, min(x1, ix1) - max(x0, ix0)) > 2 and \
               max(0, min(y1, iy1) - max(y0, iy0)) > 2:
                return True
        return False
 
    def _is_in_skip_zone(self, x0, y0, x1, y1, skip_rects) -> bool:
        """Returns True if the bbox intersects any skip zone (image or table area)."""
        for rx0, ry0, rx1, ry1 in skip_rects:
            if max(0, min(x1, rx1) - max(x0, rx0)) > 2 and \
               max(0, min(y1, ry1) - max(y0, ry0)) > 2:
                return True
        return False
 
    def _detect_font_style(self, font_name: str, flags: int) -> Tuple[bool, bool]:
        """Detects bold and italic from font name and PyMuPDF bitflags."""
        font_lower = font_name.lower()
        is_bold   = bool(flags & 16) or any(x in font_lower for x in ["bold", "black", "heavy", "-b"])
        is_italic = bool(flags & 2)  or any(x in font_lower for x in ["italic", "oblique", "-i"])
        return is_bold, is_italic
 
    def _compute_line_height(self, lines: List[FitzLine]) -> float:
        """Computes the visual line spacing ratio for CSS line-height."""
        if len(lines) < 2:
            return 1.1
        spacings = [
            lines[i].top - lines[i - 1].top
            for i in range(1, len(lines))
            if lines[i].top - lines[i - 1].top > 0
        ]
        if not spacings:
            return 1.1
        avg_spacing = sum(spacings) / len(spacings)
        dominant_fs = max(s.font_size for line in lines for s in line.spans) if lines else 9.0
        return min(max(avg_spacing / max(dominant_fs, 1.0), 0.9), 2.0)
 
    def _detect_background_color(
        self, x0: float, y0: float, x1: float, y1: float, paths: List[FitzPath]
    ) -> str:
        """Returns the fill color of any solid path sitting under this block's center."""
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
 
        for path in paths:
            if not path.fill_color:
                continue
            px0, py0 = path.left, path.top
            px1, py1 = path.left + path.width, path.top + path.height
 
            if (px0 <= cx <= px1) and (py0 <= cy <= py1):
                try:
                    parts = [
                        int(v)
                        for v in path.fill_color.replace("rgb(", "").replace(")", "").split(",")
                    ]
                    if all(c > 240 for c in parts):
                        continue
                except ValueError:
                    continue
                return path.fill_color
 
        return "white"



# ==============================================================================
# LEGACY ARCHITECTURE — kept for reference only, not used in the active pipeline
# ==============================================================================











    #  def _extract_tables(self, page: fitz.Page) -> list:
    #     """
    #     Analyse la page en mémoire, extrait la grille géométrique,
    #     et y associe les mots propres de PyMuPDF de manière immuable.
    #     """
    #     table_blocks = []

    #     try:
    #         # 1. Extraction des spans de style de la page
    #         text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    #         spans = []
    #         for b in text_dict.get("blocks", []):
    #             if b.get("type") != 0:
    #                 continue
    #             for line in b.get("lines", []):
    #                 for span in line.get("spans", []):
    #                     spans.append(span)

    #         # 2. Extraction des mots physiques et rotation cohérente
    #         raw_words = page.get_text("words")
    #         all_words = []
    #         rot_matrix = page.rotation_matrix
            
    #         for w in raw_words:
    #             r_orig = fitz.Rect(w[0], w[1], w[2], w[3])
    #             wx_center = (w[0] + w[2]) / 2.0
    #             wy_center = (w[1] + w[3]) / 2.0

    #             font_size = 8.5
    #             font_for_resolve = "" 
    #             is_bold = False
    #             is_italic = False
    #             color_css = "rgb(0,0,0)"

    #             for span in spans:
    #                 sx0, sy0, sx1, sy1 = span["bbox"]
    #                 if (sx0 - 1.0 <= wx_center <= sx1 + 1.0) and (sy0 - 1.0 <= wy_center <= sy1 + 1.0):
    #                     font_size = span.get("size", 8.5)
    #                     font_for_resolve = span.get("font", "") 
    #                     font_name = font_for_resolve.lower()
    #                     flags = span.get("flags", 0)
    #                     color_int = span.get("color", 0)

    #                     is_bold = bool(flags & 16) or any(x in font_name for x in ["bold", "black", "heavy", "-b"])
    #                     is_italic = bool(flags & 2) or any(x in font_name for x in ["italic", "oblique", "-i"])

    #                     r_col = (color_int >> 16) & 0xFF
    #                     g_col = (color_int >> 8) & 0xFF
    #                     b_col = color_int & 0xFF
    #                     color_css = f"rgb({r_col},{g_col},{b_col})"
    #                     break

    #             r_rot = r_orig * rot_matrix

    #             # On applique la normalisation CID sur le texte brut du mot
    #             cleaned_text = normalize_cids(w[4], font_for_resolve, self.cid_maps)

    #             all_words.append({
    #                 "text": cleaned_text,
    #                 "x0": r_rot.x0,
    #                 "top": r_rot.y0,
    #                 "x1": r_rot.x1,
    #                 "bottom": r_rot.y1,
    #                 "font_size": font_size,
    #                 "is_bold": is_bold,
    #                 "is_italic": is_italic,
    #                 "color": color_css
    #             })

    #         # 3. Analyse de la grille en mémoire
    #         cv = Converter(self.pdf_path)
    #         settings = cv.default_settings
    #         settings['parse_stream_table'] = False   
    #         cv.load_pages(start=page.number, end=page.number + 1)
    #         cv.parse_document(**settings)
    #         cv.parse_pages(**settings)

    #         page_docx = cv.pages[page.number]
    #         table_blocks_docx = find_table_blocks_recursively(page_docx)

    #         # ── FILTRAGE SÉMANTIQUE : Élimine les fausses équations ──────────
    #         table_blocks_docx = [t for t in table_blocks_docx if _is_real_table(t, page.rect.width)]

    #         # Tri des blocs de tableaux de haut en bas
    #         table_blocks_docx = sorted(table_blocks_docx, key=lambda t: t.bbox.y0)

    #         # ── FERMETURE DES GAPS VERTICAUX EN MÉMOIRE ──────────────────────
    #         for i in range(len(table_blocks_docx) - 1):
    #             t_curr = table_blocks_docx[i]
    #             t_next = table_blocks_docx[i+1]
                
    #             curr_bottom = t_curr.bbox.y1
    #             next_top = t_next.bbox.y0
                
    #             # Si l'écart est d'un interligne normal (< 35pt), on étire la ligne du bas de t_curr
    #             if 0 < (next_top - curr_bottom) < 35.0:
    #                 # Récupération de la dernière ligne du tableau courant
    #                 last_row = t_curr[-1]
    #                 last_row.update_bbox((last_row.bbox.x0, last_row.bbox.y0, last_row.bbox.x1, next_top))
                    
    #                 # Mise à jour de toutes les cellules de cette ligne vers le bas
    #                 for cell in last_row:
    #                     if cell:
    #                         cell.update_bbox((cell.bbox.x0, cell.bbox.y0, cell.bbox.x1, next_top))
                    
    #                 # Mise à jour du TableBlock lui-même
    #                 t_curr.update_bbox((t_curr.bbox.x0, t_curr.bbox.y0, t_curr.bbox.x1, next_top))

    #         block_id = 10000
    #         for table in table_blocks_docx:
    #             # Alignement hybride des mots dans la grille corrigée
    #             aligned_cells = self._build_hybrid_cells(all_words, table)
    #             tx0, ty0, tx1, ty1 = table.bbox

    #             table_blocks.append(FitzTableBlock(
    #                 block_id=block_id,
    #                 left=tx0,
    #                 top=ty0,
    #                 right=tx1,
    #                 bottom=ty1,
    #                 page_number=page.number + 1,
    #                 words=[],
    #                 cells=aligned_cells,
    #             ))
    #             block_id += 1
    #             logger.info(f"  Table {block_id-10000}: {len(aligned_cells)} cellules construites en mémoire.")

    #         cv.close()

    #     except Exception as e:
    #         import traceback; traceback.print_exc()
    #         logger.warning(f"Table extraction failed p{page.number+1}: {e}")

    #     return table_blocks


    # def _is_real_table(self, table) -> bool:
    #     """Filtre les faux positifs : texte en colonnes détecté comme tableau."""
    #     if len(table.rows) < 2 or len(table.columns) < 2:
    #         return False

    #     # 1. Récupère l'intégralité du texte consolidé du tableau
    #     all_text = "".join(cell.text for row in table.rows for cell in row.cells).strip()
    #     if not all_text:
    #         return False

    #     # 2. Calcul du ratio de caractères numériques (chiffres 0-9)
    #     digit_count = sum(1 for c in all_text if c.isdigit())
    #     digit_ratio = digit_count / len(all_text)

    #     # Un vrai tableau scientifique possède une forte densité de chiffres (>= 5%).
    #     # Un tableau fantôme de mise en page (ex: abstract/titre) n'en contient presque aucun.
    #     if digit_ratio < 0.05:
    #         return False

    #     # 3. Filtre classique sur la longueur de la première ligne
    #     first_row_texts = [c.text.strip() for c in table.rows[0].cells]
    #     long_cells = sum(1 for t in first_row_texts if len(t) > 80)
    #     if long_cells >= len(table.columns) - 1:
    #         return False
            
    #     return True

    # def _cleanup_temp_file(self, path: Optional[str]):
    #     """Supprime proprement les fichiers temporaires pour éviter les fuites de ressources."""
    #     if path and os.path.exists(path):
    #         try:
    #             os.remove(path)
    #         except Exception:
    #             pass

            
    # def _is_contained_in_existing(self, zone: dict, seen_zones: list[dict], threshold: float = 0.75) -> bool:
    #     """
    #     Retourne True si cette zone est largement contenue dans une zone déjà vue,
    #     ou si une zone déjà vue est largement contenue dans celle-ci.
    
    #     On calcule le taux de chevauchement surfacique :
    #         overlap_area / min(area_A, area_B) > threshold
    
    #     threshold=0.75 : si 75% de la plus petite zone est couverte → doublon.
    #     Pas de valeur hardcodée sur les pixels — c'est une fraction des surfaces.
    #     """
    #     z_area = max(1.0, (zone["x1"] - zone["x0"]) * (zone["bottom"] - zone["top"]))
    
    #     for seen in seen_zones:
    #         s_area = max(1.0, (seen["x1"] - seen["x0"]) * (seen["bottom"] - seen["top"]))
    
    #         # Chevauchement
    #         h_ov = max(0.0, min(zone["x1"], seen["x1"]) - max(zone["x0"], seen["x0"]))
    #         v_ov = max(0.0, min(zone["bottom"], seen["bottom"]) - max(zone["top"], seen["top"]))
    #         overlap = h_ov * v_ov
    
    #         ratio = overlap / min(z_area, s_area)
    #         if ratio > threshold:
    #             return True
    
    #     return False


# def _is_real_table(table, page_width: float) -> bool:
#     """
#     Filtre sémantique intelligent pour distinguer un vrai tableau de données 
#     scientifiques d'un faux tableau .
#     """
#     num_rows = table.num_rows
#     num_cols = table.num_cols
    
#     # 1. Dimensions minimales : un vrai tableau a au moins 2 colonnes et 2 lignes
#     if num_rows < 2 or num_cols < 2:
#         return False

#      # 2. Condition de Largeur relative (votre idée s'exprime ici)
#     # Le tableau doit occuper au moins 45% de la largeur totale de la page
#     tx0, ty0, tx1, ty1 = table.bbox
#     table_width = tx1 - tx0
#     if table_width < page_width * 0.45:
#         return False
        
#     # 2. Extraction complète du texte brut du TableBlock
#     all_text_parts = []
#     for row in table:
#         for cell in row:
#             if cell and cell.text:
#                 all_text_parts.append(cell.text)
                
#     all_text = " ".join(all_text_parts).strip()
#     if not all_text:
#         return False
        
#     # 3. Calcul du ratio de caractères numériques (chiffres 0-9)
#     digit_count = sum(1 for c in all_text if c.isdigit())
#     digit_ratio = digit_count / len(all_text)
    
#     # Un vrai tableau de données scientifiques contient une densité de chiffres significative (>= 2.5%)
#     # Les faux tableaux (comme les blocs de texte/Abstract séparés par des lignes) n'en contiennent presque aucun
#     # if digit_ratio < 0.005:
#     #     return False
        
#     return True


