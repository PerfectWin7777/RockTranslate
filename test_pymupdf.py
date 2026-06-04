"""
test_piste_b_french_llm.py — Version Alignement Absolu Ligne par Ligne
Reconstruit la mise en page à l'identique en superposant une div par ligne physique.
Normalise les polices par bloc sémantique et ajuste la taille du texte dynamiquement pour éviter les débordements.
"""
from itertools import groupby
import fitz
import os
import base64
import re
import json
import statistics
import webbrowser
from collections import defaultdict, Counter
from dotenv import load_dotenv

# Imports de votre projet
from translation.llm_client import LLMClient
from core.domain import FitzBlock, FitzLine, FitzSpan
from core.cid_normalizer import build_cid_maps, normalize_cids

load_dotenv()

PDF_PATH = "1_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
PAGE_IDX = 0
TARGET_LANG = "French"
MODEL_NAME = "gemini/gemini-3.1-flash-lite"

# ─────────────────────────────────────────────────────────────
# 1. ENGIN DE NORMALISATION ET NETTOYAGE DES STYLES
# ─────────────────────────────────────────────────────────────

def clean_font_family(font_name: str) -> str:
    if "+" in font_name:
        font_name = font_name.split("+", 1)[1]
    font_lower = font_name.lower()
    if "times" in font_lower or "nimbusrom" in font_lower or "serif" in font_lower:
        return "'Times New Roman', Times, serif"
    if "arial" in font_lower or "helvetica" in font_lower or "sans" in font_lower:
        return "Arial, Helvetica, sans-serif"
    return "Arial, Helvetica, sans-serif"


# ─────────────────────────────────────────────────────────────
# 2. GROUPEMENT SÉMANTIQUE DES LIGNES (Pour l'uniformisation)
# ─────────────────────────────────────────────────────────────

def should_group_lines(line_a: dict, line_b: dict) -> bool:
    """Détermine si deux lignes physiques appartiennent au même bloc sémantique (style commun)."""
    # Identifier la ligne du haut et du bas
    if line_a["y0"] <= line_b["y0"]:
        top, bot = line_a, line_b
    else:
        top, bot = line_b, line_a
        
    v_gap = bot["y0"] - top["y1"]
    line_h = max(top["height"], bot["height"])
    
    # 1. Vérification de l'écart vertical (écart max toléré de 1.5 fois la hauteur de ligne)
    if v_gap < -2.0:  # Légère superposition verticale (ex: indices, exposants)
        h_gap = max(0.0, max(top["x0"], bot["x0"]) - min(top["x1"], bot["x1"]))
        return h_gap < 40.0
        
    if v_gap > line_h * 1.5:
        return False
        
    # 2. Vérification de l'alignement horizontal
    overlap_x = min(top["x1"], bot["x1"]) - max(top["x0"], bot["x0"])
    if overlap_x > 0:  # Les lignes se chevauchent horizontalement (même colonne)
        return True
        
    # Si elles ne se chevauchent pas, elles doivent être très proches horizontalement
    h_gap = max(top["x0"], bot["x0"]) - min(top["x1"], bot["x1"])
    if h_gap < 15.0:
        return True
        
    return False


def cluster_lines_into_blocks(lines: list) -> list[list[dict]]:
    """Groupe les lignes physiques en blocs sémantiques homogènes (Union-Find / Connexité)."""
    n = len(lines)
    adj = defaultdict(list)
    
    for i in range(n):
        for j in range(i + 1, n):
            if should_group_lines(lines[i], lines[j]):
                adj[i].append(j)
                adj[j].append(i)
                
    visited = set()
    grouped_blocks = []
    
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
            grouped_blocks.append(component)
            
    return grouped_blocks


# ─────────────────────────────────────────────────────────────
# 3. ORCHESTRATEUR PRINCIPAL ET APPEL API
# ─────────────────────────────────────────────────────────────

