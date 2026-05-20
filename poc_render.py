"""
poc_render.py — Preuve de concept : PDF page → PNG fond + HTML texte superposé
Version : Styles Granulaires & Stabilité des Blocs
"""
import sys
import os
import base64
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import ctypes


def detect_style(font_name: str) -> tuple[bool, bool]:
    """
    Détecte gras/italique depuis le nom de police.
    Universel : fonctionne pour Elsevier, Springer, IEEE, etc.
    """
    # Normalise : on garde la partie après le dernier '+' ou '-'
    # Ex: 'ABCDEF+TimesNewRoman-BoldItalic' → 'BoldItalic'
    name = font_name
    if '+' in name:
        name = name.split('+')[-1]
    
    # Suffixes standards (toutes les foundries)
    BOLD_MARKERS   = ['-B', '-Bold', '-Black', '-Heavy', '-Semibold',
                      '-Demi', 'B', 'BD', 'Black', 'Heavy']
    ITALIC_MARKERS = ['-I', '-Italic', '-Oblique', '-It', 'I', 'IT']
    
    # On cherche à la FIN du nom (suffixe)
    name_upper = name.upper()
    
    is_bold   = any(name_upper.endswith(m.upper()) for m in BOLD_MARKERS)
    is_italic = any(name_upper.endswith(m.upper()) for m in ITALIC_MARKERS)
    
    # Cas combiné : BoldItalic, BI, etc.
    if 'BOLDITALIC' in name_upper or 'BOLD-ITALIC' in name_upper:
        is_bold = is_italic = True
    if name_upper.endswith('BI') or name_upper.endswith('-BI'):
        is_bold = is_italic = True
    
    return is_bold, is_italic


def page_to_png_base64(pdf_path: str, page_num: int, scale: float = 2.0) -> str:
    """Rend une page PDF en PNG base64 via PDFium."""
    doc  = pdfium.PdfDocument(pdf_path)
    page = doc[page_num - 1]
    bitmap = page.render(scale=scale, rotation=0)
    pil_image = bitmap.to_pil()
    
    import io
    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    doc.close()
    return b64

