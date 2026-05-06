import sys
import os

# Ajoute le chemin source
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.pdf_extractor import PDFExtractor
from core.spatial_clusterer import SpatialClusterer

PDF_PATH = "Nsangou Ngapna et al._ASR_2024.pdf"
OUT_HTML = "visual_debugger_2d.html"

def generate_2d_debugger():
    print(f"--- Diagnostic 2D : {PDF_PATH} ---")
    
    # 1. Extraction brute
    extractor = PDFExtractor(PDF_PATH)
    document = extractor.extract()
    sc = SpatialClusterer()

    # 2. Gouttière globale
    all_raw = [p.raw_objects for p in document.pages]
    gutter = sc.find_document_gutter(all_raw, document.pages[0].width)
    
    html_pages = []

    for page_idx, page in enumerate(document.pages):
        # On processe la page pour avoir les blocs
        blocks = sc.process_page(
            page.raw_objects, 
            page.width, 
            page.number, 
            page.height,
            forced_gutter=gutter
        )
        
        # Style de la page (on respecte le ratio PDF)
        # On utilise un scale de 1.2 pour que ce soit lisible
        scale = 1.2
        page_style = (
            f"position: relative; width: {page.width*scale}px; "
            f"height: {page.height*scale}px; background: white; "
            f"margin: 20px auto; box-shadow: 0 0 10px rgba(0,0,0,0.2); "
            f"overflow: hidden; border: 1px solid #ccc;"
        )
        
        block_elements = []
        for b in blocks:
            # Calcul des coordonnées CSS
            # Le PDF compte de BAS en HAUT, le HTML de HAUT en BAS
            w = (b.right - b.left) * scale
            h = (b.top - b.bottom) * scale
            left = b.left * scale
            top = (page.height - b.top) * scale
            
            # Couleur selon la colonne
            colors = {0: "rgba(42, 122, 42, 0.15)", 1: "rgba(42, 42, 154, 0.15)", 2: "rgba(154, 42, 42, 0.15)"}
            border_colors = {0: "#2a7a2a", 1: "#2a2a9a", 2: "#9a2a2a"}
            bg = colors.get(b.column, "rgba(0,0,0,0.1)")
            border = border_colors.get(b.column, "#333")
            
            # Label de debug
            label = f"Col {b.column} | Y={b.top:.0f}"
            
            block_elements.append(f"""
                <div class="block" style="
                    position: absolute;
                    left: {left}px; top: {top}px; width: {w}px; height: {h}px;
                    background: {bg}; border: 1px solid {border};
                    z-index: 10;
                " title="{label}">
                    <div class="block-text" style="
                        font-size: 11px; 
                        color: black; 
                        line-height: 1.2;
                        width: 100%; height: 100%;
                        overflow: hidden;
                    ">
                        <small style="background:{border}; color:white; font-size:9px; display:block; width:fit-content;">{label}</small>
                        {b.text}
                    </div>
                </div>
            """)
            
        # Ligne de la gouttière (visuelle)
        if gutter > 0:
            block_elements.append(f"""
                <div style="position:absolute; left:{gutter*scale}px; top:0; bottom:0; width:1px; border-left:1px dashed red; z-index:100;"></div>
            """)

        html_pages.append(f"""
            <div class="page-container">
                <h3 style="text-align:center">PAGE {page_idx + 1}</h3>
                <div class="page" style="{page_style}">
                    {''.join(block_elements)}
                </div>
            </div>
        """)

    # Rendu final
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>RockTranslate 2D Debugger</title>
        <style>
            body {{ background: #444; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; }}
            .page-container {{ margin-bottom: 50px; }}
            .page {{ position: relative; background: white; margin: 0 auto; transition: transform 0.2s; }}
            .block {{ box-sizing: border-box; transition: all 0.1s; }}
            .block:hover {{ 
                z-index: 1000 !important; 
                background: white !important; 
                transform: scale(1.05);
                box-shadow: 0 5px 15px rgba(0,0,0,0.3);
                height: auto !important; /* Permet de voir tout le texte au survol */
                min-height: {h}px;
                padding: 10px;
            }}
            .block:hover .block-text {{ overflow: visible !important; font-size: 14px !important; }}
            h3 {{ color: white; text-align: center; text-transform: uppercase; letter-spacing: 2px; }}
        </style>
    </head>
    <body>
        <h1 style="text-align:center">RockTranslate Visual Layout Debugger</h1>
        <p style="text-align:center; color: #666;">
            Vert: Pleine Largeur | Bleu: Col Gauche | Rouge: Col Droite | Pointillé Rouge: Gouttière détectée
        </p>
        {''.join(html_pages)}
    </body>
    </html>
    """
    
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"Fichier généré : {OUT_HTML}")

if __name__ == "__main__":
    generate_2d_debugger()