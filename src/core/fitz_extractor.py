# src/core/fitz_extractor.py

import base64, os
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

        # ← NOUVEAU : détecte les zones de tableaux et d'images
        table_blocks  = self._extract_table_rects(page)
        image_rects = self._extract_image_rects(page)
        skip_rects = [(tb.left, tb.top, tb.right, tb.bottom) for tb in table_blocks] + image_rects  # zones à ne pas couvrir


        # 3. Extract text blocks
        blocks = self._extract_text_blocks(page, page_number, paths, skip_rects )

        all_blocks = blocks + table_blocks

        return FitzPage(
            number=page_number,
            width=page_w,
            height=page_h,
            blocks=all_blocks,
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

    def _extract_text_blocks(self, page: fitz.Page, page_number: int, paths: List[FitzPath], skip_rects=[]) -> List[FitzBlock]:
        """
        Extracts structural text layouts and maps background colors.
        """
        blocks: List[FitzBlock] = []
        
        # Extract rich dictionary layout from PyMuPDF
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        # text_dict = page.get_text("dict")
        
        block_id_counter = 0

        for b_dict in text_dict.get("blocks", []):
            # Type 0 is text. Ignore images/drawings blocks here
            if b_dict.get("type") != 0:
                continue

            x0, y0, x1, y1 = b_dict["bbox"]

            # Récupère le texte brut du bloc pour l'analyser
            raw_text = " ".join(s.get("text", "") for line in b_dict.get("lines", []) for s in line.get("spans", ""))
            if self._is_math_block(raw_text):
                continue  # On ignore la formule, elle reste propre sur le PNG d'origine !


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

            is_over_image = self._is_over_image(x0, y0, x1, y1, skip_rects)
            block = FitzBlock(
                block_id=block_id_counter,
                lines=lines,
                left=x0,
                top=y0,
                right=x1,
                bottom=y1,
                page_number=page_number,
                bg_color=bg_color,
                line_height_ratio=line_height_ratio
            )

            if is_over_image:
                block.bg_color = "transparent"  # ne cache pas l'image

            if self._is_in_skip_zone(x0, y0, x1, y1, skip_rects):
               continue  # ignore ce bloc — le PNG montre le tableau/image original
    

            blocks.append(block)
            block_id_counter += 1

        return blocks
    
    def _is_over_image(self, x0, y0, x1, y1, image_rects) -> bool:
        """Vérifie si ce bloc texte intersecte (chevauche) une zone d'image."""
        for ix0, iy0, ix1, iy1 in image_rects:
            # Calcul du chevauchement horizontal et vertical
            h_overlap = max(0, min(x1, ix1) - max(x0, ix0))
            v_overlap = max(0, min(y1, iy1) - max(y0, iy0))
            if h_overlap > 2 and v_overlap > 2:
                return True
        return False
    
    def _is_in_skip_zone(self, x0, y0, x1, y1, skip_rects) -> bool:
        """
        Retourne True si ce bloc de texte intersecte une zone de tableau ou d'image.
        Si intersecté, le texte ne sera pas dessiné pour laisser l'original propre.
        """
        for rx0, ry0, rx1, ry1 in skip_rects:
            # Vérification géométrique stricte d'intersection de deux bboxes
            h_overlap = max(0, min(x1, rx1) - max(x0, rx0))
            v_overlap = max(0, min(y1, ry1) - max(y0, ry0))
            # Si la surface de collision est réelle (> 2 points), il y a chevauchement
            if h_overlap > 2 and v_overlap > 2:
                return True
        return False


    def _extract_image_rects(self, page: fitz.Page) -> list:
        """
        Retourne les bboxes de toutes les images physiques de la page via l'API native.
        Ignore les images de fond décoratives (filigranes) de grande taille.
        """
        rects = []
        page_w = page.rect.width
        page_h = page.rect.height

        try:
            # get_image_info() renvoie une liste de dicts contenant la clé 'bbox' pour chaque image
            for img_info in page.get_image_info(hashes=True, xrefs=True):
                bbox = img_info.get("bbox")
                if not bbox:
                    continue
                
                # Conversion du tuple de coordonnées (x0, y0, x1, y1)
                x0, y0, x1, y1 = bbox
                w = x1 - x0
                h = y1 - y0
                
                # Optionnel : ignore les arrière-plans décoratifs plein écran (>95%)
                # if w > page_w * 0.95 or h > page_h * 0.95:
                #     continue
                
                rects.append((x0, y0, x1, y1))
        except Exception as e:
            logger.warning(f"Erreur lors de la détection des images : {e}")
       
        return rects
    
    def _extract_table_rects(self, page: fitz.Page) -> list:
        """
        Extrait les tableaux en convertissant la page courante en fichier Word temporaire,
        en la lisant avec python-docx (OpenXML) et en la mappant géométriquement sur le PDF 
        à l'aide d'une recherche textuelle native (search_for).
        """
        table_blocks = []
        temp_docx_path = None
        try:
            import tempfile
            from pdf2docx import Converter
            from docx import Document
            import mammoth
            import io
            from core.domain import FitzTableBlock

            # 1. Génération d'un fichier Word temporaire unique pour la page courante
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                temp_docx_path = tmp.name

            page_idx = page.number
            cv = Converter(self.pdf_path)
            cv.convert(temp_docx_path, pages=[page_idx])
            cv.close()

            # 2. Ouverture et parsing avec la bibliothèque standard python-docx (OpenXML)
            doc = Document(temp_docx_path)
            
            # S'il n'y a aucun tableau physique dans le Word généré, on quitte proprement
            if not doc.tables:
                self._cleanup_temp_file(temp_docx_path)
                return table_blocks

            block_id_counter = 10000

            # 3. Traitement de chaque tableau détecté par l'OpenXML de Word
            for table in doc.tables:
                # Extraction sémantique de la matrice de cellules
                matrix = []
                for row in table.rows:
                    row_cells = [cell.text.strip() for cell in row.cells]
                    matrix.append(row_cells)

                # Évite de traiter des tableaux vides accidentels
                if not any(any(cell for cell in row) for row in matrix):
                    continue

                # Recherche textuelle sur la page PDF pour caler géométriquement le tableau
                first_text = ""
                for row in matrix:
                    for cell in row:
                        if cell.strip() and len(cell.strip()) > 3:
                            first_text = cell.strip()
                            break
                    if first_text:
                        break

                last_text = ""
                for row in reversed(matrix):
                    for cell in reversed(row):
                        if cell.strip() and len(cell.strip()) > 3:
                            last_text = cell.strip()
                            break
                    if last_text:
                        break

                # Coordonnées géométriques par défaut (fallback de sécurité)
                tx0, ty0, tx1, ty1 = 50.0, 100.0, page.rect.width - 50, page.rect.height - 100

                # Calage précis de la boîte haute du tableau
                if first_text:
                    rects_top = page.search_for(first_text)
                    if rects_top:
                        ty0 = rects_top[0].y0 - 20  # Légère marge haute pour englober la légende
                        tx0 = rects_top[0].x0 - 10

                # Calage précis de la boîte basse du tableau
                if last_text:
                    rects_bottom = page.search_for(last_text)
                    if rects_bottom:
                        ty1 = rects_bottom[0].y1 + 15
                        tx1 = max(rects_bottom[0].x1 + 10, tx0 + 100)

                # Sécurité géométrique pour éviter des coordonnées inversées ou aberrantes
                if ty1 <= ty0 or tx1 <= tx0:
                    ty1 = ty0 + len(table.rows) * 22 + 30
                    tx1 = page.rect.width - tx0

                # 4. Reconstruction du tableau isolé en mémoire vive pour conversion Mammoth
                table_doc = Document()
                new_table = table_doc.add_table(rows=len(table.rows), cols=len(table.columns))
                for r_idx, row in enumerate(table.rows):
                    for c_idx, cell in enumerate(row.cells):
                        new_table.cell(r_idx, c_idx).text = cell.text

                docx_stream = io.BytesIO()
                table_doc.save(docx_stream)
                docx_stream.seek(0)

                # Conversion du flux Word en HTML pur via Mammoth
                result = mammoth.convert_to_html(docx_stream)
                html_content = result.value
                docx_stream.close()

                # Ajout de l'objet de tableau structuré
                table_blocks.append(FitzTableBlock(
                    block_id=block_id_counter,
                    left=tx0,
                    top=ty0,
                    right=tx1,
                    bottom=ty1,
                    page_number=page_idx + 1,
                    html_content=html_content
                ))
                block_id_counter += 1

            self._cleanup_temp_file(temp_docx_path)
            print(f"✅ OpenXML + Mammoth extracted {len(table_blocks)} structured tables on Page {page.number + 1}")

        except Exception as e:
            self._cleanup_temp_file(temp_docx_path)
            import traceback
            traceback.print_exc()
            logger.warning(f"Échec de la détection de tableaux via OpenXML : {e}")

        return table_blocks

    def _cleanup_temp_file(self, path: Optional[str]):
        """Supprime proprement les fichiers temporaires pour éviter les fuites de ressources."""
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

            
       
    
    def _is_math_block(self, text: str) -> bool:
        """
        Détecte si un bloc de texte représente une formule mathématique ou une équation.
        """
        t = text.strip()
        if not t:
            return False

        # Heuristique 1 : Se termine par un numéro d'équation entre parenthèses, ex: "(2)" ou "(4)"
        import re
        if re.search(r'\(\d+\)$', t) or re.search(r'\(Eq\.\s*\d+\)$', t):
            return True

        # Heuristique 2 : Contient des symboles mathématiques complexes
        math_symbols = {'∑', '∫', '∏', '√', '±', '−', '×', '÷', '≠', '≤', '≥', '≈', '≡', 'λ', 'μ', 'π', 'σ', '∂', '∆', '∇'}
        if any(sym in t for sym in math_symbols):
            return True

        # Heuristique 3 : Formule courte contenant une égalité (ex: "aij = 1/aji")
        if " = " in t and len(t) < 80:
            return True

        return False
    
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