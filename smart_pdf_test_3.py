"""
RockTranslate - PDF Reconstruction Engine v5
=============================================
Lessons learned from v1-v4:
  - Adv* CFF fonts: uninjectable (proprietary encoding)
  - insert_textbox() + different font metrics = empty pages
  - insert_text() with origin is the ONLY reliable method

New approach (what real tools like PDFMathTranslate actually do):
  1. Draw white rect over each span (cover the original text visually)
  2. insert_text() at the EXACT original origin point
  3. Font size slightly reduced (0.92x) to compensate for metric differences
  4. Times/Helv mapped from style flags — no fallback chains

Page rotation fix:
  - page.rotation=90 means the page coordinate system is rotated
  - For text that appears horizontal on screen (which is most text),
    line["dir"] in the rotated coordinate system is (0, -1) not (1, 0)
  - We must compensate: effective_rotate = line_angle - page_rotation

  
  RockTranslate - PDF Reconstruction Engine v6
=============================================
Key upgrade vs v5:
  - Tente d'extraire et réutiliser la font originale du PDF
  - fonttools convertit CFF → TTF (fix Elsevier Adv* fonts)
  - Fallback tiro/helv uniquement si extraction échoue
  - tmp_dir passé à reconstruct_page pour stocker les TTF convertis

"""

import fitz
import os
import math
import unicodedata
from loguru import logger
import tempfile
from pathlib import Path
from io import BytesIO

try:
    from fontTools.ttLib import TTFont
    FONTTOOLS_AVAILABLE = True
except ImportError:
    FONTTOOLS_AVAILABLE = False
    logger.warning("fonttools not installed — falling back to tiro/helv always")


# ---------------------------------------------------------------------------
# 1. FONT MAPPING 
# ---------------------------------------------------------------------------

def select_font(font_name: str, flags: int) -> str:
    """Map Adv* font name + flags to a fitz built-in."""
    n = font_name.lower()
    bold   = bool(flags & 16) or any(x in n for x in ["-b", "bold", "black", "psb"])
    italic = bool(flags & 2)  or any(x in n for x in ["-i", "ital", "obli"])
    serif  = any(x in n for x in ["epstim", "pstim", "tim", "roman", "serif"])
    if serif:
        if bold and italic: return "tibi"
        if bold:            return "tibo"
        if italic:          return "tiit"
        return "tiro"
    else:
        if bold and italic: return "hebi"
        if bold:            return "hebo"
        if italic:          return "heit"
        return "helv"
    
# ---------------------------------------------------------------------------
# 2. FONT EXTRACTION + CONVERSION
# ---------------------------------------------------------------------------
 
def extract_and_convert_fonts(
    page: fitz.Page,
    tmp_dir: Path,
) -> dict[str, Path]:
    """
    Extrait les fonts de la page.
    TTF/OTF → copie directe.
    CFF/Type1 → conversion via fonttools.
    Retourne {base_font_name -> ttf_path}
    """
    doc = page.parent
    result: dict[str, Path] = {}
 
    for font_info in page.get_fonts(full=True):
        xref      = font_info[0]
        full_name = font_info[3]
        base_name = full_name.split("+")[-1]
 
        if base_name in result or not xref:
            continue
 
        try:
            font_data  = doc.extract_font(xref)
            raw_bytes  = font_data[3] if font_data else None
            font_type  = (font_data[1] or "").lower()
 
            if not raw_bytes or len(raw_bytes) < 100:
                continue
 
            # Direct TTF/OTF
            if font_type in ("ttf", "otf", "truetype", "opentype"):
                p = tmp_dir / f"{base_name}.ttf"
                p.write_bytes(raw_bytes)
                result[base_name] = p
                logger.debug(f"  Direct TTF: {base_name}")
                continue
 
            # CFF/Type1 → fonttools
            if FONTTOOLS_AVAILABLE:
                try:
                    tt = TTFont(BytesIO(raw_bytes))
                    p = tmp_dir / f"{base_name}_conv.ttf"
                    tt.save(str(p))
                    result[base_name] = p
                    logger.debug(f"  CFF→TTF OK: {base_name}")
                except Exception as e:
                    logger.warning(f"  CFF→TTF failed {base_name}: {e}")
 
        except Exception as e:
            logger.warning(f"  extract_font error {base_name}: {e}")
 
    return result
 
 
