# src/reconstruction/latex_builder.py
#
# Responsabilité unique : recevoir les lignes traduites d'une page
# et produire un PDF compilé via pdflatex.
#
# Aucune dépendance UI — pas de signaux Qt, pas de Chromium.
# Appelé par TranslationWorker quand une page est entièrement traduite.
# ─────────────────────────────────────────────────────────────────────────────

import os
import re
import subprocess
import tempfile
import time
from loguru import logger

from core.domain import FitzBlock

def fitzpage_to_lines_data(fitz_page) -> list[dict]:
    """
    Convertit une FitzPage en liste de dicts compatibles avec latex_builder.
    Seules les lignes ayant une traduction sont incluses.
    """
   

    lines = []

    for block in fitz_page.blocks:
        if not isinstance(block, FitzBlock):
            continue

        # Couleur de fond du bloc — convertie en hex 6 chiffres pour LaTeX
        bg_color = None
        raw_bg   = getattr(block, "bg_color", None)
        if raw_bg and raw_bg not in ("white", "transparent", None):
            # raw_bg est "rgb(r,g,b)" → on extrait les composantes
            try:
                parts  = raw_bg.replace("rgb(", "").replace(")", "").split(",")
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                # Ignore les fonds quasi-blancs
                if not (r > 240 and g > 240 and b > 240):
                    bg_color = f"{r:02x}{g:02x}{b:02x}"
            except Exception:
                bg_color = None

        for line in block.lines:
            if not line.translated_text or not line.translated_text.strip():
                continue

            sizes = [s.font_size for s in line.spans if s.font_size]
            font_size = sorted(sizes)[len(sizes) // 2] if sizes else 9.0

            lines.append({
                "left":                    line.left,
                "top":                     line.top,
                "width":                   line.right - line.left,
                "height":                  line.bottom - line.top,
                "font_size":               font_size,
                "translated_styled_text":  line.translated_text,
                "bg_color":                bg_color,
            })

    return lines



# ═══════════════════════════════════════════════════════════════════════════════
# 1. HELPERS LATEX
# ═══════════════════════════════════════════════════════════════════════════════

def fix_math_symbols(text: str) -> str:
    """Remplace les symboles Unicode mathématiques par leurs équivalents LaTeX."""
    replacements = {
        '≤': '$\\leq$',    '≥': '$\\geq$',
        '≠': '$\\neq$',    '≈': '$\\approx$',
        '∞': '$\\infty$',  '±': '$\\pm$',
        '×': '$\\times$',  '÷': '$\\div$',
        '∑': '$\\sum$',    '∏': '$\\prod$',
        '∫': '$\\int$',    '√': '$\\sqrt{}$',
        'α': '$\\alpha$',  'β': '$\\beta$',
        'γ': '$\\gamma$',  'δ': '$\\delta$',
        'λ': '$\\lambda$', 'μ': '$\\mu$',
        'π': '$\\pi$',     'σ': '$\\sigma$',
        'θ': '$\\theta$',  '°': '$^{\\circ}$',
        '→': '$\\to$',     '←': '$\\leftarrow$',
        '↑': '$\\uparrow$','↓': '$\\downarrow$',
        '∈': '$\\in$',     '∉': '$\\notin$',
        '⊂': '$\\subset$', '∩': '$\\cap$',
        '∪': '$\\cup$',    '∀': '$\\forall$',
        '∃': '$\\exists$', '∂': '$\\partial$',
        '·': '$\\cdot$',   '−': '$-$',
    }
    for char, latex in replacements.items():
        text = text.replace(char, latex)
    return text


def escape_latex(text: str) -> str:
    """Échappe les caractères spéciaux LaTeX dans le texte brut."""
    special = {
        '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
        '_': r'\_', '{': r'\{', '}': r'\}',
        '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
        '\\': r'\textbackslash{}',
    }
    return "".join(special.get(c, c) for c in text)


def convert_style_tags_to_latex(styled_text: str) -> str:
    """
    Convertit les balises HTML-style en commandes LaTeX.
    Balises supportées : <b>, <i>, <sup>, <color_HEX>, <fs_N>
    Le texte brut est d'abord échappé puis les symboles math sont substitués.
    """
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
            # Échappe d'abord, puis substitue les symboles math
            out.append(fix_math_symbols(escape_latex(p)))
    return "".join(out)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. GÉOMÉTRIE DES COLONNES
# ═══════════════════════════════════════════════════════════════════════════════

def detect_column_layout(lines_data: list[dict], page_w: float) -> dict:
    """
    Détecte si la page est en 1 ou 2 colonnes et calcule les limites.
    lines_data : liste de dicts avec keys 'left', 'width', 'top', 'height'
    """
    page_center = page_w / 2.0

    crossing = [
        l for l in lines_data
        if l["left"] < page_center < l["left"] + l["width"]
    ]
    ratio = len(crossing) / max(len(lines_data), 1)

    if ratio > 0.30:
        page_right = max((l["left"] + l["width"]) for l in lines_data) if lines_data else page_w
        return {
            "layout":       "one_col",
            "page_center":  page_center,
            "col_left_max": page_right,
            "col_right_min": page_center,
            "page_right":   page_right,
        }

    left_lines  = [l for l in lines_data if l["left"] + l["width"] <= page_center + 10]
    right_lines = [l for l in lines_data if l["left"] >= page_center - 10]

    col_left_max  = max((l["left"] + l["width"]) for l in left_lines)  if left_lines  else page_center
    col_right_min = min(l["left"] for l in right_lines)                 if right_lines else page_center
    page_right    = max((l["left"] + l["width"]) for l in lines_data)  if lines_data  else page_w

    return {
        "layout":        "two_col",
        "page_center":   page_center,
        "col_left_max":  col_left_max,
        "col_right_min": col_right_min,
        "page_right":    page_right,
    }


def effective_col_width(line: dict, geo: dict) -> float:
    """Largeur maximale autorisée pour cette ligne dans sa colonne."""
    MARGIN = 14.0

    if geo["layout"] == "one_col":
        return max(geo["page_right"] - line["left"] - MARGIN, 10.0)

    line_mid = line["left"] + line["width"] / 2.0

    if line_mid < geo["page_center"]:
        if line["left"] + line["width"] > geo["col_left_max"]:
            return max(geo["page_right"] - line["left"] - MARGIN, 10.0)
        return max(geo["col_left_max"] - line["left"] - MARGIN, 10.0)
    else:
        return max(geo["page_right"] - line["left"] - MARGIN, 10.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. GÉNÉRATION DU .tex
# ═══════════════════════════════════════════════════════════════════════════════

def generate_page_latex(
    bg_image_path: str,
    page_w: float,
    page_h: float,
    lines_data: list[dict],
    output_dir: str,
) -> str:
    """
    Génère le fichier .tex pour une page.

    lines_data : liste de dicts avec keys :
        left, top, width, height, font_size,
        translated_styled_text, bg_color (optionnel)

    Retourne le chemin du fichier .tex généré.
    """
    geo = detect_column_layout(lines_data, page_w)
    logger.debug(
        f"Layout : {geo['layout']} | "
        f"col_left_max={geo['col_left_max']:.1f} | "
        f"page_right={geo['page_right']:.1f}"
    )

    preamble = (
        r"\documentclass{article}" + "\n"
        r"\usepackage[papersize={" + f"{page_w:.1f}pt,{page_h:.1f}pt" + r"},margin=0in]{geometry}" + "\n"
        r"\usepackage[absolute,overlay]{textpos}" + "\n"
        r"\usepackage{graphicx}" + "\n"
        r"\usepackage{eso-pic}" + "\n"
        r"\usepackage{xcolor}" + "\n"
        r"\usepackage{adjustbox}" + "\n"
        "\n"
        r"\textblockorigin{0pt}{0pt}" + "\n"
        r"\thispagestyle{empty}" + "\n"
        r"\pagestyle{empty}" + "\n"
        "\n"
        r"\AddToShipoutPictureBG*{" + "\n"
        r"    \AtPageLowerLeft{%" + "\n"
        r"        \includegraphics[width=\paperwidth,height=\paperheight]{"
        + os.path.basename(bg_image_path) +
        r"}%" + "\n"
        r"    }" + "\n"
        r"}" + "\n"
        "\n"
        r"\begin{document}" + "\n"
        r"\setlength{\baselineskip}{0pt}" + "\n"
        r"\setlength{\parindent}{0pt}" + "\n"
    )

    tex = preamble

    for line in lines_data:
        translated = line.get("translated_styled_text", "").strip()
        if not translated:
            continue

        left      = line["left"]
        top       = line["top"]
        height    = line["height"]
        font_size = line["font_size"]
        bg_color  = line.get("bg_color")

        max_w = effective_col_width(line, geo)

        # Compression Python-side
        trans_plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', translated)).strip()
        coeff       = 0.48 if geo["layout"] == "one_col" else 0.50
        estimated_w = len(trans_plain) * font_size * coeff

        if estimated_w > max_w * 1.15:
            python_scale = max(0.55, max_w / estimated_w)
        else:
            python_scale = 1.0

        latex_text = convert_style_tags_to_latex(translated)

        inner = (
            f"\\scalebox{{{python_scale:.3f}}}{{%\n"
            f"\\fontsize{{{font_size:.1f}pt}}{{{font_size*1.2:.1f}pt}}\\selectfont%\n"
            f"{latex_text}%\n"
            f"}}"
        )

        if bg_color:
            content = (
                f"\\colorbox[HTML]{{{bg_color}}}{{\\parbox{{{max_w:.1f}pt}}{{{inner}}}}}"
            )
        else:
            content = inner

        tex += (
            f"\\begin{{textblock*}}{{{max_w:.1f}pt}}({left:.1f}pt, {top:.1f}pt)%\n"
            f"\\noindent%\n"
            f"{content}%\n"
            f"\\end{{textblock*}}\n"
        )

    tex += "\n\\end{document}\n"

    tex_path = os.path.join(output_dir, "page.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex)

    return tex_path


# ═══════════════════════════════════════════════════════════════════════════════
# 4. COMPILATION
# ═══════════════════════════════════════════════════════════════════════════════

def compile_page(
    tex_path: str,
    output_dir: str,
    job_name: str = "page",
) -> str | None:
    """
    Compile le .tex avec pdflatex.
    Retourne le chemin du PDF généré, ou None si échec.
    """
    cwd      = os.path.abspath(output_dir)
    tex_file = os.path.basename(tex_path)
    pdf_out  = os.path.join(cwd, f"{job_name}.pdf")

    try:
        res = subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                f"-jobname={job_name}",
                tex_file,
            ],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if os.path.exists(pdf_out):
            if res.returncode != 0:
                logger.warning(f"pdflatex warnings pour {job_name} (voir .log)")
            else:
                logger.info(f"PDF compilé : {pdf_out}")
            return pdf_out
        else:
            logger.error(f"Échec compilation {job_name}")
            logger.debug(res.stdout[-1000:])
            return None

    except FileNotFoundError:
        logger.error("pdflatex introuvable — MiKTeX dans le PATH ?")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 5. API PUBLIQUE — appelée par TranslationWorker
# ═══════════════════════════════════════════════════════════════════════════════

def build_page_pdf(
    bg_image_path: str,
    page_w: float,
    page_h: float,
    lines_data: list[dict],
    output_dir: str,
    page_number: int = 1,
) -> str | None:
    """
    Point d'entrée principal.
    Génère le .tex et compile le PDF pour une page.

    Paramètres :
        bg_image_path : chemin du PNG de fond (texte masqué)
        page_w, page_h : dimensions de la page en points
        lines_data     : liste de dicts avec les lignes traduites
        output_dir     : dossier de sortie (doit exister)
        page_number    : numéro de page (pour nommer le fichier)

    Retourne le chemin du PDF compilé, ou None si échec.
    """
    os.makedirs(output_dir, exist_ok=True)

    job_name = f"page_{page_number:03d}"

    tex_path = generate_page_latex(
        bg_image_path=bg_image_path,
        page_w=page_w,
        page_h=page_h,
        lines_data=lines_data,
        output_dir=output_dir,
    )

    pdf_path = compile_page(
        tex_path=tex_path,
        output_dir=output_dir,
        job_name=job_name,
    )

    return pdf_path