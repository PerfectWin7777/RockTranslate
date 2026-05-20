# src/reconstruction/html_builder.py

from typing import List, Optional
from core.domain import FitzDocument, FitzPage, FitzBlock, FitzPath


class HTMLBuilder:
    """
    Constructs pixel-perfect HTML/CSS pages to be rendered inside QWebEngineView.
    Positions text boxes absolute-by-coordinate on top of a rendered high-res PNG background.
    """

    @staticmethod
    def build_page(page: FitzPage, show_overlay: bool = True) -> str:
        """Génère le HTML d'une seule page."""
        display_w = int(page.width)
        display_h = int(page.height)

        paths_html = ""
        for p in page.paths:
            paths_html += HTMLBuilder._generate_path_element(p)

        blocks_html = ""
        for block in page.blocks:
            if not block.text.strip():
                continue
            blocks_html += HTMLBuilder._generate_block_element(block)
        
        overlay_html = ""
        if show_overlay:
            overlay_html = """
            <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;
                        background:rgba(255,255,255,0.15);backdrop-filter:blur(6px);
                        z-index:100;display:flex;justify-content:center;align-items:center;">
            <div style="background:rgba(255,255,255,0.9);padding:30px 50px;border-radius:12px;
                        text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.2);">
                <h3 style="color:#1e293b;margin-bottom:8px;">✨ Prêt à traduire</h3>
                <p style="color:#64748b;font-size:14px;">Cliquez sur Démarrer la traduction</p>
            </div>
            </div>"""


        return f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="UTF-8">
    <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{
        background: #2b2e3c;
        display: flex;
        justify-content: center;
        padding: 20px;
        font-family: 'Times New Roman', Times, serif;
    }}
    .page-container {{
        position: relative;
        width: {display_w}px;
        height: {display_h}px;
        background-image: url('data:image/png;base64,{page.png_b64}');
        background-size: {display_w}px {display_h}px;
        background-repeat: no-repeat;
        box-shadow: 0 10px 30px rgba(0,0,0,0.4);
        overflow: hidden;
    }}
    .block-element {{
        position: absolute;
        z-index: 2;
        overflow: visible;
        white-space: normal;
        word-wrap: break-word;
        -webkit-font-smoothing: antialiased;
    }}
    .text-span {{ display: inline; }}
    </style>
    </head>
    <body>
    <div class="page-container">
    {overlay_html}
    {paths_html}
    {blocks_html}
    </div>

    </body>
    </html>"""


    @staticmethod
    def build_document(document: FitzDocument, show_blurred_overlay: bool = False) -> str:
        """
        Generates a continuous, scrollable HTML representation of the entire document.
        Renders all pages stacked vertically with precise coordinates and inline dimensions.
        
        Args:
            document: The FitzDocument object containing all pages and structural data.
            show_blurred_overlay: If True, applies a modern frosted-glass blur over 
                                  the pages to indicate the "ready to translate" state.
        """
        pages_html = ""
        
        for page in document.pages:
            display_w = int(page.width)
            display_h = int(page.height)

            # 1. Build background vector paths (fills, shapes, borders)
            paths_html = ""
            for p in page.paths:
                paths_html += HTMLBuilder._generate_path_element(p)

            # 2. Build text blocks (either original spans or translated text flow)
            blocks_html = ""
            for block in page.blocks:
                if block.skip_translation or not block.text.strip():
                    continue
                blocks_html += HTMLBuilder._generate_block_element(block)

            # 3. Append the individual page wrapper container to the cumulative document list.
            # We apply inline width, height, and background-image so that pages can have different sizes.
            blur_class = 'blurred-layout' if show_blurred_overlay else ''
            pages_html += f"""
            <div class="page-container {blur_class}" style="
                width: {display_w}px; 
                height: {display_h}px; 
                background-image: url('data:image/png;base64,{page.png_b64}'); 
                background-size: {display_w}px {display_h}px;
                margin-bottom: 24px;
            ">
                {paths_html}
                {blocks_html}
            </div>
            """

        # 4. Handle Frosted Glass Overlay (CSS Glassmorphism spanning the entire viewport)
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

        # 5. Assemble the final complete HTML template with a vertical scrolling layout
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
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
        /* Apply layout blur if transition state is activated */
        .page-container.blurred-layout {{
            filter: blur(5px);
            pointer-events: none;
        }}
        .block-element {{
            position: absolute;
            z-index: 2;
            overflow: visible;
            white-space: normal;
            word-wrap: break-word;
            -webkit-font-smoothing: antialiased;
        }}
        .text-span {{
            display: inline;
        }}
        /* Frosted glass overlay layout styles */
        .glass-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(8px);
            -webkit-backdrop-filter: blur(8px);
            z-index: 100;
            display: flex;
            justify-content: center;
            align-items: center;
            pointer-events: auto;
        }}
        .glass-card {{
            background: rgba(255, 255, 255, 0.9);
            padding: 30px 50px;
            border-radius: 12px;
            text-align: center;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.25);
            border: 1px solid rgba(255, 255, 255, 0.2);
            animation: fadeIn 0.3s ease-out;
        }}
        .glass-card h3 {{
            color: #1e293b;
            margin-bottom: 8px;
            font-size: 20px;
            font-weight: 700;
        }}
        .glass-card p {{
            color: #64748b;
            font-size: 14px;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: scale(0.97); }}
            to {{ opacity: 1; transform: scale(1); }}
        }}
    </style>
</head>
<body>
    {pages_html}
    {overlay_html}
</body>
</html>"""
    

    @staticmethod
    def _generate_path_element(path: FitzPath) -> str:
        """
        Generates absolute divs for underlying graphical vector paths.
        """
        fill_css = path.fill_color if path.fill_color else "transparent"
        border_css = (
            f"{path.stroke_width:.1f}px solid {path.stroke_color}"
            if path.stroke_color and path.stroke_width > 0
            else "none"
        )
        return (
            f'<div style="position: absolute; '
            f'left: {path.left:.1f}px; top: {path.top:.1f}px; '
            f'width: {path.width:.1f}px; height: {path.height:.1f}px; '
            f'background: {fill_css}; border: {border_css}; '
            f'z-index: 1; pointer-events: none;"></div>\n'
        )

    @staticmethod
    def _generate_block_element(block: FitzBlock) -> str:
        """
        Generates an absolutely positioned text block container.
        Dynamically adjusts text-rendering based on translation availability.
        """
        align = block.alignment
        bg_css = block.bg_color

        content_html = ""

        # --- MODE A : Translation exists ---
        if block.translated_text:
            # We render the entire translated paragraph using the block's dominant styles
            # The background mask sits directly behind the block to cleanly hide the original text
            dom_size = block.fs_dominant
            content_html = (
                f'<span style="'
                f'font-size: {dom_size:.1f}px; '
                f'background: {bg_css};'
                f'">{block.translated_text}</span>'
            )

        # --- MODE B : Original text (Pre-translation) ---
        else:
            # We map spans recursively to match style structures perfectly
            for line in block.lines:
                for span in line.spans:
                    weight = "bold" if span.is_bold else "normal"
                    style = "italic" if span.is_italic else "normal"
                    size = span.font_size
                    valign = "baseline"

                    if span.is_sup:
                        valign = "super"
                        size *= 0.7  # Scale down superscripts (citations, formulas)

                    content_html += (
                        f'<span class="text-span" style="'
                        f'color: {span.color}; '
                        f'font-weight: {weight}; '
                        f'font-style: {style}; '
                        f'font-size: {size:.1f}px; '
                        f'vertical-align: {valign}; '
                        f'background: {bg_css};'
                        f'">{span.text}</span> '
                    )

        # Generates the parent container
        return (
            f'<div class="block-element" style="'
            f'left: {block.left - 1.0:.1f}px; '
            f'top: {block.top:.1f}px; '
            f'width: {block.width + 4.0:.1f}px; '
            f'min-height: {block.height:.1f}px; '
            f'font-size: {block.fs_dominant:.1f}px; '
            f'line-height: {block.line_height_ratio:.3f}; '
            f'background: {block.bg_color}; '
            f'text-align: {align};">'
            f'{content_html}</div>\n'
        )