def build_font_registry(
    page: fitz.Page,
    tmp_dir: Path,
) -> dict[str, str]:
    """
    Retourne {span_font_name -> fitz_registered_fontname}
    Priorité : font originale extraite > fallback tiro/helv
    """
    converted = extract_and_convert_fonts(page, tmp_dir)
    registry: dict[str, str] = {}
    counter = 0
 
    raw = page.get_text("rawdict")
    used: set[tuple] = set()
    for block in raw["blocks"]:
        if block["type"] == 0:
            for line in block["lines"]:
                for span in line["spans"]:
                    used.add((span["font"], span["flags"]))
 
    for font_name, flags in used:
        if font_name in registry:
            continue
 
        base = font_name.split("+")[-1]
        fitz_name = f"RF{counter}"
        counter += 1
        registered = False
 
        # Stratégie 1 : font originale convertie
        if base in converted:
            try:
                page.insert_font(
                    fontfile=str(converted[base]),
                    fontname=fitz_name,
                )
                registry[font_name] = fitz_name
                registered = True
                logger.debug(f"  Registered original: '{font_name}' → {fitz_name}")
            except Exception as e:
                logger.warning(f"  insert_font failed '{font_name}': {e}")
 
        # Stratégie 2 : fallback
        if not registered:
            registry[font_name] = select_font(font_name, flags)
            logger.debug(f"  Fallback: '{font_name}' → {registry[font_name]}")
 
    return registry
 
 
# ---------------------------------------------------------------------------
# 3. UTILITIES
# ---------------------------------------------------------------------------
 
 
def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    for k, v in {
        "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl",
"\u0131\u00a8": "ï",  # ı + ¨ → ï
"\u0131\u00b4": "í",  # ı + ´ → í
"\u2013": "-",   # – → -
"\u2014": "--",  # — → --
"\u00d7": "x",   # × → x
"\u00b7": ".",   # · → .
"\u21d1": "^",   # ⇑ → ^
        "\u223c": "~", "\u00b7": "·", "\u2022": "•", "\u2212": "-","\u00ef": "ï",  # garder ï — Times le supporte
        "\u00b1": "±", "\u2264": "≤", "\u2265": "≥", "\u00d7": "×",
        "\u00e9": "é", "\u00e8": "è","\u00ea": "ê","\u00e0": "à", "\u00e7": "ç",
"\u00e2": "â",
    }.items():
        text = text.replace(k, v)
    return text

# ---------------------------------------------------------------------------
# 2. ROTATION — the definitive fix
# ---------------------------------------------------------------------------

def compute_rotatess(page: fitz.Page, line_dir: tuple) -> int:
    """
    Returns the rotate= value for insert_text() that produces
    visually correct text orientation on screen.

    The key insight:
    - page.rotation=90 means the PDF viewer rotates the page 90° CW to display it
    - All coordinates in get_text() are in the RAW (unrotated) PDF space
    - line["dir"] in raw space for "visually horizontal" text on a 90° page = (0, -1)
    - insert_text(rotate=0) places text in the raw space left-to-right
    - We need rotate = (raw_angle - page_rotation) % 360

    Verified against log: page 5 rotation=90°
    """
     # Si la page est déjà rotée (paysage), on ignore la direction de ligne
    # et on laisse fitz placer le texte normalement dans l'espace de la page
    if page.rotation != 0:
        return 0
    
    page_rot = page.rotation

    # Raw angle in PDF coordinate space (Y axis points DOWN in PDF)
    raw_deg = math.degrees(math.atan2(line_dir[1], line_dir[0]))
    # Convert to CCW positive (fitz convention)
    raw_deg = (-raw_deg) % 360
    # Snap to 90° quadrant
    raw_snapped = round(raw_deg / 90) * 90 % 360

    # Subtract page rotation
    effective = (raw_snapped - page_rot) % 360
    return int(effective)

