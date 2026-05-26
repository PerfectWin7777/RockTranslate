"""
test_batches.py — Visualise les batches en HTML
Usage: python test_batches.py <pdf_path>
"""
import sys, os
sys.path.insert(0, os.path.abspath("src"))

import fitz
from core.fitz_extractor import FitzExtractor
from core.reading_order import ReadingOrderSorter
from translation.chunker import build_batches, should_translate

PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "Nsangou Ngapna et al._ASR_2024.pdf"
MODEL    = "gemini/gemini-2.5-flash-lite"

# 1. Extraction complète du document
extractor = FitzExtractor(PDF_PATH)
sorter    = ReadingOrderSorter()
doc_fitz  = fitz.open(PDF_PATH)

all_blocks = []
for page_num in range(len(doc_fitz)):
    page      = doc_fitz[page_num]
    fitz_page = extractor._extract_page(page, page_num + 1)
    fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)
    for block in fitz_page.blocks:
        block._page_num = page_num + 1  # stocke le numéro de page
    all_blocks.extend(fitz_page.blocks)

total_pages = len(doc_fitz)
doc_fitz.close()
print(f"Total blocs extraits : {len(all_blocks)}")

# 2. Filtrage + batches
valid = [b for b in all_blocks if should_translate(b)]
print(f"Blocs à traduire : {len(valid)}")

batches = build_batches(valid, MODEL)
print(f"Nombre de batches : {len(batches)}")

# 3. HTML visuel
COLORS = [
    "#fff3cd", "#d1ecf1", "#d4edda", "#f8d7da",
    "#e2d9f3", "#fde8d8", "#d0f0f0", "#fdf3d0",
    "#dde8ff", "#ffe0e0", "#e0ffe0", "#f0e0ff",
]

rows_html = ""
for b_idx, batch in enumerate(batches):
    color = COLORS[b_idx % len(COLORS)]
    for p_idx, block in enumerate(batch.paragraphs):
        page_num = getattr(block, '_page_num', '?')
        text_preview = block.text[:200].replace("<","&lt;").replace(">","&gt;")
        first_row = p_idx == 0
        rows_html += f"""
        <tr style="background:{color}">
            <td style="font-weight:bold;text-align:center;white-space:nowrap;">
                {'🔵 Batch ' + str(b_idx+1) if first_row else ''}
            </td>
            <td style="text-align:center;color:#666;">p.{page_num}</td>
            <td style="text-align:center;color:#666;">{block.block_id}</td>
            <td style="font-size:12px;">{text_preview}{'...' if len(block.text)>200 else ''}</td>
            <td style="text-align:center;color:#888;font-size:11px;">
                ~{len(block.text)//4} tok
            </td>
        </tr>"""

html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
body {{ font-family: sans-serif; padding: 20px; background: #f5f5f5; }}
h2 {{ color: #333; }}
.stats {{ background: #333; color: #fff; padding: 12px 20px; border-radius: 8px; 
          margin-bottom: 20px; font-size: 14px; }}
table {{ width: 100%; border-collapse: collapse; background: white;
         box-shadow: 0 2px 8px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }}
th {{ background: #2d3748; color: white; padding: 10px 12px; text-align: left; font-size: 13px; }}
td {{ padding: 8px 12px; border-bottom: 1px solid rgba(0,0,0,0.05); vertical-align: top; }}
tr:hover td {{ filter: brightness(0.95); }}
</style></head>
<body>
<h2>📦 Visualisation des Batches — {os.path.basename(PDF_PATH)}</h2>
<div class="stats">
  📄 {total_pages} pages &nbsp;|&nbsp;
  🧩 {len(all_blocks)} blocs extraits &nbsp;|&nbsp;
  ✅ {len(valid)} blocs à traduire &nbsp;|&nbsp;
  📦 {len(batches)} batches &nbsp;|&nbsp;
  🤖 Modèle : {MODEL}
</div>
<table>
<thead>
  <tr>
    <th style="width:100px">Batch</th>
    <th style="width:50px">Page</th>
    <th style="width:50px">ID</th>
    <th>Texte (200 chars)</th>
    <th style="width:70px">Tokens</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
</body></html>"""

out = "batches_view.html"
with open(out, "w", encoding="utf-8") as f:
    f.write(html)
print(f"\n✅ HTML → {out}")
print(f"Ouvre batches_view.html dans Chrome")

# Console summary
print(f"\nRésumé des batches :")
for i, b in enumerate(batches):
    print(f"  Batch {i+1:02d} : {len(b.paragraphs):3d} blocs, ~{b.estimated_tokens:,} tokens")