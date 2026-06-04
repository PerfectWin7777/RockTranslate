#src/reconstruction/html_builder.py

import math
from typing import List
from core.domain import FitzDocument, FitzPage, FitzBlock, FitzPath, FitzTableBlock, FitzLine
from utils.style_codec import decode_styled_text


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
    def build_document(document: FitzDocument, show_blurred_overlay: bool = False) -> str:
        """
        Generates a continuous scrollable HTML document — all pages stacked vertically.
        Each line of each block is rendered as an absolutely positioned div.
        """
        pages_html = ""

        for page_idx, page in enumerate(document.pages):
            display_w = int(page.width)
            display_h = int(page.height)

            # Compute column boundaries once per page (needed for effective_width)
            col_left_max, col_right_min = HTMLBuilder._compute_column_boundaries(
                page.blocks, page.width
            )

            lines_html = ""
            for block in page.blocks:
                if isinstance(block, FitzTableBlock):
                    # Table blocks are not yet handled in the new pipeline
                    continue
                for line in block.lines:
                    lines_html += HTMLBuilder._generate_line_div(
                        line=line,
                        block=block,
                        page_width=page.width,
                        col_left_max=col_left_max,
                        col_right_min=col_right_min,
                        page_idx=page_idx,
                    )

            blur_class = "blurred-layout" if show_blurred_overlay else ""
            pages_html += f"""
            <div id="page-container-{page_idx}" class="page-container {blur_class}" style="
                width: {display_w}px;
                height: {display_h}px;
                background-image: url('data:image/png;base64,{page.png_b64}');
                background-size: {display_w}px {display_h}px;
                margin-bottom: 24px;
            ">
                {lines_html}
            </div>
            """

        # Frosted glass overlay (shown before translation starts)
        overlay_html = ""
        if show_blurred_overlay:
            overlay_html = """
            <div class="glass-overlay">
                <div class="glass-card">
                    <h3>✨ Translation Layer Active</h3>
                    <p>Ready to translate this document.</p>
                </div>
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
    </script>
</head>
<body>
    {pages_html}
    {overlay_html}
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
        col_left_max: float,
        col_right_min: float,
        page_idx: int,
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

        if line.translated_text:
            text_to_render = decode_styled_text(line.translated_text)
            original_len   = max(1, len(line.text))
            translated_len = len(line.translated_text)
            ratio          = translated_len / original_len
        else:
            raw_fallback   = line.styled_text or line.text
            text_to_render = decode_styled_text(raw_fallback) if line.styled_text else line.text
            ratio          = 1.0

        sizes         = [s.font_size for s in line.spans if s.font_size]
        dominant_size = sorted(sizes)[len(sizes) // 2] if sizes else 9.0

        final_font_size = dominant_size
        if ratio > 1.0:
            final_font_size = max(6.0, dominant_size / ratio)

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

        if line.layout == "one_col":
            effective_width = page_width - line.left - 20
        else:
            if line.right <= page_center:
                effective_width = col_left_max - line.left
            else:
                effective_width = line.right - col_right_min
        effective_width = max(effective_width, 10)

        element_id = f"line-{page_idx}-{block.block_id}-{id(line)}"

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

    @staticmethod
    def _compute_column_boundaries(blocks, page_width: float):
        """
        Computes the right edge of the left column and the left edge of the
        right column — used to calculate effective_width for two_col lines.
        Mirrors the logic from the original test script.
        """
        page_center = page_width / 2.0

        all_lines = [line for block in blocks
                     if isinstance(block, FitzBlock)
                     for line in block.lines]

        left_rights  = [l.right for l in all_lines if l.right < page_center]
        right_lefts  = [l.left  for l in all_lines if l.left  > page_center]

        col_left_max  = max(left_rights,  default=page_center)
        col_right_min = min(right_lefts, default=page_center)

        return col_left_max, col_right_min

    # ──────────────────────────────────────────────────────────────────────────
    # FONT FAMILY HELPER
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_font_family(font_name: str) -> str:
        """Maps a raw PDF font name to a safe CSS font-family stack."""
        if "+" in font_name:
            font_name = font_name.split("+", 1)[1]
        font_lower = font_name.lower()
        if any(x in font_lower for x in ["times", "nimbusrom", "serif"]):
            return "'Times New Roman', Times, serif"
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






# import math
# from typing import List, Optional
# from core.domain import FitzDocument, FitzPage, FitzBlock, FitzPath, FitzTableBlock
# from utils.style_codec import decode_styled_text

# class HTMLBuilder:
#     """
#     Constructs pixel-perfect HTML/CSS pages to be rendered inside QWebEngineView.
#     Positions text boxes absolute-by-coordinate on top of a rendered high-res PNG background.
#     """

