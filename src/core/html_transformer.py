"""
RockTranslate — High-Fidelity Geometry-Based HTML Parser and Transformer
Path: core/html_transformer.py

This module executes high-fidelity semantic reconstruction of PDF layouts:
1. Converts PDF documents to raw HTML utilizing local pdf2htmlEX engines.
2. Parses unscaled CSS transform matrices and dynamic spacer properties.
3. Applies a scaled hybrid grouping algorithm to prevent word fragmentation:
   - Identifies structural table breaks (scaled spaces >= THRESHOLD_PX).
   - Identifies real word spaces (2.5px <= scaled spaces < THRESHOLD_PX).
   - Identifies kerning/accent positioning (scaled spaces < 2.5px or negative),
     merging diacritics (like Moïse, Sébastien) cleanly without injecting gaps.

Author: RockTranslate Contributors
License: MIT License
Version: 1.0.0
"""

import os
import re
import subprocess
from typing import Callable, Optional, Dict, Tuple, List, Set, Any
from bs4 import BeautifulSoup, NavigableString
from loguru import logger

# Safe fallback imports supporting both standard package modules and direct scripts
try:
    from core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from utils.downloader import check_and_download_pdf2htmlex
except ImportError:
    from src.core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from src.utils.downloader import check_and_download_pdf2htmlex


