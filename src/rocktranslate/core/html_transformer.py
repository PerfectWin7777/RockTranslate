"""
RockTranslate — High-Fidelity Geometry-Based HTML Parser and Transformer
Path: src/rocktranslate/core/html_transformer.py

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

import os, sys
import re
import subprocess
import unicodedata
from typing import Callable, Optional, Dict, Tuple, List, Set, Any
from bs4 import BeautifulSoup, NavigableString
from loguru import logger

try:
    from PyQt6.QtCore import QSettings
except ImportError:
    QSettings = None
# Safe fallback imports supporting both standard package modules and direct scripts
from .constants import DEFAULT_ASSETS_DIR, ACCENTS_TO_IGNORE, THRESHOLD_PX
from .downloader import check_and_download_pdf2htmlex


def convert_pdf_to_html(
    pdf_path: str, 
    assets_dir: str = DEFAULT_ASSETS_DIR, 
    on_progress: Optional[Callable[[int, int], None]] = None
) -> Optional[str]:
    """
    Converts a source PDF into raw HTML using the local pdf2htmlEX executable.
    Implements a strict 45-second execution timeout to prevent the application
    from hanging indefinitely on complex LaTeX/arXiv mathematical documents [1].

    Args:
        pdf_path: The filesystem path to the target PDF file.
        assets_dir: Assets folder storing the external pdf2htmlEX compiler.
        on_progress: Optional callback progress tracker (current_page, total_pages).

    Returns:
        Optional[str]: Absolute path to the generated raw HTML, or None if failed/timed out.
    """
    pdf2htmlex_exe = check_and_download_pdf2htmlex(assets_dir)
    if not pdf2htmlex_exe:
        logger.error("pdf2htmlEX executable could not be resolved.")
        return None

    pdf_dir: str = os.path.dirname(os.path.abspath(pdf_path))
    pdf_filename: str = os.path.basename(pdf_path)
    html_filename: str = f"{os.path.splitext(pdf_filename)[0]}_raw.html"
    output_html_path: str = os.path.join(pdf_dir, html_filename)

    # Bypass compilation ONLY if raw HTML is already generated and is not empty
    if os.path.exists(output_html_path) and os.path.getsize(output_html_path) > 0:
        logger.info(f"Raw HTML already exists and is valid. Skipping compilation for: {pdf_filename}")
        return output_html_path

    cmd: List[str] = [
        os.path.abspath(pdf2htmlex_exe),
        "--zoom", "1.3",
        pdf_filename,
        html_filename
    ]
    
    logger.info(f"Starting high-fidelity conversion of PDF: {pdf_filename}")
    
    # ── WINDOWS CRASH PROTECTION ──
    if sys.platform == "win32":
        import ctypes
        # Disable Windows GPF error dialog popups ("Application has stopped working").
        # This ensures that if the process crashes, it terminates immediately
        # instead of hanging in memory waiting for a user click [1].
        ctypes.windll.kernel32.SetErrorMode(0x0002)

    # Execute pdf2htmlEX in a background process
    process = subprocess.Popen(
        cmd, 
        cwd=pdf_dir, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.PIPE, 
        text=True
    )

    # ── STRICT 45-SECOND TIMEOUT PROTECTION ──
    # To prevent the application from freezing when pdf2htmlEX enters an infinite loop
    # (common with LaTeX/arXiv mathematical fonts), we enforce a strict 30s timeout [1].
    try:
        # Wait up to 45 seconds for execution to complete cleanly [1]
        stderr_output, _ = process.communicate(timeout=45)
        
    except subprocess.TimeoutExpired:
        # Crucial: Force-kill the hanging process to free system memory and release locks [1]
        logger.error(f"pdf2htmlEX conversion timed out after 30 seconds on: {pdf_filename}")
        process.kill()
        
        # Clean up zombie processes and release file handles securely
        process.communicate()
        
        # TODO: If local compilation fails or times out, implement an automatic fallback
        # to a remote serverless cloud-rendering API to convert complex LaTeX documents.
        return None

    # Parse final compilation progress from accumulated stderr logs
    if stderr_output and on_progress:
        matches = re.findall(r"Working:\s*(\d+)/(\d+)", stderr_output)
        if matches:
            last_match = matches[-1]
            on_progress(int(last_match[0]), int(last_match[1]))

    if process.returncode == 0 and os.path.exists(output_html_path):
        logger.info("Raw HTML file generated successfully.")
        return output_html_path
        
    logger.error(f"pdf2htmlEX exited with error code: {process.returncode}")
    
    # TODO: In the main UI window, handle the None return value by displaying a clear
    # and friendly error message explaining that this PDF contains unsupported fonts.
    return None




def parse_matrix_classes(soup: BeautifulSoup) -> Dict[str, Tuple[float, float]]:
    """
    Parses unscaled CSS transform matrix properties from style tags.
    Robust pattern tolerating spaces, negative signs, and multiple rules.
    (e.g., .m0 { transform: matrix(0.125, 0, 0, 0.125, 0, 0); } -> {'m0': (0.125, 0.125)})
    
    Args:
        soup: BeautifulSoup object parsed from raw HTML.

    Returns:
        Dict[str, Tuple[float, float]]: Mapping of matrix classes to (scaleX, scaleY) factors.
    """
    matrix_map: Dict[str, Tuple[float, float]] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        # Improved pattern capturing scaleX and scaleY with sign and spacing tolerance
        for m in re.finditer(r'\.(m\w+)\s*\{[^}]*transform\s*:\s*matrix\s*\(\s*(-?[\d\.]+)\s*,\s*-?[\d\.]+\s*,\s*-?[\d\.]+\s*,\s*(-?[\d\.]+)\s*,', text):
            cls: str = m.group(1)
            sx: float = float(m.group(2))
            sy: float = float(m.group(3))
            matrix_map[cls] = (sx, sy)
    return matrix_map


def parse_spacer_widths(soup: BeautifulSoup) -> Dict[str, float]:
    """
    Parse horizontal spacer widths from CSS style tags inside the HTML document.

    This function dynamically scans all <style> tags to extract horizontal offset
    properties (such as margin-left, margin-right, left, right, and width)
    generated by pdf2htmlEX. It converts different CSS units (pt, em, rem) 
    into standard virtual pixels (px) to prevent layout breakages.

    Args:
        soup (BeautifulSoup): The parsed BeautifulSoup object of the HTML page.

    Returns:
        Dict[str, float]: A mapping of spacer class names to their width in pixels.
    """
    spacer_map: Dict[str, float] = {}
    
    # Generic regex pattern matching horizontal spacing properties and their units
    pattern = re.compile(
        r'\._([a-fA-F0-9\w]+)\s*\{[^}]*?\b(margin-left|margin-right|left|right|width)\s*:\s*(-?[\d\.]+)\s*(px|pt|em|rem|%)'
    )

    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
        for match in pattern.finditer(text):
            class_name = match.group(1)
            raw_value = float(match.group(3))
            unit = match.group(4)
            
            # Normalize units to standard virtual pixels (px)
            if unit == "pt":
                pixel_value = raw_value * 1.333333
            elif unit in ("em", "rem"):
                pixel_value = raw_value * 16.0
            else:
                pixel_value = raw_value
                
            spacer_map[class_name] = pixel_value
            
    return spacer_map


def parse_color_classes(soup: BeautifulSoup) -> Dict[str, str]:
    """
    Parse font color classes from CSS style tags inside the HTML document.

    This utility extracts color declarations mapped to class names starting 
    with '.fc' (e.g. .fc0 { color: #1a1a1a; }) and normalizes hex/rgb values 
    into standard hex codes (without the '#' symbol) for XML tagging.
    Features robust error handling to prevent pipeline failures.

    Args:
        soup (BeautifulSoup): The parsed BeautifulSoup object of the HTML page.

    Returns:
        Dict[str, str]: A mapping of CSS classes (like 'fc0') to their Hex codes.
    """
    color_map: Dict[str, str] = {}
    try:
        pattern = re.compile(
            r'\.(fc\w+)\s*\{[^}]*?color\s*:\s*([^;}]+)'
        )

        for style_tag in soup.find_all("style"):
            text = style_tag.get_text()
            for match in pattern.finditer(text):
                class_name = match.group(1)
                color_value = match.group(2).strip()
                
                hex_color = ""
                if color_value.startswith("#"):
                    hex_color = color_value.replace("#", "").strip()
                    if len(hex_color) == 3:
                        hex_color = "".join([c * 2 for c in hex_color])
                elif "rgb" in color_value:
                    rgb_nums = re.findall(r'\d+', color_value)
                    if len(rgb_nums) >= 3:
                        r, g, b = int(rgb_nums[0]), int(rgb_nums[1]), int(rgb_nums[2])
                        hex_color = f"{r:02x}{g:02x}{b:02x}"
                        
                if hex_color:
                    color_map[class_name] = hex_color
    except Exception:
        # Fail silently to guarantee core pipeline extraction never crashes
        pass
        
    return color_map


def parse_position_classes(soup: BeautifulSoup) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Parses unscaled CSS coordinates from style tags to understand visual layout.
    Extracts x classes (.x1 { left: 85px; }) and y classes (.y1 { bottom: 234px; })
    """
    x_map: Dict[str, float] = {}
    y_map: Dict[str, float] = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
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
    color_map:  Dict[str, str] = parse_color_classes(soup)
    x_map, y_map = parse_position_classes(soup)
    pages_list = soup.find_all("div", class_="pf")

    # Safely load structural spacing threshold configurations [1]
    # Load dynamic threshold, falling back to THRESHOLD_PX (12.0) if not configured
    if QSettings is not None:
        try:
            settings = QSettings("RockTranslate", "TranslationConfig")
            threshold_px = float(settings.value("threshold_px", 12.0))
        except Exception:
            threshold_px = THRESHOLD_PX
    else:
        threshold_px = THRESHOLD_PX  # Safe visual spacing default for CLI/API [1]

    original_texts_map: Dict[str, str] = {}
    tid_to_page: Dict[str, int] = {}
    idx: List[int] = [0]

    for page_idx, page_el in enumerate(pages_list):
        # 1. Collect all raw line containers on this page
        div_t_elements = page_el.find_all("div", class_="t")
        
        # 2. Extract real geometric positions for layout sorting
        # def get_div_sort_key(div_t_node: Any) -> Tuple[float, float]:
        #     classes = div_t_node.get("class", [])
        #     x_val = 0.0
        #     y_val = 0.0
        #     for cls in classes:
        #         if cls in x_map:
        #             x_val = x_map[cls]
        #         if cls in y_map:
        #             y_val = y_map[cls]
        #     # pdf2htmlEX uses 'bottom' for Y coordinates. Larger values are at the top.
        #     return -y_val, x_val

        # 3. Sort line containers visually from top-to-bottom and left-to-right
        # sorted_div_t = sorted(div_t_elements, key=get_div_sort_key)

        # 3. Preserve the native DOM reading order from pdf2htmlEX to support multi-column layouts
        sorted_div_t = div_t_elements


        for div_t in sorted_div_t:
            # Determine line scaling factors (scaleX, scaleY)
            classes = div_t.get("class", [])
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)
            
            # ── 4. RECURSIVE DOM FLATTENING (Surgically exposes nested spacers inside styled spans) ──
            flattened_children: List[Any] = []
            
            def flatten_element(element: Any, active_classes: List[str]) -> None:
                if isinstance(element, NavigableString):
                    if str(element).strip():
                        # Wrap raw text nodes in a cloned span with inherited classes (ff2, fc0, etc.)
                        new_span = soup.new_tag("span", attrs={"class": " ".join(active_classes)})
                        new_span.string = str(element)
                        flattened_children.append(new_span)
                    else:
                        flattened_children.append(element)
                elif element.name == "span" and element.get("class") and "_" in element.get("class"):
                    # Spacers are kept flat without wrapping
                    flattened_children.append(element)
                elif element.name in ["span", "b", "i", "sup", "sub", "em", "strong"]:
                    current_classes = list(active_classes)
                    if element.get("class"):
                        current_classes.extend(element.get("class"))
                    for child_node in list(element.contents):
                        flatten_element(child_node, current_classes)
                else:
                    flattened_children.append(element)

            for child in children:
                flatten_element(child, [])

            # Re-bind processing contents to our perfectly flattened line nodes
            children = flattened_children
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
                    # --- UNIVERSAL ACCENT NORMALIZATION (NFC) ---
                    # Merges split floating accents (like e + ´) into standard unicode characters (like é)
                    normalized_text = unicodedata.normalize('NFC', merged_text)
                    
                    gid = f"g-{idx[0]}"
                    original_texts_map[gid] = normalized_text
                    tid_to_page[gid] = page_idx

                    # Copy font styles from the children, but DO NOT inherit fc (font color) classes.
                    # This prevents the parent translation span from bleeding a single color over the entire line.
                    inherited_classes = ["trans-span"]
                    for el in current_group_elements:
                        if hasattr(el, "get"):
                            el_classes = el.get("class", [])
                            for cls in el_classes:
                                # We inherit font family (ff) and size (fs), but skip color classes
                                if cls.startswith("ff") or cls.startswith("fs"):
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
                # child_text = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                
                # Silently skip legacy PDF floating accents
                # if child_text in ACCENTS_TO_IGNORE:
                #     continue

                is_spacer = False
                width = 0.0

                # --- FIX : Systematic and defensive initialization of child_classes ---
                raw_classes = child.get("class") if hasattr(child, "get") else None
                if isinstance(raw_classes, str):
                    child_classes = raw_classes.split()
                elif isinstance(raw_classes, list):
                    child_classes = [str(cls) for cls in raw_classes]
                else:
                    child_classes = []

                # Now that it's initialized, we can use it safely
                if child.name == "span" and "_" in child_classes:
                    is_spacer = True
                    for cls in child_classes:
                        if cls.startswith("_") and len(cls) > 1:
                            width = spacer_map.get(cls[1:], 0.0)
                            break

                if is_spacer:
                    # --- SCALED WIDTH CALCULATION (Core geometry fix) ---
                    scaled_width = width * sx_orig

                    if abs(scaled_width) >= threshold_px:  # Uses the user-defined threshold px
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
                        # Extract raw text content
                        text_content = child.get_text()
                        # --- NORMALIZATION FIX: Convert custom symbol parentheses back to standard Unicode ---
                        # todo : remplace it by a very table map avec pdf's writter
                        text_content = text_content.replace("ð", "(").replace("Þ", ")")
                        text_content = text_content.replace("¼", "=").replace("þ","+")
                        
                        color_hex = None
                        for cls in child_classes:
                            # Ignore default color class (fc0) to keep normal text clean
                            if cls == "fc0":
                                continue
                            if cls in color_map:
                                color_hex = color_map[cls]
                                break
                        
                        # Wrap text in style XML tag if a special color is detected
                        if color_hex and text_content.strip():
                            styled_text = f"<color_{color_hex}>{text_content}</color_{color_hex}>"
                        else:
                            styled_text = text_content
                            
                        current_group_text.append(styled_text)
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
                "background: rgba(250, 250, 252, 0.98); "
                "border: 3px solid rgba(255,255,255,0.8); "
                "border-radius: 16px; "
                "box-shadow: 0 8px 32px rgba(31,38,135,0.15), 0 0 1px rgba(255,255,255,0.8); "
                "z-index: 1000; "
                "display: flex; "
                "justify-content: center; "
                "align-items: center; "
                "pointer-events: none; "
                "transform: translate3d(0, 0, 0); "
                "backface-visibility: hidden; "
                "-webkit-backface-visibility: hidden;"
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
        text_p.string = "Waiting for translation..."
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

        div.t {
            white-space: nowrap !important;
        }

       @keyframes loading-shimmer {
            0% {
                background-position: -150px 0;
            }
            100% {
                background-position: 150px 0;
            }
        }
        
        .shimmer-line {
            display: inline-block !important;
            background: #f1f5f9 !important;
            background-image: linear-gradient(
                90deg, 
                #f1f5f9 0px, 
                #cbd5e1 40px, 
                #f1f5f9 80px
            ) !important;
            background-size: 250px 100% !important;
            background-repeat: no-repeat !important;
            animation: loading-shimmer 1.5s infinite linear !important;

            will-change: background-position !important;
            transform: translateZ(0) !important;

            border-radius: 4px !important;
            color: transparent !important;
            min-width: 30px;
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
    script_tag.string = r"""
        window.applyTranslation = function(transId, translatedText) {
            try {
                // Find the target translation span using its unique routing ID
                var span = document.querySelector('[data-trans-id="' + transId + '"]');
                if (!span) return;

                // Performance optimization: Skip DOM updates if the translated text is identical to current content
                if (span.textContent.trim() === translatedText.trim()) {
                    span.classList.remove('shimmer-line');
                    return;
                }

                // Locate the closest text block container. pdf2htmlEX wraps lines in 'div.t' wrappers.
                var divT = span.closest('div.t');
                if (!divT) return;

                // Cache original geometric matrix scaling values (scaleX, scaleY)
                var sxOrig = parseFloat(span.getAttribute('data-sx') || '1');
                var syOrig = parseFloat(span.getAttribute('data-sy') || '1');

                // Initialize metrics backup on the first translation pass to prevent multi-pass calculation drift
                if (!divT.hasAttribute('data-orig-sw')) {
                    // Temporarily restore the original scale matrix to measure the true native scrollWidth
                    divT.style.transform = 'matrix(' + sxOrig + ',0,0,' + syOrig + ',0,0)';
                    divT.setAttribute('data-orig-sw', divT.scrollWidth);
                    divT.setAttribute('data-sx-orig', sxOrig);
                    divT.setAttribute('data-sy-orig', syOrig);
                }

                // Retrieve cached metric baselines
                var origSW = parseFloat(divT.getAttribute('data-orig-sw'));
                var sx     = parseFloat(divT.getAttribute('data-sx-orig'));
                var sy     = parseFloat(divT.getAttribute('data-sy-orig'));

                // Robust Color Formatting: Transform <color_HEX>...</color_HEX> tags into visual inline spans.
                // Uses [\s\S]*? to handle line breaks, and allows lazy LLM formatting variations (e.g. simplified </color> closure) [1.2.6].
                var formattedHTML = translatedText.replace(
                    /<color_([0-9a-fA-F]{6})>([\s\S]*?)<\/color(?:_\w+)?>/g, 
                    '<span style="color: #$1;">$2</span>'
                );
                span.innerHTML = formattedHTML;

                // Clear skeletal loading animations once real DOM content is injected [1.2.6]
                span.classList.remove('shimmer-line');

                // Compute adaptive horizontal scaling to fit the translated text within physical boundaries
                var newSW = divT.scrollWidth;

                if (newSW > 0 && origSW > 0) {
                    var newSx = sx * (origSW / newSW);
                    // Cap horizontal scaling to prevent unnecessary stretching of short text
                    newSx = Math.min(newSx, sx);
                    // newSx = Math.max(newSx, sx * 0.82);
                    divT.style.transform = 'matrix(' + newSx + ',0,0,' + sy + ',0,0)';
                }
            } catch (e) {
                console.error("Error in applyTranslation:", e);
            }
        };

        window.preparePageForTranslation = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            // Smoothly fade out and hide the waiting overlay to reveal the underlying page structure [1.2.6]
            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (glass) {
                glass.style.transition = 'opacity 0.3s ease-out';
                glass.style.opacity = '0';
                setTimeout(function() { glass.style.display = 'none'; }, 300);
            }

            // Apply shimmer skeletal loaders to all targeted translation units on this page [1.2.6]
            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.add('shimmer-line');
            });
        };

        window.resetPageToWaiting = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            // Remove shimmering animation states to clean up DOM rendering [1.2.6]
            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.remove('shimmer-line');
            });

            // Reconstruct the waiting overlay if missing, or restore its visibility.
            // This prevents unrendered pages from displaying blank gaps if translation halts midway.
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
                text_p.textContent = "Waiting for translation...";
                
                inner.appendChild(loader);
                inner.appendChild(text_p);
                glass.appendChild(inner);
                page.appendChild(glass);
            } else {
                glass.style.display = 'flex';
                glass.style.opacity = '1';
            }
        };

        // Secure message bus routing to receive events and updates from parent window contexts
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