def extract_blocksSSSS(pdf_path: str, page_num: int) -> list[dict]:
    """Extrait les blocs avec leurs segments de style (gras, couleur, etc)."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
    
    from core.pdf_extractor     import PDFExtractor
    from core.spatial_clusterer import SpatialClusterer

    extractor = PDFExtractor(pdf_path)
    document  = extractor.extract()
    sc        = SpatialClusterer()

    all_raw = [p.raw_objects for p in document.pages]
    gutter  = sc.find_document_gutter(all_raw, document.pages[0].width)

    target_page = document.pages[page_num - 1]
    page_w = target_page.width
    page_h = target_page.height

    blocks = sc.process_page(
        target_page.raw_objects,
        page_w,
        target_page.number,
        page_h,
        forced_gutter=gutter,
    )

    result = []
    for b in blocks:
        if not b.text.strip(): continue

        segments = []
        for line in b.lines:
            for span in line.spans:
                ro = span.raw_objects[0] if span.raw_objects else None
                if ro:
                    r, g, bl = [int(c * 255) for c in ro.color]
                    segments.append({
                        "text": span.text,
                        "bold": ro.font_weight >= 600,
                        "italic": ro.is_italic,
                        "color": f"rgb({r}, {g}, {bl})",
                        "fs": ro.font_size,
                        "is_sup": (line.bottom - ro.bottom) > 1.5 
                    })
        
        page_mid = page_w / 2
        block_width = b.right - b.left
        
        # Un bloc est VRAIMENT centré si :
        # 1. Son milieu est au milieu de la page (à 15pt près)
        # 2. ET il ne prend pas toute la largeur (il reste de la place sur les côtés)
        is_truly_centered = abs(b.x_center - page_mid) < 15 and block_width < (page_w * 0.8)
        
        # Un bloc doit être justifié si :
        # 1. Il a plusieurs lignes ou beaucoup de texte
        # 2. Il occupe une largeur significative (> 40% de la page)
        should_justify = len(b.lines) > 1 or block_width > (page_w * 0.4)

        # On ne devine plus le centrage, on respecte la colonne
        OFFSET = -6  # Ajustement visuel pour compenser les marges internes du bloc
        result.append({
            "left": b.left ,
            "top": page_h - b.top + OFFSET,
            "width": b.right - b.left,
            "height":  b.top - b.bottom,
            "segments": segments,
            "column": b.column,
            "line_height": b.line_height_ratio,
            "alignment": "center" if is_truly_centered else ("justify" if should_justify else "left")
        })


    doc_raw = pdfium.PdfDocument(pdf_path)
    page_raw = doc_raw[page_num - 1]
    page_h = page_raw.get_height()
    
    paths = []
    for obj in page_raw.get_objects():
        obj_type = pdfium_c.FPDFPageObj_GetType(obj.raw)
        if obj_type != pdfium_c.FPDF_PAGEOBJ_PATH:
            continue
        try:
            L, B, R, T = obj.get_bounds()
            w = R - L
            h = T - B
            if w < 5 or h < 2:
                continue
            
            # Fill
            fr, fg, fb, fa = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
            pdfium_c.FPDFPageObj_GetFillColor(obj.raw, fr, fg, fb, fa)
            
            # Stroke
            sr, sg, sb, sa = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
            pdfium_c.FPDFPageObj_GetStrokeColor(obj.raw, sr, sg, sb, sa)
            
            sw = ctypes.c_float()
            pdfium_c.FPDFPageObj_GetStrokeWidth(obj.raw, sw)
            
            # Conversion PDF coords → HTML coords
            paths.append({
                "left":         L,
                "top":          page_h - T,  # Y inversé
                "width":        w,
                "height":       h,
                "fill":         (fr.value, fg.value, fb.value, fa.value),
                "stroke":       (sr.value, sg.value, sb.value, sa.value),
                "stroke_width": max(sw.value, 0.5),
            })
        except:
            continue
    
    doc_raw.close()
    
    # for p in paths:
    #     # Filtre pour trouver le rectangle du bas de page
    #     if p["top"] > 700 and p["width"] > 400:  # grand rectangle en bas
    #         fr, fg, fb, fa = p["fill"]
    #         sr, sg, sb, sa = p["stroke"]
    #         print(f"PATH GRAND: "
    #             f"left={p['left']:.0f} top={p['top']:.0f} "
    #             f"w={p['width']:.0f} h={p['height']:.0f} | "
    #             f"fill=({fr},{fg},{fb},a={fa}) | "
    #             f"stroke=({sr},{sg},{sb},a={sa}) | "
    #             f"stroke_w={p['stroke_width']:.2f}")
        

    return result, paths

def extract_blocks(pdf_path: str, page_num: int) -> tuple[list[dict], list[dict]]:
    """
    Extraction via PyMuPDF (fitz) — zéro clustering manuel.
    fitz.get_text("dict") donne blocs/lignes/spans avec positions exactes.
    """
    import fitz
    doc  = fitz.open(pdf_path)
    page = doc[page_num - 1]
    page_h = page.rect.height
    page_w = page.rect.width

    # ── 1. PATHS EN PREMIER ────────────────────────────────────
    paths = []
    for d in page.get_drawings():
        rect = d.get("rect")
        if not rect:
            continue
        x0, y0, x1, y1 = rect
        w, h = x1 - x0, y1 - y0
        if w < 5 or h < 1:
            continue
        fill  = d.get("fill")
        color = d.get("color")
        fr, fg, fb, fa = (int(fill[0]*255), int(fill[1]*255), int(fill[2]*255), 255) if fill else (255,255,255,0)
        sr, sg, sb, sa = (int(color[0]*255), int(color[1]*255), int(color[2]*255), 255) if color else (0,0,0,0)
        paths.append({
            "left": x0, "top": y0,
            "width": w, "height": h,
            "fill":   (fr, fg, fb, fa),
            "stroke": (sr, sg, sb, sa),
            "stroke_width": d.get("width", 1.0) or 1.0,
        })

    # ── 2. FONCTION FOND ───────────────────────────────────────
    def find_bg(x0, y0, x1, y1):
        cx, cy = (x0+x1)/2, (y0+y1)/2
        for p in paths:
            px1 = p["left"] + p["width"]
            py1 = p["top"]  + p["height"]
            fr, fg, fb, fa = p["fill"]
            if (p["left"] <= cx <= px1 and
                p["top"]  <= cy <= py1 and
                fa > 0 and
                not (fr > 240 and fg > 240 and fb > 240)):
                return f"rgb({fr},{fg},{fb})"
        return "white"

    # ── 3. BLOCS TEXTE ─────────────────────────────────────────
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    blocks_result = []

    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        x0, y0, x1, y1 = block["bbox"]
        lines = block.get("lines", [])
        segments = []
        dominant_fs = 9.0

        for line in lines:
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                fs        = span.get("size", 9.0)
                font      = span.get("font", "")
                font_lower= font.lower()
                flags     = span.get("flags", 0)
                color_int = span.get("color", 0)
                r = (color_int >> 16) & 0xFF
                g = (color_int >> 8)  & 0xFF
                b =  color_int        & 0xFF
                is_bold, is_italic = detect_style(font)
                is_sup    = bool(flags & (1 << 0))
                dominant_fs = max(dominant_fs, fs)
                segments.append({
                    "text": text, "bold": is_bold, "italic": is_italic,
                    "is_sup": is_sup, "color": f"rgb({r},{g},{b})", "fs": fs,
                })

                # if text:
                #    print(f"font='{font}' | bold={is_bold} | italic={is_italic} | text='{text[:20]}'")
                #    fonts_seen = set()
                # for block in data["blocks"]:
                #     if block.get("type") != 0:
                #         continue
                #     for line in block.get("lines", []):
                #         for span in line.get("spans", []):
                #             font = span.get("font", "")
                #             text = span.get("text", "").strip()
                #             if font not in fonts_seen and text:
                #                 fonts_seen.add(font)
                #                 print(f"POLICE: '{font}' | ex: '{text[:30]}'")

        if not segments:
            continue

        real_lh = []
        for i in range(1, len(lines)):
            delta = lines[i]["bbox"][1] - lines[i-1]["bbox"][1]
            if delta > 0:
                real_lh.append(delta)
        lh_ratio = (sum(real_lh)/len(real_lh)/max(dominant_fs,1)) if real_lh else 1.15

        bw = x1 - x0
        is_centered   = abs((x0+x1)/2 - page_w/2) < 15 and bw < page_w * 0.8
        should_justify= bw > page_w * 0.4

        blocks_result.append({
            "left": x0, "top": y0,
            "width": bw, "height": y1 - y0,
            "segments": segments,
            "alignment": "center" if is_centered else ("justify" if should_justify else "left"),
            "bg_color": find_bg(x0, y0, x1, y1),   # ← couleur réelle
            "line_height": lh_ratio,
            "fs_dominant": dominant_fs,
        })

    doc.close()
    print(f"  fitz : {len(blocks_result)} blocs, {len(paths)} paths")

    for i, b in enumerate(blocks_result):
        first_text = b["segments"][0]["text"] if b["segments"] else ""
        print(f"[{i:02d}] top={b['top']:.0f} left={b['left']:.0f} | '{first_text[:30]}'")

    return blocks_result, paths


def generate_html(png_b64: str, blocks: list[dict], paths: list[dict], page_w: float, page_h: float) -> str:
    display_w = int(page_w)
    display_h = int(page_h)

    # ── Paths (rectangles, lignes, bordures) ──────────────────
    paths_html = ""
    for p in paths:
        fr, fg, fb, fa = p["fill"]
        sr, sg, sb, sa = p["stroke"]

        fill_css   = f"rgb({fr},{fg},{fb})"   if fa   > 0 else "transparent"
        border_css = f"{p['stroke_width']:.1f}px solid rgb({sr},{sg},{sb})" if sa > 0 and p["stroke_width"] > 0 else "none"

        paths_html += (
            f'<div style="position:absolute;'
            f'left:{p["left"]:.1f}px;top:{p["top"]:.1f}px;'
            f'width:{p["width"]:.1f}px;height:{p["height"]:.1f}px;'
            f'background:{fill_css};border:{border_css};'
            f'z-index:1;pointer-events:none;"></div>\n'
        )

    # ── Blocs texte ───────────────────────────────────────────
    blocks_html = ""
    for b in blocks:
        align = b.get("alignment", "left")
        bg_css = b.get("bg_color", "white")
        
        content_html = ""
        for s in b["segments"]:
            weight = "bold"   if s["bold"]   else "normal"
            fstyle = "italic" if s["italic"] else "normal"
            size   = s["fs"]
            valign = "baseline"

            if s.get("is_sup"):
                valign = "super"
                size  *= 0.7

            content_html += (
                f'<span style="'
                f'color:{s["color"]};'
                f'font-weight:{weight};'
                f'font-style:{fstyle};'
                f'font-size:{size:.1f}px;'
                f'vertical-align:{valign};'
                f'background:{bg_css};'
                f'">{s["text"]}</span> '
            )

        blocks_html += (
            f'<div class="block" style="'
            f'left:{b["left"] - 1:.1f}px;'
            f'top:{b["top"]:.1f}px;'
            f'width:{b["width"] + 4:.1f}px;'
            f'min-height:{b["height"]:.1f}px;'
            f'font-size:{b["fs_dominant"]:.1f}px;'
            f'line-height:{b["line_height"]:.3f};'
            f'background:{b["bg_color"]};' 
            f'text-align:{align};">'
            f'{content_html}</div>\n'
        )

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background: #525659;
    display: flex;
    justify-content: center;
    padding: 20px;
  }}
  .page {{
    position: relative;
    width:  {display_w}px;
    height: {display_h}px;
    background-image: url('data:image/png;base64,{png_b64}');
    background-size: {display_w}px {display_h}px;
    background-repeat: no-repeat;
    box-shadow: 0 0 10px rgba(0,0,0,0.5);
    overflow: hidden;
  }}
  .block {{
    position: absolute;
    z-index: 2;
    font-family: 'Times New Roman', Times, serif;
    overflow: visible;
    white-space: normal;
    word-wrap: break-word;
    -webkit-font-smoothing: antialiased;
  }}
  span {{ display: inline; }}
</style>
</head>
<body>
  <div class="page">
    {paths_html}
    {blocks_html}
  </div>
</body>
</html>"""



# python poc_render.py "Nsangou Ngapna et al._ASR_2024.pdf" 1
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python poc_render.py fichier.pdf [page]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    print(f"Traitement : {pdf_path} (Page {page_num})")
    
    # 1. Dimensions
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[page_num-1]
    w, h = page.get_width(), page.get_height()
    doc.close()

    # 2. Données & Image
    png_b64 = page_to_png_base64(pdf_path, page_num)
    blocks_data, paths_data = extract_blocks(pdf_path, page_num)
    
    # 3. HTML
    final_html = generate_html(png_b64, blocks_data, paths_data, w, h)
    
    out = f"poc_page_{page_num}.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(final_html)
    
    print(f"✅ Terminé : {out}")