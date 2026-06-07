# tests_latex/test_latex_reconstruction.py  — v2 (column-aware)
#
# FIXES vs v1 :
#   1. Détection automatique de la frontière gauche/droite (page_center)
#   2. Chaque ligne est clampée à sa colonne réelle → plus de débordement
#   3. \resizebox contraint le texte dans la boîte (largeur ET hauteur max)
#   4. Fallback scalebox Python-side pour les textes très longs
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import subprocess
import sys
import fitz
from loguru import logger
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from translation.llm_client import LLMClient

load_dotenv()

CANDIDATES = [
     "1_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
     "1_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf",
    "2_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf",
    ]

PDF_PATH    = "2_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
PAGE_IDX    = 0
MODEL_NAME  = "gemini/gemini-3.1-flash-lite"
TARGET_LANG = "French"
OUTPUT_DIR  = "output_files"

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LATEX HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def escape_latex(text: str) -> str:
    special = {
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
        '_': r'\_', '{': r'\{', '}': r'\}',
        '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
        '\\': r'\textbackslash{}',
    }
    return "".join(special.get(c, c) for c in text)


def convert_style_tags_to_latex(styled_text: str) -> str:
    """HTML-style tags → LaTeX commands.  Plain text is latex-escaped."""
    if not styled_text:
        return ""
    parts = re.split(r'(</?[a-zA-Z0-9_]+(?:_[0-9a-fA-F]{6})?>)', styled_text)
    out = []
    for p in parts:
        if p.startswith("<") and p.endswith(">"):
            tag = p[1:-1]
            if tag.startswith("/"):
                out.append("}")
            elif tag == "b":
                out.append("\\textbf{")
            elif tag == "i":
                out.append("\\textit{")
            elif tag == "sup":
                out.append("\\textsuperscript{")
            elif tag.startswith("color_"):
                out.append(f"\\textcolor[HTML]{{{tag[6:]}}}{{")
            elif tag.startswith("fs_"):
                sz = tag[3:]
                out.append(f"\\fontsize{{{sz}}}{{{float(sz)*1.25:.1f}}}\\selectfont {{")
        else:
            out.append(escape_latex(p))
    return "".join(out)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. COLUMN GEOMETRY  ← NEW
# ═══════════════════════════════════════════════════════════════════════════════

def detect_column_layout(lines_data: list[dict], page_w: float) -> dict:
    """
    Analyse les lignes pour détecter si la page est en 1 ou 2 colonnes,
    et calcule les limites de chaque colonne.

    Retourne un dict :
        {
          "layout"       : "one_col" | "two_col",
          "page_center"  : float,          # frontière gauche/droite
          "col_left_max" : float,          # bord droit max de la colonne gauche
          "col_right_min": float,          # bord gauche min de la colonne droite
          "page_right"   : float,          # bord droit de la page (texte le plus à droite)
        }
    """
    page_center = page_w / 2.0

    # Lignes qui traversent le centre → probablement 1 colonne
    crossing = [l for l in lines_data if l["left"] < page_center < l["left"] + l["width"]]
    ratio = len(crossing) / max(len(lines_data), 1)

    if ratio > 0.30:
        # Page 1 colonne
        page_right = max((l["left"] + l["width"]) for l in lines_data) if lines_data else page_w
        return {
            "layout": "one_col",
            "page_center": page_center,
            "col_left_max": page_right,
            "col_right_min": page_center,
            "page_right": page_right,
        }

    # Page 2 colonnes
    left_lines  = [l for l in lines_data if l["left"] + l["width"] <= page_center + 10]
    right_lines = [l for l in lines_data if l["left"] >= page_center - 10]

    col_left_max  = max((l["left"] + l["width"]) for l in left_lines)  if left_lines  else page_center
    col_right_min = min(l["left"]                for l in right_lines) if right_lines else page_center
    page_right    = max((l["left"] + l["width"]) for l in lines_data)  if lines_data  else page_w

    return {
        "layout": "two_col",
        "page_center": page_center,
        "col_left_max": col_left_max,
        "col_right_min": col_right_min,
        "page_right": page_right,
    }