#     @staticmethod
#     def build_page(page: FitzPage, show_overlay: bool = True) -> str:
#         """Génère le HTML d'une seule page."""
#         display_w = int(page.width)
#         display_h = int(page.height)

#         paths_html = ""
#         # for p in page.paths:
#         #     paths_html += HTMLBuilder._generate_path_element(p)

#         blocks_html = ""
#         for block in page.blocks:
#             if not block.text.strip():
#                 continue
#             blocks_html += HTMLBuilder._generate_block_element(block)
        
#         overlay_html = ""
#         if show_overlay:
#             overlay_html = """
#             <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;
#                         background:rgba(255,255,255,0.15);backdrop-filter:blur(6px);
#                         z-index:100;display:flex;justify-content:center;align-items:center;">
#             <div style="background:rgba(255,255,255,0.9);padding:30px 50px;border-radius:12px;
#                         text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.2);">
#                 <h3 style="color:#1e293b;margin-bottom:8px;">✨ Prêt à traduire</h3>
#                 <p style="color:#64748b;font-size:14px;">Cliquez sur Démarrer la traduction</p>
#             </div>
#             </div>"""


#         return f"""<!DOCTYPE html>
#     <html>
#     <head>
#     <meta charset="UTF-8">
#     <style>
#     * {{ margin:0; padding:0; box-sizing:border-box; }}
#     body {{
#         background: #2b2e3c;
#         display: flex;
#         justify-content: center;
#         padding: 20px;
#         font-family: 'Times New Roman', Times, serif;
#     }}
#     .page-container {{
#         position: relative;
#         width: {display_w}px;
#         height: {display_h}px;
#         background-image: url('data:image/png;base64,{page.png_b64}');
#         background-size: {display_w}px {display_h}px;
#         background-repeat: no-repeat;
#         box-shadow: 0 10px 30px rgba(0,0,0,0.4);
#         overflow: hidden;
#     }}
#     .block-element {{
#         position: absolute;
#         z-index: 2;
#         overflow: visible;
#         white-space: normal;
#         word-wrap: break-word;
#         -webkit-font-smoothing: antialiased;
#     }}
#     .text-span {{ display: inline; }}
#     </style>
#     </head>
#     <body>
#     <div class="page-container">
#     {overlay_html}
#     {paths_html}
#     {blocks_html}
#     </div>

#     </body>
#     </html>"""


#     @staticmethod
#     def build_document(document: FitzDocument, show_blurred_overlay: bool = False) -> str:
#         """
#         Generates a continuous, scrollable HTML representation of the entire document.
#         Renders all pages stacked vertically with precise coordinates and inline dimensions.
        
#         Args:
#             document: The FitzDocument object containing all pages and structural data.
#             show_blurred_overlay: If True, applies a modern frosted-glass blur over 
#                                   the pages to indicate the "ready to translate" state.
#         """
#         pages_html = ""
        
#         for  page_idx, page in enumerate(document.pages):
#             display_w = int(page.width)
#             display_h = int(page.height)

#             # 1. Build background vector paths (fills, shapes, borders)
#             paths_html = ""
#             # for p in page.paths:
#             #     paths_html += HTMLBuilder._generate_path_element(p)

#             # 2. Build text blocks (either original spans or translated text flow)
#             blocks_html = ""
#             for block in page.blocks:
#                 if block.skip_translation or not block.text.strip():
#                     continue

#                 # On détermine l'identifiant unique global du bloc
#                 block_id_str = f"block-{page_idx}-{block.block_id}"
#                 # print(f"[HTML] Génère id={block_id_str}") 

#                 if isinstance(block, FitzTableBlock):
#                     blocks_html += HTMLBuilder._generate_table_element(block, block_id_str)
#                 else:
#                     blocks_html += HTMLBuilder._generate_block_element(block, block_id_str)