def compute_rotate(page: fitz.Page, line_dir: tuple) -> int:
    return page.rotation


def is_math_block(block: dict) -> bool:
    """Détecte si un bloc est une formule mathématique de manière statistique."""
    full_text = ""
    for line in block["lines"]:
        for span in line["spans"]:
            full_text += "".join(c["c"] for c in span["chars"])
    
    if not full_text.strip():
        return False

    # Caractères qui puent la corruption ou les maths pures
    math_symbols = {"∑", "∫", "√", "∞", "≈", "≠", "≤", "≥", "∂", "∆"}
    corrupt_char = "\ufffd"
    
    # 1. Compter les anomalies
    bad_count = full_text.count(corrupt_char)
    symbol_count = sum(1 for c in full_text if c in math_symbols)
    
    # 2. Calculer le ratio d'anomalie
    # Si plus de 30% du bloc est corrompu/symbole, c'est probablement une formule
    anomaly_ratio = (bad_count + symbol_count) / len(full_text)
    
    # 3. Vérifier la police (souvent les polices de maths ont 'Sym' ou 'Math' dans le nom)
    is_math_font = any("sym" in span["font"].lower() or "math" in span["font"].lower() 
                       for line in block["lines"] for span in line["spans"])

    if anomaly_ratio > 0.3 or is_math_font:
        return True
        
    return False

# ---------------------------------------------------------------------------
# 4. RECONSTRUCTION
# ---------------------------------------------------------------------------
 
def reconstruct_page(
    page: fitz.Page,
    tmp_dir: Path,
    text_override: dict | None = None,
) -> None:
 
    raw   = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    links = page.get_links()
 
    # Construire le registre de fonts pour cette page
    font_registry = build_font_registry(page, tmp_dir)
 
    # Pass 1 : collecter les spans
    spans_to_process = []
    for block in raw["blocks"]:
        if block["type"] != 0:
            continue
        
        # NOUVEAU : skip les blocs math
        if is_math_block(block):
            continue
            
        for line in block["lines"]:

            # On fusionne tous les spans de la ligne pour le LLM
            full_line_text = "".join("".join(c["c"] for c in s["chars"]) for s in line["spans"])
            full_line_text = clean_text(full_line_text).strip()
            
            if len(full_line_text) > 1: # On ignore les caractères isolés
                # --- LOG TEMPORAIRE POUR VOIR LE TEXTE ---
                logger.info(f" [A TRADUIRE] -> {full_line_text}")
                # -----------------------------------------

            angle = compute_rotate(page, line["dir"])
            for span in line["spans"]:
                raw_text = "".join(c["c"] for c in span["chars"])
                text = clean_text(
                    text_override.get(raw_text, raw_text)
                    if text_override else raw_text
                )
                if not text.strip():
                    continue

                bbox_mid_y = (span["bbox"][1] + span["bbox"][3]) / 2
                is_super   = span["origin"][1] < bbox_mid_y - span["size"] * 0.3

                spans_to_process.append({
                    "bbox":     fitz.Rect(span["bbox"]),
                    "origin":   list(span["origin"]),
                    "text":     text,
                    "font":     span["font"],
                    "flags":    span["flags"],
                    "size":     span["size"],
                    "color":    span["color"],
                    "angle":    angle,
                    "is_super": is_super,
                })

    # Pass 2 : couvrir avec rects blancs — bbox EXACT sans expansion
    # shape = page.new_shape()
    # for s in spans_to_process:
    #     r = s["bbox"]  # MODIFIÉ : plus d'expansion (+3, etc.)
    #     shape.draw_rect(r)
    #     shape.finish(fill=(1, 1, 1), color=(1, 1, 1), width=0)
    # shape.commit()

    for s in spans_to_process:
        page.add_redact_annot(s["bbox"]) # On marque la zone à effacer

    page.apply_redactions(images=0, graphics=0) # On efface le texte, mais ON GARDE les lignes du tableau (graphics=0)
 
    # Pass 3 : réécrire
    for s in spans_to_process:
        fontname = font_registry.get(s["font"], select_font(s["font"], s["flags"]))
 
        # Scale : pas de réduction si on a la font originale
        is_original = fontname.startswith("RF")
        if s["is_super"]:
            scale = 1.0
        elif is_original:
            scale = 1.0   # font originale → métriques exactes
        elif fontname in ("tiro", "tibo", "tiit", "tibi"):
            scale = 0.97
        else:
            scale = 0.92
 
        size = s["size"] * scale
 
        c = s["color"]
        rgb = (((c >> 16) & 0xFF) / 255,
               ((c >>  8) & 0xFF) / 255,
               ( c        & 0xFF) / 255)
 
        try:
            page.insert_text(
                s["origin"],
                s["text"],
                fontsize=size,
                fontname=fontname,
                color=rgb,
                rotate=s["angle"],
                overlay=True,
            )
        except Exception as e:
            logger.warning(f"  insert_text failed '{s['text'][:25]}': {e}")
 
    for link in links:
        try:
            page.insert_link(link)
        except Exception:
            pass
            
