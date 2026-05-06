"""
extract_to_html.py — Validation de l'extraction et de l'ordre de lecture
Chemin : D:/Projets/RockTranslate/extract_to_html.py

Génère un HTML qui montre exactement ce que le LLM recevra :
- Paragraphes dans l'ordre de lecture
- Indication de colonne (gauche/droite/pleine largeur)
- Indication cross-page
- Numérotation globale

Lance depuis D:/Projets/RockTranslate/ :
    python extract_to_html.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.pdf_extractor import PDFExtractor
from core.spatial_clusterer import SpatialClusterer

PDF_PATH  = "Nsangou Ngapna et al._ASR_2024.pdf"
OUT_HTML  = "extraction_validation.html"
MAX_PAGES = None  # None = tout le document


def col_label(col: int) -> str:
    return {0: "pleine largeur", 1: "col. gauche", 2: "col. droite"}.get(col, "?")

def col_color(col: int) -> str:
    return {0: "#e8f4e8", 1: "#e8e8f4", 2: "#f4e8e8"}.get(col, "#fff")

def col_badge(col: int) -> str:
    colors = {0: "#2a7a2a", 1: "#2a2a9a", 2: "#9a2a2a"}
    c = colors.get(col, "#333")
    return f'<span style="background:{c};color:white;padding:2px 7px;border-radius:3px;font-size:11px;font-family:monospace">{col_label(col)}</span>'


def main():
    # ── Extraction ────────────────────────────────────────────────
    print(f"Extraction : {PDF_PATH}")
    extractor = PDFExtractor(PDF_PATH)
    document  = extractor.extract()

    sc = SpatialClusterer()

    # Gouttière globale
    all_raw = [p.raw_objects for p in document.pages]
    gutter  = sc.find_document_gutter(all_raw, document.pages[0].width)
    print(f"Gouttière globale : {gutter:.1f} pt")

    pages_to_process = (
        document.pages[:MAX_PAGES] if MAX_PAGES else document.pages
    )

    # ── Clustering par page ───────────────────────────────────────
    all_page_blocks = []
    for page in pages_to_process:
        blocks = sc.process_page(
            page.raw_objects,
            page.width,
            page.number,
            page.height,
            forced_gutter=gutter,
        )
        all_page_blocks.append(blocks)
        print(f"  Page {page.number} : {len(blocks)} blocs")

    # ── Cross-page ────────────────────────────────────────────────
    for i in range(len(all_page_blocks) - 1):
        all_page_blocks[i], all_page_blocks[i + 1] = sc.merge_cross_page(
            all_page_blocks[i], all_page_blocks[i + 1]
        )

    # ── Paragraphes finaux ────────────────────────────────────────
    flat       = [b for pb in all_page_blocks for b in pb]
    paragraphs = sc.build_paragraphs(flat)
    print(f"Total paragraphes : {len(paragraphs)}")

    # ── Génération HTML ───────────────────────────────────────────
    rows = []
    for i, para in enumerate(paragraphs):
        bg      = col_color(para.column)
        badge   = col_badge(para.column)
        cross   = ""
        if para.is_cross_page:
            cross = ' <span style="background:#e65c00;color:white;padding:2px 7px;border-radius:3px;font-size:11px">⚡ cross-page</span>'

        # Texte nettoyé
        text = para.text.strip().replace("<", "&lt;").replace(">", "&gt;")

        rows.append(f"""
        <tr style="background:{bg}">
          <td style="padding:6px 10px;font-size:12px;color:#666;
                     text-align:center;vertical-align:top;
                     border-right:1px solid #ddd;white-space:nowrap">
            #{i+1}<br>
            <small>p.{para.page_number}</small>
          </td>
          <td style="padding:6px 10px;vertical-align:top;
                     border-right:1px solid #ddd">
            {badge}{cross}
          </td>
          <td style="padding:8px 12px;font-size:13px;line-height:1.6">
            {text}
          </td>
        </tr>""")

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>RockTranslate — Validation extraction</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 0; padding: 20px;
            background: #f5f5f5; }}
    h1   {{ font-size: 18px; color: #333; margin-bottom: 4px; }}
    p.meta {{ font-size: 12px; color: #666; margin-bottom: 16px; }}
    table {{ width: 100%; border-collapse: collapse;
             background: white; box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
    td    {{ border-bottom: 1px solid #e8e8e8; }}
    tr:hover td {{ filter: brightness(0.97); }}
    .legend {{ display:flex; gap:16px; margin-bottom:12px;
               font-size:12px; align-items:center; }}
  </style>
</head>
<body>
  <h1>RockTranslate — Validation extraction et ordre de lecture</h1>
  <p class="meta">
    Document : <b>{PDF_PATH}</b> |
    Pages : <b>{len(pages_to_process)}</b> |
    Paragraphes : <b>{len(paragraphs)}</b> |
    Gouttière : <b>{gutter:.1f} pt</b>
  </p>
  <div class="legend">
    <b>Légende :</b>
    {col_badge(0)} &nbsp;
    {col_badge(1)} &nbsp;
    {col_badge(2)} &nbsp;
    <span style="background:#e65c00;color:white;padding:2px 7px;
                 border-radius:3px;font-size:11px">⚡ cross-page</span>
  </div>
  <table>
    <thead>
      <tr style="background:#333;color:white">
        <th style="padding:8px 10px;width:60px">#</th>
        <th style="padding:8px 10px;width:130px">Position</th>
        <th style="padding:8px 10px;text-align:left">Texte extrait</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>
</body>
</html>"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML généré : {OUT_HTML}")
    print("Ouvre ce fichier dans ton navigateur pour valider l'ordre.")


if __name__ == "__main__":
    main()