#                 # if isinstance(block, FitzTableBlock):
#                 #     blocks_html += HTMLBuilder._generate_table_placeholder(block, block_id_str)
#                 # else:
#                 #     # Paragraphes normaux
#                 #     blocks_html += HTMLBuilder._generate_block_placeholder(block, block_id_str)

#             # 3. Append the individual page wrapper container to the cumulative document list.
#             # We apply inline width, height, and background-image so that pages can have different sizes.
#             blur_class = 'blurred-layout' if show_blurred_overlay else ''
#             pages_html += f"""
#             <div id="page-container-{page_idx}" class="page-container {blur_class}" style="
#                 width: {display_w}px; 
#                 height: {display_h}px; 
#                 background-image: url('data:image/png;base64,{page.png_b64}'); 
#                 background-size: {display_w}px {display_h}px;
#                 margin-bottom: 24px;
#             ">
#                 {paths_html}
#                 {blocks_html}
#             </div>
#             """

#         # 4. Handle Frosted Glass Overlay (CSS Glassmorphism spanning the entire viewport)
#         overlay_html = ""
#         if show_blurred_overlay:
#             overlay_html = """
#             <div class="glass-overlay">
#                 <div class="glass-card">
#                     <h3>✨ Translation Layer Active</h3>
#                     <p>Ready to translate this document.</p>
#                 </div>
#             </div>
#             """

#         # 5. Assemble the final complete HTML template with a vertical scrolling layout
#         return f"""<!DOCTYPE html>
# <html>
# <head>
#     <meta charset="UTF-8">
#     <style>
#         * {{
#             margin: 0;
#             padding: 0;
#             box-sizing: border-box;
#         }}
#         body {{
#             background: #2b2e3c;
#             display: flex;
#             flex-direction: column;
#             align-items: center;
#             min-height: 100vh;
#             padding: 30px 0;
#             font-family: 'Times New Roman', Times, serif;
#         }}
#         .page-container {{
#             position: relative;
#             box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4);
#             overflow: hidden;
#             border-radius: 4px;
#             background-color: white;
#             background-repeat: no-repeat;
#         }}
#         /* Apply layout blur if transition state is activated */
#         .page-container.blurred-layout {{
#             filter: blur(5px);
#             pointer-events: none;
#         }}
#         .block-element {{
#             position: absolute;
#             z-index: 2;
#             overflow: visible;
#             white-space: normal;
#             word-wrap: break-word;
#             -webkit-font-smoothing: antialiased;
#             /* opacity: 0; Caché au départ pour masquer le doublon d'anglais */
#             /* transition: opacity 0.4s ease-in-out;  Effet de fondu enchaîné */
#         }}
#         .text-span {{
#             display: inline;
#         }}
#         /* Frosted glass overlay layout styles */
#         .glass-overlay {{
#             position: fixed;
#             top: 0;
#             left: 0;
#             width: 100vw;
#             height: 100vh;
#             background: rgba(255, 255, 255, 0.1);
#             backdrop-filter: blur(8px);
#             -webkit-backdrop-filter: blur(8px);
#             z-index: 100;
#             display: flex;
#             justify-content: center;
#             align-items: center;
#             pointer-events: auto;
#         }}
#         .glass-card {{
#             background: rgba(255, 255, 255, 0.9);
#             padding: 30px 50px;
#             border-radius: 12px;
#             text-align: center;
#             box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
#             border: 1px solid rgba(255, 255, 255, 0.2);
#             animation: fadeIn 0.3s ease-out;
#         }}
#         .glass-card h3 {{
#             color: #1e293b;
#             margin-bottom: 8px;
#             font-size: 20px;
#             font-weight: 700;
#         }}
#         .glass-card p {{
#             color: #64748b;
#             font-size: 14px;
#         }}
#         @keyframes fadeIn {{
#             from {{ opacity: 0; transform: scale(0.97); }}
#             to {{ opacity: 1; transform: scale(1); }}
#         }}

#         /* Styles élégants pour les tableaux générés par Mammoth */
#         table {{
#             width: 100%;
#             border-collapse: collapse;
#             font-family: Arial, sans-serif;
#             font-size: 11px;
#             background-color: white;
#         }}
#         td, th {{
#             border: 1px solid #cbd5e1; /* Bordure fine gris ardoise moderne */
#             padding: 6px 8px;
#             color: #1e293b;
#             text-align: left;
#        }}

#     </style>