def run_absolute_translation_test():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("❌ Erreur : Clé API manquante dans votre .env")
        return

    print("📖 Ouverture du document...")
    doc = fitz.open(PDF_PATH)
    page = doc[PAGE_IDX]

    page_w = page.rect.width
    page_h = page.rect.height
    rot_matrix = page.rotation_matrix

    # Lecture des CID Maps de la page pour la normalisation
    print("🎯 Construction de la table CID d'origine...")
    cid_maps = build_cid_maps(doc)

    for word in page.get_text("words"):
        page.draw_rect(fitz.Rect(word[0], word[1], word[2], word[3]),
                   color=(1, 1, 1), fill=(1, 1, 1))

    # Image de fond base64
    pix = page.get_pixmap(matrix=fitz.Matrix(150/72.0, 150/72.0))
    png_b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")

    # Extraction brute de la structure dict de PyMuPDF
    text_dict = page.get_text("dict")
    extracted_lines = []
    line_idx_counter = 0

    print("🧩 Extraction des lignes physiques du PDF...")
    for b in text_dict.get("blocks", []):
        if b.get("type") != 0:  # On ignore les images ou vecteurs
            continue
            
        for l in b.get("lines", []):
            lx0, ly0, lx1, ly1 = l["bbox"]
            # Application de la matrice de rotation
            rect = fitz.Rect(lx0, ly0, lx1, ly1) * rot_matrix
            rx0, ry0, rx1, ry1 = rect.x0, rect.y0, rect.x1, rect.y1
            
            line_texts = []
            span_fonts = []
            span_sizes = []
            span_colors = []
            is_bold_flags = []
            is_italic_flags = []
            
            for span in l.get("spans", []):
                font_name = span.get("font", "Times New Roman")
                font_size = span.get("size", 9.0)
                color_int = span.get("color", 0)
                flags = span.get("flags", 0)
                
                # Conversion couleur entière vers CSS
                r_col = (color_int >> 16) & 0xFF
                g_col = (color_int >> 8) & 0xFF
                b_col = color_int & 0xFF
                color_css = f"rgb({r_col},{g_col},{b_col})"
                
                font_lower = font_name.lower()
                is_bold = bool(flags & 16) or any(x in font_lower for x in ["bold", "black", "heavy", "-b"])
                is_italic = bool(flags & 2) or any(x in font_lower for x in ["italic", "oblique", "-i"])
                
                # Normalisation CID
                normalized_span_text = normalize_cids(span["text"], font_name, cid_maps)
                line_texts.append(normalized_span_text)
                
                span_fonts.append(font_name)
                span_sizes.append(font_size)
                span_colors.append(color_css)
                is_bold_flags.append(is_bold)
                is_italic_flags.append(is_italic)
                
            full_line_text = "".join(line_texts)
            full_line_text = re.sub(r'\s+', ' ', full_line_text).strip()
            
            if not full_line_text:
                continue
                
            # Propriétés dominantes de la ligne physique
            line_font = Counter(span_fonts).most_common(1)[0][0] if span_fonts else "Times New Roman"
            line_size = statistics.median(span_sizes) if span_sizes else 9.0
            line_color = Counter(span_colors).most_common(1)[0][0] if span_colors else "rgb(0,0,0)"
            line_bold = any(is_bold_flags)
            line_italic = any(is_italic_flags)
            
            extracted_lines.append({
                "line_id": line_idx_counter,
                "x0": rx0,
                "y0": ry0,
                "x1": rx1,
                "y1": ry1,
                "width": rx1 - rx0,
                "height": ry1 - ry0,
                "text": full_line_text,
                "font_name": line_font,
                "font_size": line_size,
                "color": line_color,
                "is_bold": line_bold,
                "is_italic": line_italic,
                "block_id": None,
            })
            line_idx_counter += 1
    

    
    print(f"📦 Groupement et uniformisation des styles...")
    grouped_blocks = cluster_lines_into_blocks(extracted_lines)
    
    for idx, block_lines in enumerate(grouped_blocks):
        fonts = [l["font_name"] for l in block_lines]
        sizes = [l["font_size"] for l in block_lines]
        colors = [l["color"] for l in block_lines]
        
        dom_font = Counter(fonts).most_common(1)[0][0] if fonts else "Times New Roman"
        dom_size = statistics.median(sizes) if sizes else 9.0
        dom_color = Counter(colors).most_common(1)[0][0] if colors else "rgb(0,0,0)"
        
        # Réassignation uniforme du style de bloc sémantique
        for l in block_lines:
            l["block_id"] = idx
            l["block_font_name"] = dom_font
            l["block_font_size"] = dom_size
            l["block_color"] = dom_color

  

    # Préparation du lot de traduction
    batch_data = [
        {"id": f"LINE_ID_{line['line_id']:04d}", "text": line["text"]}
        for line in extracted_lines
    ]

    # Préparation du lot de traduction
    print(f"🚀 Traduction de {len(extracted_lines)} lignes physiques via {MODEL_NAME}...")
    client = LLMClient(model=MODEL_NAME, api_key=api_key, target_lang=TARGET_LANG)
    raw_results = client._call_llm(batch_data)

    # Réassociation des traductions
    line_map = {l["line_id"]: l for l in extracted_lines}
    received_count = 0

    if raw_results:
        for res in raw_results:
            res_id = str(res.get("id", ""))
            translated = (
                res.get("translated") or res.get("translated_text") or res.get("translation") or ""
            ).strip()

            digits = re.findall(r'\d+', res_id)
            if digits and translated:
                line_num = int(digits[0])
                if line_num in line_map:
                    line_map[line_num]["translated_text"] = translated
                    received_count += 1

    # Sécurité anti-disparition : repli sur l'anglais si nécessaire
    for l in extracted_lines:
        if "translated_text" not in l or not l["translated_text"] or "[TRANSLATION FAILED]" in l["translated_text"]:
            l["translated_text"] = l["text"]

    print(f"✅ Reçu {received_count}/{len(extracted_lines)} lignes traduites.")

    page_center   = page_w / 2.0
    col_left_max  = max((l['x1'] for l in extracted_lines if l['x1'] < page_center), default=page_center)
    col_right_min = min((l['x0'] for l in extracted_lines if l['x0'] > page_center), default=page_center)

    # Détection par bandes Y — chaque ligne sait si elle est en zone 1col ou 2col
    BAND_HEIGHT = 50.0
    y_min = min(l['y0'] for l in extracted_lines)
    y_max = max(l['y1'] for l in extracted_lines)

    band_layout = {}  # y_band → "one_col" ou "two_col"
    y = y_min
    while y < y_max:
        band_lines = [l for l in extracted_lines if y <= l['y0'] < y + BAND_HEIGHT]
        if band_lines:
            crossing = [l for l in band_lines if l['x0'] < page_center and l['x1'] > page_center]
            ratio = len(crossing) / len(band_lines)
            band_layout[y] = "one_col" if ratio > 0.30 else "two_col"
        y += BAND_HEIGHT

    # Assigner le layout à chaque ligne
    for l in extracted_lines:
        band_y = min(band_layout.keys(), key=lambda y: abs(y - l['y0']))
        l['layout'] = band_layout[band_y]

    print(f"   Gouttière : gauche={col_left_max:.1f} droite={col_right_min:.1f}")
    print(f"   Bandes détectées : {dict(list(band_layout.items())[:5])}...")

    # ─────────────────────────────────────────────────────────────
    # 4. GÉNÉRATION DU HTML PAR POSITIONNEMENT ABSOLU ET COMPRESSION
    # ─────────────────────────────────────────────────────────────
    print("✍️  Reconstruction du document HTML à positionnement absolu...")
    lines_html_list = []

    
    for l in extracted_lines:
        text_orig = l["text"]
        text_trans = l["translated_text"]
        print(f"y0={l['y0']:.1f} x0={l['x0']:.1f} text='{l['text'][:30]}'")

        if not l.get("translated_text"):
                print(f"   LIGNE VIDE : id={l['line_id']} text='{l['text']}'")
        
        # Calcul du taux d'expansion de la traduction
        ratio = len(text_trans) / max(1, len(text_orig))
        
        base_size = l["font_size"]
        font_family = clean_font_family(l["font_name"])
        color = l["color"]
        font_weight = "bold" if l["is_bold"] else "normal"
        font_style = "italic" if l["is_italic"] else "normal"

        final_font_size = base_size
        transform_style = ""

        if ratio > 1.0:
            final_font_size = base_size / ratio
            final_font_size = max(6.0, final_font_size)
        
       

        # --- RE-CENTRAGE ET FORCE D'UNE HAUTEUR SÉCURISÉE ---
        # On calcule le centre de la ligne d'origine pour y centrer notre nouvelle boîte agrandie
        y_center = l['y0'] + (l['height'] / 2.0)
        final_height = max(l['height'], final_font_size * 1.1)
        final_top = y_center - (final_height / 2.0)

        # Marge interne d'effacement plus généreuse pour masquer tous les pixels parasites d'origine
        mask_padding_style = "padding: 1px 2px; margin: -1px -2px;"

        if l['layout'] == "one_col":
            effective_width = page_w - l['x0'] - 20
        else:
            if l['x1'] <= page_center:
                effective_width = col_left_max - l['x0']
            else:
                effective_width = l['x1'] - col_right_min
        effective_width = max(effective_width, 10)
        # print ('effective_width:', effective_width)
            

        line_div = f"""
        <div style="
            position: absolute;
            left: {l['x0']:.1f}px;
            top: {final_top:.1f}px;
            width: {effective_width:.1f}px;
            max-width: {effective_width:.1f}px;
            height: auto; 
            min-height: {final_height:.1f}px; 
            font-family: {font_family};
            font-size: {final_font_size:.2f}px;
            font-weight: {font_weight};
            font-style: {font_style};
            color: {color};
            background-color: transparent  !important;
            white-space: nowrap;
            overflow: visible !important; 
            display: flex;
            align-items: center;
            {mask_padding_style}
            {transform_style}
        ">{text_trans}</div>"""
        
        lines_html_list.append(line_div)

    lines_html = "".join(lines_html_list)

    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #2b2e3c;
            display: flex;
            justify-content: center;
            padding: 20px;
        }}
        .page-container {{
            position: relative;
            width: {int(page_w)}px;
            height: {int(page_h)}px;
            background-image: url('data:image/png;base64,{png_b64}');
            background-size: {int(page_w)}px {int(page_h)}px;
            background-repeat: no-repeat;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            overflow: hidden;
        }}
    </style>
</head>
<body>
    <div class="page-container">
        {lines_html}
    </div>
</body>
</html>
"""

    output_path = "test_piste_b_traduit_fr.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"\n🎉 Traduction terminée ! Document sauvegardé sous '{output_path}'.")
    doc.close()
    
    # Ouverture automatique du navigateur
    webbrowser.open(output_path)

if __name__ == "__main__":
    run_absolute_translation_test()