def effective_col_width(line: dict, geo: dict) -> float:
    """
    Retourne la largeur maximale autorisée pour cette ligne dans SA colonne.

    Colonne gauche  : de line["left"] jusqu'à col_left_max  (avec 4 pt de marge)
    Colonne droite  : de line["left"] jusqu'à page_right    (avec 4 pt de marge)
    Une seule colonne : de line["left"] jusqu'à page_right
    """
    MARGIN = 14.0   # points de sécurité pour éviter de toucher le bord

    if geo["layout"] == "one_col":
        return max(geo["page_right"] - line["left"] - MARGIN, 10.0)

    page_center = geo["page_center"]
    line_mid    = line["left"] + line["width"] / 2.0

    if line_mid < page_center:
        # Colonne gauche → ne pas dépasser col_left_max
        # return max(geo["col_left_max"] - line["left"] - MARGIN, 10.0)
        if line["left"] + line["width"] > geo["col_left_max"]:
            return max(geo["page_right"] - line["left"] - MARGIN, 10.0)
        return max(geo["col_left_max"] - line["left"] - MARGIN, 10.0)
    else:
        # Colonne droite → ne pas dépasser page_right
        return max(geo["page_right"] - line["left"] - MARGIN, 10.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. PDF EXTRACTION & BLANKING
# ═══════════════════════════════════════════════════════════════════════════════

def extract_and_blank_page(pdf_path: str, page_idx: int):
    doc  = fitz.open(pdf_path)
    page = doc[page_idx]
    page_w = page.rect.width
    page_h = page.rect.height
    rot    = page.rotation_matrix

    logger.info(f"Ouverture : {os.path.basename(pdf_path)}")
    lines_data = []
    text_dict  = page.get_text("dict")

    for b in text_dict.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            rect = fitz.Rect(l["bbox"]) * rot
            texts, colors, sizes, bolds, italics = [], [], [], [], []

            for span in l.get("spans", []):
                fn    = span.get("font", "").lower()
                flags = span.get("flags", 0)
                ci    = span.get("color", 0)
                r, g, b_ = (ci >> 16) & 0xFF, (ci >> 8) & 0xFF, ci & 0xFF
                texts.append(span.get("text", ""))
                colors.append(f"{r:02x}{g:02x}{b_:02x}")
                sizes.append(span.get("size", 9.0))
                bolds.append(bool(flags & 16) or any(x in fn for x in ["bold", "black", "-b"]))
                italics.append(bool(flags & 2)  or any(x in fn for x in ["italic", "oblique", "-i"]))

            full = " ".join(texts).strip()
            if not full:
                continue

            styled = full
            if any(bolds):   styled = f"<b>{styled}</b>"
            if any(italics): styled = f"<i>{styled}</i>"
            dom_color = colors[0] if colors else "000000"
            if dom_color != "000000":
                styled = f"<color_{dom_color}>{styled}</color_{dom_color}>"

            lines_data.append({
                "left":        rect.x0,
                "top":         rect.y0,
                "width":       rect.x1 - rect.x0,
                "height":      rect.y1 - rect.y0,
                "text":        full,
                "styled_text": styled,
                "font_size":   sizes[0] if sizes else 9.0,
            })

    # Blanking
    for word in page.get_text("words"):
        page.draw_rect(fitz.Rect(word[0], word[1], word[2], word[3]),
                       color=(1, 1, 1), fill=(1, 1, 1))

    bg_path = os.path.join(OUTPUT_DIR, "background_page.png")
    pix = page.get_pixmap(matrix=fitz.Matrix(150/72.0, 150/72.0))
    pix.save(bg_path)
    doc.close()
    return bg_path, page_w, page_h, lines_data


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LLM TRANSLATION
# ═══════════════════════════════════════════════════════════════════════════════

def translate_lines_with_llm(lines_data: list[dict]) -> list[dict]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        logger.warning("Clé API absente — traduction simulée.")
        for line in lines_data:
            line["translated_styled_text"] = f"[FR] {line['styled_text']}"
        return lines_data

    logger.info(f"Appel LLM {MODEL_NAME} — {len(lines_data)} lignes…")
    client     = LLMClient(model=MODEL_NAME, api_key=api_key, target_lang=TARGET_LANG)
    batch_data = [{"id": i, "text": l["styled_text"]} for i, l in enumerate(lines_data)]
    results    = client._call_llm(batch_data)

    translated = 0
    if results:
        for res in results:
            idx  = res.get("id")
            text = res.get("translated", "").strip()
            if idx is not None and 0 <= int(idx) < len(lines_data):
                lines_data[int(idx)]["translated_styled_text"] = text
                translated += 1

    for line in lines_data:
        if "translated_styled_text" not in line or not line["translated_styled_text"]:
            line["translated_styled_text"] = ""

    logger.info(f"✅ {translated}/{len(lines_data)} lignes traduites.")
    return lines_data


# ═══════════════════════════════════════════════════════════════════════════════
# 5. LATEX GENERATION  ← REWRITTEN
# ═══════════════════════════════════════════════════════════════════════════════

def generate_latex_document(
    bg_path: str,
    page_w: float,
    page_h: float,
    lines_data: list[dict],
) -> str:
    logger.info("Génération du LaTeX…")

    # ── Détection de la géométrie des colonnes ────────────────────────────────
    geo = detect_column_layout(lines_data, page_w)
    logger.info(
        f"Layout détecté : {geo['layout']} | "
        f"col_left_max={geo['col_left_max']:.1f} | "
        f"col_right_min={geo['col_right_min']:.1f} | "
        f"page_right={geo['page_right']:.1f}"
    )

    # ── Préambule ─────────────────────────────────────────────────────────────
    preamble = r"""\documentclass{article}
\usepackage[papersize={PAGE_Wpt,PAGE_Hpt},margin=0in]{geometry}
\usepackage[absolute,overlay]{textpos}
\usepackage{graphicx}
\usepackage{eso-pic}
\usepackage{xcolor}
\usepackage{adjustbox}

\textblockorigin{0pt}{0pt}
\thispagestyle{empty}
\pagestyle{empty}

\AddToShipoutPictureBG*{
    \AtPageLowerLeft{%
        \includegraphics[width=\paperwidth,height=\paperheight]{BG_FILENAME}%
    }
}

\begin{document}
\setlength{\baselineskip}{0pt}
\setlength{\parindent}{0pt}
"""
    tex  = preamble.replace("PAGE_W",      f"{page_w:.1f}")
    tex  = tex.replace     ("PAGE_H",      f"{page_h:.1f}")
    tex  = tex.replace     ("BG_FILENAME", os.path.basename(bg_path))

    # ── Lignes ────────────────────────────────────────────────────────────────
    for idx, line in enumerate(lines_data):
        translated = line.get("translated_styled_text", "").strip()
        if not translated:
            continue

        left      = line["left"]
        top       = line["top"]
        orig_w    = line["width"]
        height    = line["height"]
        font_size = line["font_size"]

        

        # ── Largeur contrainte par la colonne ─────────────────────────────────
        max_w = effective_col_width(line, geo)

        # Ratio de compression Python-side (évite que \resizebox écrase trop)
        # On estime la largeur du texte traduit en caractères × taille de police × 0.50
        trans_plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', translated)).strip()
        estimated_w = len(trans_plain) * font_size * 0.50

        if estimated_w > max_w* 1.15:
            # Compression amortie : on ne descend pas en dessous de 70 % de la taille orig
            python_scale = max(0.55, max_w / estimated_w)
            render_fs    = font_size * python_scale
        else:
            python_scale = 1.0
            render_fs    = font_size

        latex_text = convert_style_tags_to_latex(translated)

        # ── Hauteur de la boîte : original + 40 % de marge pour l'interligne ──
        box_h = max(height * 1.4, render_fs * 1.4)

        if "facteurs" in line.get("translated_styled_text", "").lower() or "degré de" in line.get("text", "").lower():
            print(f"texte={line.get("translated_styled_text", "")} left={line['left']:.1f} right={line['left']+line['width']:.1f} "
                f"max_w={max_w:.1f} font={font_size:.1f} "
                f"estimated={estimated_w:.1f} scale={python_scale:.2f} "
                f"layout={geo['layout']} col_left_max={geo['col_left_max']:.1f}")

        tex += f"""
\\begin{{textblock*}}{{{max_w:.1f}pt}}({left:.1f}pt, {top:.1f}pt)%
\\noindent%
\\scalebox{{{python_scale:.3f}}}{{%
\\fontsize{{{font_size:.1f}pt}}{{{font_size*1.2:.1f}pt}}\\selectfont%
{latex_text}%
}}%
\\end{{textblock*}}
"""

    tex += "\n\\end{document}\n"

    tex_path = os.path.join(OUTPUT_DIR, "document.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    logger.info(f"Fichier LaTeX écrit : {tex_path}")
    return tex_path


# ═══════════════════════════════════════════════════════════════════════════════
# 6. COMPILATION
# ═══════════════════════════════════════════════════════════════════════════════

def compile_latex(tex_path: str):
    logger.info("Compilation pdflatex…")
    cwd      = os.path.abspath(OUTPUT_DIR)
    tex_file = os.path.basename(tex_path)
    pdf_out  = os.path.join(cwd, "document.pdf")

    if os.path.exists(pdf_out):
        try: os.remove(pdf_out)
        except Exception: pass

    try:
        res = subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", tex_file],
            cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        if os.path.exists(pdf_out):
            logger.info(f"🎉 PDF généré : {pdf_out}")
            if res.returncode != 0:
                logger.warning("Avertissements mineurs (voir document.log).")
        else:
            logger.error("❌ Échec compilation — aucun PDF généré.")
            logger.error(res.stdout[-1500:])
    except FileNotFoundError:
        logger.error("❌ pdflatex introuvable. MiKTeX dans le PATH ?")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not os.path.exists(PDF_PATH):
        logger.error(f"PDF introuvable : {PDF_PATH}")
        sys.exit(1)

    bg, w, h, lines = extract_and_blank_page(PDF_PATH, PAGE_IDX)
    lines           = translate_lines_with_llm(lines)
    tex             = generate_latex_document(bg, w, h, lines)
    compile_latex(tex)