#     <script>
#         // Fonction globale d'injection chirurgicale
#         function updateBlock(pageIdx, blockId, blockHtml) {{
#             var el = document.getElementById("block-" + pageIdx + "-" + blockId); 
#             if (el)  {{
#                 // Si le bloc existe déjà, on remplace son HTML par le nouveau
#                 el.outerHTML = blockHtml;
#              }} else {{
#                 // S'il n'existe pas, on le crée en l'injectant dans sa page correspondante
#                 var pageContainer = document.getElementById("page-container-" + pageIdx);
#                 if (pageContainer) {{
#                     pageContainer.insertAdjacentHTML('beforeend', blockHtml);
#                 }}
#             }}
#         }}
#     </script>
    
# </head>
# <body>
#     {pages_html}
#     {overlay_html}
# </body>
# </html>"""
    

#     @staticmethod
#     def _generate_path_element(path: FitzPath) -> str:
#         """
#         Generates absolute divs for underlying graphical vector paths.
#         """
#         fill_css = path.fill_color if path.fill_color else "transparent"
#         border_css = (
#             f"{path.stroke_width:.1f}px solid {path.stroke_color}"
#             if path.stroke_color and path.stroke_width > 0
#             else "none"
#         )
#         return (
#             f'<div style="position: absolute; '
#             f'left: {path.left:.1f}px; top: {path.top:.1f}px; '
#             f'width: {path.width:.1f}px; height: {path.height:.1f}px; '
#             f'background: {fill_css}; border: {border_css}; '
#             f'z-index: 1; pointer-events: none;"></div>\n'
#         )

#     @staticmethod
#     def _generate_block_element(block: FitzBlock, element_id: str = "") -> str:
#         """
#         Generates an absolutely positioned text block container.
#         Dynamically adjusts text-rendering based on translation availability.
#         """
#         align = block.alignment
#         bg_css = block.bg_color
#         id_attr = f'id="{element_id}" ' if element_id else ""

#         content_html = ""

#         # --- MODE A : Translation exists ---
#         if block.translated_text:
#             # We render the entire translated paragraph using the block's dominant styles
#             # The background mask sits directly behind the block to cleanly hide the original text
#             dom_size = block.fs_dominant
            
#             # ── CALCUL D'ÉCHELLE CÔTÉ PYTHON ──
#             if block.text and block.translated_text:
#                 len_orig = len(block.text.strip())
#                 len_trans = len(block.translated_text.strip())
                
#                 # Si la traduction s'allonge, on réduit la police de manière amortie
#                 if len_trans > len_orig:
#                     ratio = len_trans / len_orig
#                     # Amortissement géométrique par racine carrée pour éviter de trop réduire
#                     scale = max(0.68, 1.0 / math.sqrt(ratio))
#                     dom_size = dom_size * scale

#             decoded = decode_styled_text(block.translated_text)
#             content_html = (
#                 f'<span style="'
#                 f'font-size: {dom_size:.1f}px; '
#                 f'background: {bg_css};'
#                 f'">{decoded}</span>'
#             )

#         # --- MODE B : Original text (Pre-translation) ---
#         else:
#             pass 
#             # We map spans recursively to match style structures perfectly
#             # for line in block.lines:
#             #     for span in line.spans:
#             #         weight = "bold" if span.is_bold else "normal"
#             #         style = "italic" if span.is_italic else "normal"
#             #         size = span.font_size
#             #         valign = "baseline"

#             #         if span.is_sup:
#             #             valign = "super"
#             #             size *= 0.7  # Scale down superscripts (citations, formulas)
                    
#             #         text_color = span.color
#             #         if "cid:" in span.text:
#             #             text_color = "transparent"

#             #         content_html += (
#             #             f'<span class="text-span" style="'
#             #             f'color: {text_color}; '
#             #             f'font-weight: {weight}; '
#             #             f'font-style: {style}; '
#             #             f'font-size: {size:.1f}px; '
#             #             f'vertical-align: {valign}; '
#             #             f'background: {bg_css};'
#             #             f'">{span.text}</span> '
#             #         )

#         # Generates the parent container
#         return (
#             f'<div {id_attr}class="block-element" style="'
#             f'left: {block.left - 1.0:.1f}px; '
#             f'top: {block.top:.1f}px; '
#             f'width: {block.width + 4.0:.1f}px; '
#             f'min-height: {block.height:.1f}px; '
#             f'font-size: {block.fs_dominant:.1f}px; '
#             f'line-height: {block.line_height_ratio:.3f}; '
#             f'background: {block.bg_color}; '
#             f'text-align: {align};">'
#             f'{content_html}</div>\n'
#         )
    
