#src/reconstruction/html_builder.py

import re,os
import math
from typing import List
from core.domain import FitzDocument, FitzPage, FitzBlock, FitzPath, FitzTableBlock, FitzLine
from utils.style_codec import decode_styled_text
from translation.chunker import should_translate

_FONTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")
).replace("\\", "/")


print(_FONTS_DIR)

class HTMLBuilder:
    """
    Builds pixel-perfect HTML pages rendered inside QWebEngineView.
    Each FitzLine becomes one absolutely positioned div on top of the
    background PNG (which already has all original text blanked out).
    """

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def build_document(
        document: FitzDocument, 
        # show_blurred_overlay: bool = False,
        show_skeletons: bool = False
    ) -> str:
        """
        Generates a continuous scrollable HTML document — all pages stacked vertically.
        Each line of each block is rendered as an absolutely positioned div.
        """
        pages_html = ""


        for page_idx, page in enumerate(document.pages):
            display_w = int(page.width)
            display_h = int(page.height)

            # Compute column boundaries once per page (needed for effective_width)
            # col_left_max, col_right_min, page_right_max = HTMLBuilder._compute_column_boundaries(
            #     page.blocks, page.width
            # )

            geo = HTMLBuilder._detect_column_layout(page.blocks, page.width)

            lines_html = ""
            for block in page.blocks:
                if isinstance(block, FitzTableBlock):
                    # Table blocks are not yet handled in the new pipeline
                    continue
                for line in block.lines:
                    # lines_html += HTMLBuilder._generate_line_div(
                    #     line=line,
                    #     block=block,
                    #     page_width=page.width,
                    #     col_left_max=col_left_max,
                    #     col_right_min=col_right_min,
                    #     page_right_max=page_right_max,
                    #     page_idx=page_idx,
                    #     show_skeletons=show_skeletons,
                    # )

                    lines_html += HTMLBuilder._generate_line_div(
                        line=line, block=block, page_width=page.width,
                        geo=geo,
                        page_idx=page_idx,
                        show_skeletons=show_skeletons,
                    )

        #     blur_class = "blurred-layout" if show_blurred_overlay else ""
        #     pages_html += f"""
        #     <div id="page-container-{page_idx}" class="page-container {blur_class}" style="
        #         width: {display_w}px;
        #         height: {display_h}px;
        #         background-image: url('data:image/png;base64,{page.png_b64}');
        #         background-size: {display_w}px {display_h}px;
        #         margin-bottom: 24px;
        #     ">
        #         {lines_html}
        #     </div>
        #     """

        # # Frosted glass overlay (shown before translation starts)
        # overlay_html = ""
        # if show_blurred_overlay:
        #     overlay_html = """
        #     <div class="glass-overlay">
        #         <div class="glass-card">
        #             <h3>✨ Translation Layer Active</h3>
        #             <p>Ready to translate this document.</p>
        #         </div>
        #     </div>
        #     """


        glass_overlay = f"""
            <div id="glass-overlay-{page_idx}" style="
                position: absolute;
                top: 10%;
                left: 10%;
                width: 80%;
                height: 80%;
                background: rgba(255, 255, 255, 0.15);
                backdrop-filter: blur(8px);
                -webkit-backdrop-filter: blur(8px);
                border-radius: 12px;
                z-index: 10;
                display: flex;
                justify-content: center;
                align-items: center;
                pointer-events: none;
            ">
                <div style="
                    background: rgba(255,255,255,0.9);
                    padding: 20px 40px;
                    border-radius: 10px;
                    text-align: center;
                    box-shadow: 0 8px 32px rgba(0,0,0,0.2);
                ">
                    <p style="color:#1e293b; font-size:14px; font-weight:600; margin:0;">
                        ⏳ En attente de traduction...
                    </p>
                </div>
            </div>
            """

        pages_html += f"""
        <div id="page-container-{page_idx}" class="page-container" style="
            width: {display_w}px;
            height: {display_h}px;
            background-image: url('data:image/png;base64,{page.png_b64}');
            background-size: {display_w}px {display_h}px;
            margin-bottom: 24px;
        ">
            {glass_overlay}
            {lines_html}
        </div>
        """



        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #2b2e3c;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
            padding: 30px 0;
            font-family: 'Times New Roman', Times, serif;
        }}
        .page-container {{
            position: relative;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
            overflow: hidden;
            border-radius: 4px;
            background-color: white;
            background-repeat: no-repeat;
        }}
        .page-container.blurred-layout {{
            filter: blur(5px);
            pointer-events: none;
        }}
        .line-div {{
            position: absolute;
            background-color: transparent;
            white-space: nowrap;
            overflow: visible;
            display: flex;
            align-items: center;
        }}
        .glass-overlay {{
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 100;
            display: flex;
            justify-content: center;
            align-items: center;
        }}
        .glass-card {{
            background: rgba(255, 255, 255, 0.9);
            padding: 30px 50px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
            animation: fadeIn 0.3s ease-out;
        }}
        .glass-card h3 {{ color: #1e293b; margin-bottom: 8px; font-size: 20px; font-weight: 700; }}
        .glass-card p  {{ color: #64748b; font-size: 14px; }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: scale(0.97); }}
            to   {{ opacity: 1; transform: scale(1); }}
        }}

    /* ── ANIMATIONS DU SQUELETTE ET DE L'APPARITION DU TEXTE ── */
        @keyframes shimmer {{
            0% {{ background-position: -200% 0; }}
            100% {{ background-position: 200% 0; }}
        }}
        
        .skeleton-line {{
            display: inline-block;
            width: 100%;
            height: 10px;
            background: linear-gradient(90deg, #f1f5f9 25%, #cbd5e1 50%, #f1f5f9 75%);
            background-size: 200% 100%;
            animation: shimmer 1.8s infinite linear;
            border-radius: 4px;
        }}
        
        .fade-in {{
            animation: fadeInEffect 0.5s ease-out forwards;
        }}
        
        @keyframes fadeInEffect {{
            from {{ opacity: 0; transform: translateY(1px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
        }}

       
        @font-face {{
            font-family: 'EB Garamond';
            src: url('file:///{_FONTS_DIR}/EBGaramond-Regular.ttf');
            font-weight: normal; font-style: normal;
        }}
        @font-face {{
            font-family: 'EB Garamond';
            src: url('file:///{_FONTS_DIR}/EBGaramond-Bold.ttf');
            font-weight: bold; font-style: normal;
        }}
        @font-face {{
            font-family: 'EB Garamond';
            src: url('file:///{_FONTS_DIR}/EBGaramond-Italic.ttf');
            font-weight: normal; font-style: italic;
        }}
        @font-face {{
            font-family: 'EB Garamond';
            src: url('file:///{_FONTS_DIR}/EBGaramond-BoldItalic.ttf');
            font-weight: bold; font-style: italic;
        }}

    </style>

    <script>
        // Surgical block injection — called by TranslationViewer after each translated line
        function updateBlock(pageIdx, blockId, lineId, blockHtml) {{
            var el = document.getElementById("line-" + pageIdx + "-" + blockId + "-" + lineId);
            if (el) {{
                el.outerHTML = blockHtml;
            }} else {{
                var container = document.getElementById("page-container-" + pageIdx);
                if (container) {{
                    container.insertAdjacentHTML('beforeend', blockHtml);
                }}
            }}
        }}

        function removeGlass(pageIdx) {{
                var el = document.getElementById("glass-overlay-" + pageIdx);
                if (el) el.remove();
            }}

        function showPagePdf(pageIdx, pdfPath) {{
            var container = document.getElementById("page-container-" + pageIdx);
            if (container) {{
                container.innerHTML = '<iframe src="' + pdfPath + '" style="width:100%;height:100%;border:none;"></iframe>';
            }}
        }}

    </script>
</head>
<body>
    {pages_html}
   
</body>
</html>"""

    # ──────────────────────────────────────────────────────────────────────────
    # LINE DIV GENERATOR  (core of the new rendering approach)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _generate_line_div(
        line: FitzLine,
        block: FitzBlock,
        page_width: float,
        geo: dict,
        page_idx: int,
        show_skeletons: bool = False,
    ) -> str:
        real_line_width = max(line.right - line.left, 10)

        # 1. Calcul de effective_width via la géométrie de colonnes
        effective_width = HTMLBuilder._effective_col_width(line, geo)

        # 2. Sélection du texte à afficher
        if show_skeletons and should_translate(line) and not line.translated_text:
            text_to_render = f'<span class="skeleton-line" style="width: {real_line_width:.1f}px;"></span>'
            raw_translated = ""
        elif line.translated_text:
            text_to_render = f'<span class="fade-in">{decode_styled_text(line.translated_text)}</span>'
            raw_translated =re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', line.translated_text))
        else:
            raw_fallback   = line.styled_text or line.text
            text_to_render = decode_styled_text(raw_fallback) if line.styled_text else line.text
            raw_translated = ""

        # 3. Taille de police avec compression si texte trop long
        sizes = [s.font_size for s in line.spans if s.font_size]
        dominant_size = sorted(sizes)[len(sizes) // 2] if sizes else getattr(block, 'fs_dominant', 9.0)
        

        # if raw_translated:
        #     trans_plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', raw_translated))
        #     estimated_w = len(trans_plain) * dominant_size * 0.52
        #     if estimated_w > effective_width:
        #         scale = max(0.55, effective_width / estimated_w)
        #         final_font_size = dominant_size * scale
        #     else:
        #         final_font_size = dominant_size
        # else:
        #     final_font_size = dominant_size

        final_font_size = dominant_size
        # final_font_size = final_font_size * 1.45
        # 4. Style dominant
        dominant_span = max(line.spans, key=lambda s: len(s.text)) if line.spans else None
        font_weight   = "bold"   if (dominant_span and dominant_span.is_bold)   else "normal"
        font_style_cs = "italic" if (dominant_span and dominant_span.is_italic) else "normal"
        color         = dominant_span.color if dominant_span else "rgb(0,0,0)"
        font_family   = HTMLBuilder._clean_font_family(
            dominant_span.font_name if dominant_span else ""
        )

        # 5. Positionnement vertical centré
        line_height  = line.bottom - line.top
        y_center     = line.top + line_height / 2.0
        final_height = max(line_height, final_font_size * 1.1)
        final_top    = y_center - final_height / 2.0

        line_idx   = block.lines.index(line)
        element_id = f"line-{page_idx}-{block.block_id}-{line_idx}"

        return (
            f'<div id="{element_id}" style="'
            f'position: absolute; '
            f'left: {line.left:.1f}px; '
            f'top: {final_top:.1f}px; '
            f'width: {effective_width:.1f}px; '
            f'max-width: {effective_width:.1f}px; '
            f'height: auto; '
            f'min-height: {final_height:.1f}px; '
            f'font-family: {font_family}; '
            f'font-size: {final_font_size:.2f}px; '
            f'font-weight: {font_weight}; '
            f'font-style: {font_style_cs}; '
            f'color: {color}; '
            f'background-color: transparent !important; '
            f'white-space: nowrap; '
            f'overflow: visible !important; '
            f'display: flex; '
            f'align-items: center; '
            f'padding: 1px 2px; '
            f'margin: -1px -2px;'
            f'"><span style="display: inline-block; width: 100%; white-space: nowrap;">'
            f'{text_to_render}</span></div>\n'
        )


    @staticmethod
    def _generate_line_divSSSSS(
        line: FitzLine,
        block: FitzBlock,
        page_width: float,
        col_left_max: float,
        col_right_min: float,
        page_right_max: float,
        page_idx: int,
        show_skeletons: bool = False,
    ) -> str:
        """
        Generates one absolutely positioned div for a single FitzLine.

        Text priority:
          1. translated_text  — LLM output, decoded from style tags
          2. styled_text      — original tagged text (shown while waiting for translation)
          3. text             — raw fallback

        Font size is compressed dynamically when the translation is longer
        than the original to avoid overflow — same formula as the test.
        """
        page_center = page_width / 2.0

        # ── Sélection dynamique de l'état : Squelette, Traduit, ou Anglais initial ──
        real_line_width = max(line.right - line.left, 10)

        # Dynamic space budget determination
        if line.layout == "one_col":
            max_right = page_right_max
        else:
            if line.right <= page_center:
                # Left column line
                max_right = col_left_max
            elif line.left >= page_center:
                # Right column line
                max_right = page_right_max
            else:
                # Crossing line
                max_right = page_right_max

        effective_width = max(max_right - line.left, 10.0)

        if show_skeletons and should_translate(line) and not line.translated_text:
            text_to_render = f'<span class="skeleton-line" style="width: {real_line_width:.1f}px;"></span>'
            raw_translated = ""
        elif line.translated_text :
            text_to_render = f'<span class="fade-in">{decode_styled_text(line.translated_text)}</span>'
            raw_translated = re.sub(r'<[^>]+>', '', line.translated_text)

        else:
            raw_fallback   = line.styled_text or line.text
            text_to_render = decode_styled_text(raw_fallback) if line.styled_text else line.text
            raw_translated = ""

        sizes = [s.font_size for s in line.spans if s.font_size]
        dominant_size = sorted(sizes)[len(sizes) // 2] if sizes else getattr(block, 'fs_dominant', 9.0)

        final_font_size = dominant_size
        if raw_translated:
            estimated_text_width = len(raw_translated) * dominant_size * 0.52
            if estimated_text_width > effective_width:
                scale = effective_width / max(estimated_text_width, 1.0)
                final_font_size = max(6.0, dominant_size * scale)

        dominant_span = max(line.spans, key=lambda s: len(s.text)) if line.spans else None
        font_weight   = "bold"   if (dominant_span and dominant_span.is_bold)   else "normal"
        font_style_cs = "italic" if (dominant_span and dominant_span.is_italic) else "normal"
        color         = dominant_span.color if dominant_span else "rgb(0,0,0)"
        font_family   = HTMLBuilder._clean_font_family(
            dominant_span.font_name if dominant_span else ""
        )

        line_height  = line.bottom - line.top
        y_center     = line.top + line_height / 2.0
        final_height = max(line_height, final_font_size * 1.1)
        final_top    = y_center - final_height / 2.0

        line_idx = block.lines.index(line)
        element_id = f"line-{page_idx}-{block.block_id}-{line_idx}"

        # All styles inline — identical to the test script
        return (
            f'<div id="{element_id}" style="'
            f'position: absolute; '
            f'left: {line.left:.1f}px; '
            f'top: {final_top:.1f}px; '
            f'width: {effective_width:.1f}px; '
            f'max-width: {effective_width:.1f}px; '
            f'height: auto; '
            f'min-height: {final_height:.1f}px; '
            f'font-family: {font_family}; '
            f'font-size: {final_font_size:.2f}px; '
            f'font-weight: {font_weight}; '
            f'font-style: {font_style_cs}; '
            f'color: {color}; '
            f'background-color: transparent !important; '
            f'white-space: nowrap; '
            f'overflow: visible !important; '
            f'display: flex; '
            f'align-items: center; '
            f'padding: 1px 2px; '
            f'margin: -1px -2px;'
            f'"><span style="display: inline-block; width: 100%; white-space: nowrap;">{text_to_render}</span></div>\n'
        )

    # ──────────────────────────────────────────────────────────────────────────
    # COLUMN BOUNDARY HELPER
    # ──────────────────────────────────────────────────────────────────────────
    
    def _detect_column_layout(blocks, page_width: float) -> dict:
        lines = [l for b in blocks if isinstance(b, FitzBlock) for l in b.lines]
        page_center = page_width / 2.0
        crossing = [l for l in lines if l.left < page_center < l.right]
        ratio = len(crossing) / max(len(lines), 1)

        if ratio > 0.30:
            page_right = max((l.right for l in lines), default=page_width)
            return {"layout": "one_col", "col_left_max": page_right, "page_width":page_width,
                    "page_center": page_center, "page_right": page_right}

        left_lines  = [l for l in lines if l.right <= page_center + 10]
        right_lines = [l for l in lines if l.left  >= page_center - 10]
        return {
            "layout":       "two_col",
            "page_center":  page_center,
            "page_width":   page_width,
            "col_left_max": max((l.right for l in left_lines),  default=page_center),
            "col_right_min":min((l.left  for l in right_lines), default=page_center),
            "page_right":   max((l.right for l in lines),       default=page_width),
        }

    @staticmethod
    def _effective_col_width(line: FitzLine, geo: dict) -> float:
        MARGIN = 25.0
        page_width = geo["page_width"]
        # print(f"left={line.left} right={line.right} width={line.right-line.left}")
        if geo["layout"] == "one_col":
            return max(geo["page_right"] - line.left - MARGIN, 10.0)
        
        mid = line.left + (line.right - line.left) / 2.0
        if mid < geo["page_center"]:
            # CORRECTION : On n'autorise la pleine largeur que si le bloc d'origine occupait déjà 
            # plus de 70% de la largeur totale de la page (vrai titre ou abstract pleine-page).
            # if (line.right - line.left) > (page_width * 0.70):
            #    return max(page_width - line.left - MARGIN, 10.0)
            # Sinon, on bride strictement à la largeur de la colonne de gauche
            return max(geo["col_left_max"] - line.left - MARGIN, 10.0)
        
        return max(geo["page_right"] - line.left - MARGIN, 10.0)


    @staticmethod
    def _compute_column_boundaries(blocks, page_width: float):
        """
        Computes column boundaries and page text rightmost boundary.
        """
        page_center = page_width / 2.0

        all_lines = [line for block in blocks
                     if isinstance(block, FitzBlock)
                     for line in block.lines]

        left_rights  = [l.right for l in all_lines if l.right < page_center]
        right_lefts  = [l.left  for l in all_lines if l.left  > page_center]
        all_rights   = [l.right for l in all_lines]

        col_left_max  = max(left_rights,  default=page_center)
        col_right_min = min(right_lefts, default=page_center)
        page_right_max = max(all_rights, default=page_width - 40.0)

        # Safety padding to avoid zero or negative budgets
        return col_left_max, col_right_min, page_right_max

    # ──────────────────────────────────────────────────────────────────────────
    # FONT FAMILY HELPER
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_font_family(font_name: str) -> str:
        """Maps a raw PDF font name to a safe CSS font-family stack."""
        if "+" in font_name:
            font_name = font_name.split("+", 1)[1]
        font_lower = font_name.lower()
        if any(x in font_lower for x in [
            "times", "nimbusrom", "garamond", "caslon", "adv", "baskerville", "serif"]):
           return "'EB Garamond', 'Times New Roman', Times, serif"
        return "Arial, Helvetica, sans-serif"

    # ──────────────────────────────────────────────────────────────────────────
    # PATH ELEMENT  (unchanged — kept for optional vector overlay use)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_path_element(path: FitzPath) -> str:
        """Generates an absolutely positioned div for a vector path."""
        fill_css   = path.fill_color if path.fill_color else "transparent"
        border_css = (
            f"{path.stroke_width:.1f}px solid {path.stroke_color}"
            if path.stroke_color and path.stroke_width > 0
            else "none"
        )
        return (
            f'<div style="position:absolute;'
            f'left:{path.left:.1f}px;top:{path.top:.1f}px;'
            f'width:{path.width:.1f}px;height:{path.height:.1f}px;'
            f'background:{fill_css};border:{border_css};'
            f'z-index:1;pointer-events:none;"></div>\n'
        )