def convert_pdf_to_html(
    pdf_path: str, 
    assets_dir: str = DEFAULT_ASSETS_DIR, 
    on_progress: Optional[Callable[[int, int], None]] = None
) -> Optional[str]:
    """
    Converts a source PDF into raw HTML using the local pdf2htmlEX executable,
    tracking page compilation progress in real-time.

    Args:
        pdf_path: The filesystem path to the target PDF file.
        assets_dir: Assets folder storing the external pdf2htmlEX compiler.
        on_progress: Optional callback progress tracker (current_page, total_pages).

    Returns:
        Optional[str]: Absolute path to the generated raw HTML, or None.
    """
    pdf2htmlex_exe = check_and_download_pdf2htmlex(assets_dir)
    if not pdf2htmlex_exe:
        logger.error("pdf2htmlEX executable could not be resolved.")
        return None

    pdf_dir: str = os.path.dirname(os.path.abspath(pdf_path))
    pdf_filename: str = os.path.basename(pdf_path)
    html_filename: str = f"{os.path.splitext(pdf_filename)[0]}_raw.html"
    output_html_path: str = os.path.join(pdf_dir, html_filename)

    # Bypass compilation if raw HTML is already generated on disk
    if os.path.exists(output_html_path):
        logger.info(f"Raw HTML already exists. Skipping compilation for: {pdf_filename}")
        return output_html_path

    cmd: List[str] = [
        os.path.abspath(pdf2htmlex_exe),
        "--zoom", "1.3",
        pdf_filename,
        html_filename
    ]
    
    logger.info(f"Starting high-fidelity conversion of PDF: {pdf_filename}")
    
    # Execute pdf2htmlEX in a background process
    process = subprocess.Popen(
        cmd, cwd=pdf_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    # Read the stderr stream in real-time to intercept page processing progress
    while True:
        line = process.stderr.readline() if process.stderr else ""
        if not line and process.poll() is not None:
            break
        
        # Intercept pdf2htmlEX syntax output: "Working: 1/12"
        if "Working:" in line:
            match = re.search(r"Working:\s*(\d+)/(\d+)", line)
            if match and on_progress:
                current_page = int(match.group(1))
                total_pages = int(match.group(2))
                on_progress(current_page, total_pages)

    process.wait()
    if process.returncode == 0 and os.path.exists(output_html_path):
        logger.info("Raw HTML file generated successfully.")
        return output_html_path
        
    logger.error(f"pdf2htmlEX exited with error code: {process.returncode}")
    return None


def parse_matrix_classes(soup: BeautifulSoup) -> Dict[str, Tuple[float, float]]:
    """
    Parses unscaled CSS transform matrix properties from style tags.
    (e.g., .m0 { transform: matrix(0.125, 0, 0, 0.125, 0, 0); } -> {'m0': (0.125, 0.125)})

    Args:
        soup: BeautifulSoup object parsed from raw HTML.

    Returns:
        Dict[str, Tuple[float, float]]: Mapping of matrix classes to (scaleX, scaleY) factors.
    """
    matrix_map: Dict[str, Tuple[float, float]] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        for m in re.finditer(
            r'\.(m\w+)\{transform:matrix\(([\d.]+),[\d.]+,[\d.]+,([\d.]+),', text
        ):
            cls: str = m.group(1)
            sx: float = float(m.group(2))
            sy: float = float(m.group(3))
            matrix_map[cls] = (sx, sy)
    return matrix_map


def parse_spacer_widths(soup: BeautifulSoup) -> Dict[str, float]:
    """
    Parses spacer widths from raw CSS style tags.
    Corrected pattern to support negative values (e.g., ._19 { width: -15.123px; }).

    Args:
        soup: BeautifulSoup object parsed from raw HTML.

    Returns:
        Dict[str, float]: Mapping of spacer class indices to raw width values.
    """
    spacer_map: Dict[str, float] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        # Added optional sign '-?' to capture negative diacritics reposition spacers
        for m in re.finditer(r'\._(\w+)\s*\{\s*width\s*:\s*(-?[\d\.]+)\s*px\s*;?\s*\}', text):
            cls: str = m.group(1)
            width: float = float(m.group(2))
            spacer_map[cls] = width
    return spacer_map


def parse_position_classes(soup: BeautifulSoup) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Parses unscaled CSS coordinates from style tags to understand visual layout.
    Extracts x classes (.x1 { left: 85px; }) and y classes (.y1 { bottom: 234px; })
    """
    x_map: Dict[str, float] = {}
    y_map: Dict[str, float] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        for m in re.finditer(r'\.(x\w+)\s*\{\s*(?:left|margin-left)\s*:\s*([\d\.-]+)\s*px', text):
            x_map[m.group(1)] = float(m.group(2))
        for m in re.finditer(r'\.(y\w+)\s*\{\s*(?:bottom|top|margin-bottom|margin-top)\s*:\s*([\d\.-]+)\s*px', text):
            y_map[m.group(1)] = float(m.group(2))
    return x_map, y_map



def instrument_html(raw_html_path: str, output_html_path: str) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    Instruments the raw HTML layout by applying the high-fidelity scaled grouping algorithm.
    Groups words into sentences, segregates table columns, and embeds loading screens.

    Args:
        raw_html_path: Path to the raw compiled HTML file.
        output_html_path: Path where the instrumented HTML should be saved.

    Returns:
        Tuple[Dict[str, str], Dict[str, int]]:
            - original_texts_map: Map of unique translation IDs to unified text strings.
            - tid_to_page: Map of unique translation IDs to their zero-based page index.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    matrix_map: Dict[str, Tuple[float, float]] = parse_matrix_classes(soup)
    spacer_map: Dict[str, float] = parse_spacer_widths(soup)
    x_map, y_map = parse_position_classes(soup)
    pages_list = soup.find_all("div", class_="pf")
    

    original_texts_map: Dict[str, str] = {}
    tid_to_page: Dict[str, int] = {}
    idx: List[int] = [0]

    for page_idx, page_el in enumerate(pages_list):
        # 1. Collecter toutes les lignes de texte div_t de cette page
        div_t_elements = page_el.find_all("div", class_="t")
        
        # 2. Fonction d'aide pour extraire les coordonnées réelles de tri
        def get_div_sort_key(div_t_node: Any) -> Tuple[float, float]:
            classes = div_t_node.get("class", [])
            x_val = 0.0
            y_val = 0.0
            for cls in classes:
                if cls in x_map:
                    x_val = x_map[cls]
                if cls in y_map:
                    y_val = y_map[cls]
            # pdf2htmlEX utilise 'bottom' pour Y (le bas de page = 0).
            # Trier par -y_val ascendant permet d'obtenir un flux parfait de haut en bas.
            return -y_val, x_val

        # 3. Trier spatialement les lignes de texte (de haut en bas, de gauche à droite)
        sorted_div_t = sorted(div_t_elements, key=get_div_sort_key)

        # 4. Exécuter l'analyse géométrique dans l'ordre chronologique de lecture
        for div_t in sorted_div_t:
            # Déterminer les coefficients d'échelle d'origine (sx, sy) de la ligne
            classes = div_t.get("class", [])
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)
            div_t.clear()

            current_group_text: List[str] = []
            current_group_elements: List[Any] = []

            def commit_group() -> None:
                nonlocal current_group_text, current_group_elements
                if not current_group_elements:
                    return

                # Fuse the textual values gathered in the current group
                merged_text = "".join(current_group_text).strip()
                if merged_text:
                    gid = f"g-{idx[0]}"
                    original_texts_map[gid] = merged_text
                    tid_to_page[gid] = page_idx

                    # Copy font styles and color attributes from the children
                    inherited_classes = ["trans-span"]
                    for el in current_group_elements:
                        if hasattr(el, "get"):
                            el_classes = el.get("class", [])
                            for cls in el_classes:
                                if cls.startswith("fc") or cls.startswith("sc"):
                                    inherited_classes.append(cls)

                    # Wrap the unified group in a single localizable span
                    group_span = soup.new_tag("span", attrs={
                        "class": " ".join(inherited_classes),
                        "data-trans-id": gid,
                        "data-sx": str(sx_orig),
                        "data-sy": str(sy_orig),
                        "style": "display:inline;"
                    })
                    for el in current_group_elements:
                        group_span.append(el)
                    div_t.append(group_span)
                    idx[0] += 1
                else:
                    # Fallback for empty spaces or layout floats
                    for el in current_group_elements:
                        div_t.append(el)

                current_group_text.clear()
                current_group_elements.clear()

            # Iterate through DOM elements to apply scaled grouping
            for child in children:
                child_text = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                
                # Silently skip legacy PDF floating accents
                if child_text in ACCENTS_TO_IGNORE:
                    continue

                is_spacer = False
                width = 0.0

                if child.name == "span" and child.get("class"):
                    child_classes = child.get("class")
                    if "_" in child_classes:
                        is_spacer = True
                        for cls in child_classes:
                            if cls.startswith("_") and len(cls) > 1:
                                width = spacer_map.get(cls[1:], 0.0)
                                break

                if is_spacer:
                    # --- SCALED WIDTH CALCULATION (Core geometry fix) ---
                    scaled_width = width * sx_orig
                    
                    if scaled_width >= THRESHOLD_PX:
                        # Case 1: Structural spacing -> Commit active group and append Red Cut marker
                        commit_group()
                        div_t.append(child)
                    elif scaled_width >= 2.5:
                        # Case 2: Real word spacing -> Accumulate space and continue
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                    else:
                        # Case 3: Kerning / Accent adjustments -> Accumulate elements WITHOUT any space!
                        current_group_elements.append(child)
                else:
                    # Normal styled text spans or strings
                    if isinstance(child, str):
                        current_group_text.append(str(child))
                        current_group_elements.append(child)
                    else:
                        current_group_text.append(child.get_text())
                        current_group_elements.append(child)

            commit_group()

    # ── 2. EMBED GLASS OVERLAYS ON ALL PAGES ──
    for p_idx, page in enumerate(pages_list):
        glass_div = soup.new_tag("div", attrs={
            "id": f"glass-overlay-t-{p_idx}",
            "style": (
                "position: absolute; "
                "top: 5%; "
                "left: 5%; "
                "width: 90%; "
                "height: 90%; "
                "background: linear-gradient(135deg, rgba(255,255,255,0.45), rgba(255,255,255,0.15)); "
                "backdrop-filter: blur(18px); "
                "-webkit-backdrop-filter: blur(18px); "
                "border: 1px solid rgba(255,255,255,0.5); "
                "border-radius: 16px; "
                "box-shadow: 0 8px 32px rgba(31,38,135,0.25), 0 0 1px rgba(255,255,255,0.5); "
                "z-index: 1000; "
                "display: flex; "
                "justify-content: center; "
                "align-items: center; "
                "pointer-events: none;"
            )
        })

        inner_div = soup.new_tag("div", attrs={
            "style": (
                "background: rgba(255,255,255,0.92); "
                "padding: 24px 40px; "
                "border-radius: 12px; "
                "text-align: center; "
                "box-shadow: 0 10px 30px rgba(0,0,0,0.15); "
                "display: flex; "
                "flex-direction: column; "
                "align-items: center;"
            )
        })

        loader_div = soup.new_tag("div", attrs={"class": "circular-loader"})
        inner_div.append(loader_div)

        text_p = soup.new_tag("p", attrs={
            "style": "color:#1e293b; font-size:14px; font-weight:600; margin:0; font-family: sans-serif;"
        })
        text_p.string = "En attente de traduction..."
        inner_div.append(text_p)

        glass_div.append(inner_div)
        page.append(glass_div)

    # ── 3. INJECT STYLESHEET RULES (Shimmers, Spinners) ──
    style_tag = soup.new_tag("style")
    style_tag.string = """
        #sidebar { display: none !important; }
        #page-container { left: 0 !important; margin: 0 auto !important; }

        span[data-trans-id] {
            word-spacing: 0.25em !important;
        }

        @keyframes loading-shimmer {
            0%   { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        .shimmer-line {
            display: inline-block !important;
            background: linear-gradient(90deg, #f1f5f9 25%, #cbd5e1 50%, #f1f5f9 75%) !important;
            background-size: 200% 100% !important;
            animation: loading-shimmer 1.8s infinite linear !important;
            border-radius: 2px !important;
            color: transparent !important;
            min-width: 15px;
        }
        .shimmer-line * { color: transparent !important; }

        .circular-loader {
            border: 4px solid #f3f4f6 !important;
            border-top: 4px solid #4f8ef7 !important;
            border-radius: 50% !important;
            width: 36px !important; height: 36px !important;
            animation: spin 1s linear infinite !important;
            margin-bottom: 12px !important;
        }
        @keyframes spin {
            0%   { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    """
    soup.head.append(style_tag)

    # ── 4. INJECT CLIENT JAVASCRIPT ACTIONS (DOM streams & dynamic page resets) ──
    script_tag = soup.new_tag("script")
    script_tag.string = """
        window.applyTranslation = function(transId, translatedText) {
            var span = document.querySelector('[data-trans-id="' + transId + '"]');
            if (!span) return;
            var divT = span.closest('div.t');
            if (!divT) return;

            var sxOrig = parseFloat(span.getAttribute('data-sx') || '1');
            var syOrig = parseFloat(span.getAttribute('data-sy') || '1');

            if (!divT.hasAttribute('data-orig-sw')) {
                divT.style.transform = 'matrix(' + sxOrig + ',0,0,' + syOrig + ',0,0)';
                divT.setAttribute('data-orig-sw', divT.scrollWidth);
                divT.setAttribute('data-sx-orig', sxOrig);
                divT.setAttribute('data-sy-orig', syOrig);
            }

            var origSW = parseFloat(divT.getAttribute('data-orig-sw'));
            var sx     = parseFloat(divT.getAttribute('data-sx-orig'));
            var sy     = parseFloat(divT.getAttribute('data-sy-orig'));

            span.textContent = translatedText;
            span.classList.remove('shimmer-line');

            var newSW = divT.scrollWidth;
            if (newSW > 0 && origSW > 0) {
                var newSx = sx * (origSW / newSW);
                newSx = Math.min(newSx, sx);
                divT.style.transform = 'matrix(' + newSx + ',0,0,' + sy + ',0,0)';
            }
        };

        window.preparePageForTranslation = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (glass) {
                glass.style.transition = 'opacity 0.3s ease-out';
                glass.style.opacity = '0';
                setTimeout(function() { glass.style.display = 'none'; }, 300);
            }

            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.add('shimmer-line');
            });
        };

        window.resetPageToWaiting = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.remove('shimmer-line');
            });

            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (!glass) {
                glass = document.createElement('div');
                glass.id = 'glass-overlay-t-' + pageIdx;
                glass.style.cssText = "position: absolute; top: 5%; left: 5%; width: 90%; height: 90%; background: linear-gradient(135deg, rgba(255,255,255,0.45), rgba(255,255,255,0.15)); backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px); border: 1px solid rgba(255,255,255,0.5); border-radius: 16px; box-shadow: 0 8px 32px rgba(31,38,135,0.25), 0 0 1px rgba(255,255,255,0.5); z-index: 1000; display: flex; justify-content: center; align-items: center; pointer-events: none;";
                
                var inner = document.createElement('div');
                inner.style.cssText = "background: rgba(255,255,255,0.92); padding: 24px 40px; border-radius: 12px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.15); display: flex; flex-direction: column; align-items: center;";
                
                var loader = document.createElement('div');
                loader.className = 'circular-loader';
                
                var text_p = document.createElement('p');
                text_p.style.cssText = "color:#1e293b; font-size:14px; font-weight:600; margin:0; font-family: sans-serif;";
                text_p.textContent = "En attente de traduction...";
                
                inner.appendChild(loader);
                inner.appendChild(text_p);
                glass.appendChild(inner);
                page.appendChild(glass);
            } else {
                glass.style.display = 'flex';
                glass.style.opacity = '1';
            }
        };

        window.addEventListener('message', function(event) {
            var msg = event.data;
            if (!msg) return;

            if (msg.action === 'applyTranslation') {
                window.applyTranslation(msg.transId, msg.translatedText);
            } else if (msg.action === 'preparePage') {
                window.preparePageForTranslation(msg.pageIdx);
            } else if (msg.action === 'resetPage') {
                window.resetPageToWaiting(msg.pageIdx);
            }
        });
    """
    soup.body.append(script_tag)

    # ── 5. SAVE INSTRUMENTED HTML ──
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map, tid_to_page