#     @staticmethod
#     def _generate_table_element(block, element_id: str = "") -> str:
#         """
#         Place chaque cellule traduite à sa position exacte de mots d'origine,
#         avec un masque blanc élargi de sécurité pour effacer proprement 100% de l'anglais.
#         """
#         id_attr = f'id="{element_id}" ' if element_id else ""
#         words_html = ""
#         translated_cells = getattr(block, "translated_cells", {})
#         cells = block.get_cells()
#         import math
    
#         for cell_idx, translated_text in translated_cells.items():
#             if not (0 <= cell_idx < len(cells)):
#                 continue
    
#             cell_words = cells[cell_idx]
#             if not cell_words:
#                 continue
    
#             # ── COORDONNÉES RÉELLES PYMUPDF + MASQUAGE ÉLARGI DE SÉCURITÉ ──
#             # On décale le rectangle blanc de 6px vers l'extérieur pour tout masquer
#             left   = min(w["x0"]     for w in cell_words) - 6
#             top    = min(w["top"]    for w in cell_words) - 3
#             right  = max(w["x1"]     for w in cell_words) + 6
#             bottom = max(w["bottom"] for w in cell_words) + 3
            
#             width  = right - left
#             height = bottom - top
    
#             # ── Style d'origine ──────────────────────────────────────────
#             size   = cell_words[0].get("font_size", 8.5)
#             weight = "bold"   if cell_words[0].get("is_bold")   else "normal"
#             fstyle = "italic" if cell_words[0].get("is_italic") else "normal"
#             color  = cell_words[0].get("color", "rgb(0,0,0)")
    
#             # ── CALCUL D'ÉCHELLE ADAPTATIF PAR SURFACE (SMART SCALING) ───
#             char_count = len(translated_text)
#             required_area = char_count * size * size * 0.66
#             available_area = width * height
            
#             if required_area > available_area:
#                 scale_factor = math.sqrt(available_area / required_area)
#                 size = max(6.5, size * min(0.95, scale_factor))
    
#             from utils.style_codec import decode_styled_text
#             txt = decode_styled_text(translated_text)
    
#             words_html += (
#                 f'<div style="position:absolute;'
#                 f'left:{left:.1f}px;top:{top:.1f}px;'
#                 f'width:{width:.1f}px;min-height:{height:.1f}px;'
#                 f'background:white;'  # <-- Fond blanc élargi
#                 f'overflow:hidden;'
#                 f'white-space:normal;'
#                 f'word-break:break-word;'
#                 f'line-height:1.15;'
#                 f'font-size:{size:.1f}px;font-weight:{weight};'
#                 f'font-style:{fstyle};color:{color};">'
#                 f'{txt}</div>\n'
#             )
    
#         return (
#             f'<div {id_attr}style="position:absolute;'
#             f'left:0px;top:0px;'
#             f'width:100%;height:100%;">'
#             f'{words_html}</div>\n'
#         )



#     @staticmethod
#     def _generate_block_placeholder(block: FitzBlock, element_id: str) -> str:
#         """Génère le conteneur vide et invisible pour un paragraphe."""
#         align = block.alignment
#         return (
#             f'<div id="{element_id}" class="block-element" style="'
#             f'left: {block.left - 1.0:.1f}px; '
#             f'top: {block.top:.1f}px; '
#             f'width: {block.width + 4.0:.1f}px; '
#             f'min-height: {block.height:.1f}px; '
#             f'font-size: {block.fs_dominant:.1f}px; '
#             f'line-height: {block.line_height_ratio:.3f}; '
#             f'text-align: {align};"></div>\n'
#         )

#     @staticmethod
#     def _generate_table_placeholder(block, element_id: str) -> str:
#         """Génère le conteneur vide et invisible pour un tableau."""
#         return f"""
#         <div id="{element_id}" class="block-element" style="
#             left: {block.left - 5:.1f}px;
#             top: {block.top - 15:.1f}px;
#             width: {block.width + 10:.1f}px;
#             height: {block.height + 20:.1f}px;
#             z-index: 5;
#             padding: 5px;
#             box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
#             overflow: visible;
#         "></div>\n
#         """