# ---------------------------------------------------------------------------
# 5. PIPELINE
# ---------------------------------------------------------------------------
 
def run_reconstruction(
    input_file: str,
    output_file: str,
    test_pages: list[int] | None = None,
    text_override: dict | None = None,
) -> bool:
 
    if not os.path.exists(input_file):
        logger.error(f"Not found: {input_file}")
        return False
 
    doc   = fitz.open(input_file)
    pages = test_pages if test_pages is not None else list(range(len(doc)))
 
    with tempfile.TemporaryDirectory(prefix="rocktranslate_") as tmp:
        tmp_dir = Path(tmp)
 
        for pno in pages:
            if pno >= len(doc):
                continue
            page = doc[pno]
            logger.info(f"Page {pno+1} | rotation={page.rotation}°")
            reconstruct_page(page, tmp_dir, text_override)
            logger.success(f"Page {pno+1} done")
    
    # for pno in test_pages:
    #     page = doc[pno]
    #     raw = page.get_text("rawdict")
    #     skipped = 0
    #     translated = 0
    #     for block in raw["blocks"]:
    #         if block["type"] != 0:
    #             continue
    #         if is_math_block(block):
    #             skipped += 1
    #             # Affiche le texte skippé pour vérifier
    #             text = " ".join(
    #                 "".join(c["c"] for c in s["chars"])
    #                 for line in block["lines"]
    #                 for s in line["spans"]
    #             )
    #             logger.debug(f"  SKIPPED: {text}")
    #         else:
    #             translated += 1
    #     logger.info(f"Page {pno+1}: {translated} blocs à traduire, {skipped} skippés")

    doc.save(output_file, garbage=1, deflate=False, clean=False)
    doc.close()
    logger.success(f"Output → {output_file}")
    return True
 
 
# ---------------------------------------------------------------------------
# 6. ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    
    run_reconstruction(
        input_file  = "Nsangou Ngapna et al._ASR_2024.pdf",
        # input_file  =r"C:\Users\TONY\Desktop\Dossiers\DOCUMENT OPEN  GL\scipy-ref.pdf",
        output_file = "RESULTAT_ROCK_V5.pdf",
        test_pages  = [0,1,2,3,4,5,6,7,8,9,10,12],
    )



