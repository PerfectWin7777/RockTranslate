"""
RockTranslate — Visual Segmentation Diagnostic Tool
Path: tests/test_analyzer.py

This utility script converts a sample PDF, applies the hybrid layout grouping 
algorithms, injects colored diagnostic classes (Green for merged, Red for cuts),
and automatically opens the rendered HTML results in the user's default browser.

Usage:
    python tests/test_analyzer.py
"""

import os
import sys
import re
import webbrowser
from typing import Dict, Tuple, List, Any
from bs4 import BeautifulSoup, NavigableString

# Ensure correct execution paths
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Safe package imports
try:
    from core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from core.html_transformer import convert_pdf_to_html, parse_matrix_classes
except ImportError:
    from src.core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from src.core.html_transformer import convert_pdf_to_html, parse_matrix_classes


def parse_spacer_widths(soup: BeautifulSoup) -> Dict[str, float]:
    """
    Extrait de manière générique les largeurs des spacers depuis les balises <style>.
    Ne capture que les propriétés de déplacement horizontal pour éviter les conflits verticaux.
    """
    spacer_map = {}
    pattern = re.compile(
        r'\._([a-fA-F0-9\w]+)\s*\{[^}]*?\b(margin-left|margin-right|left|right|width)\s*:\s*(-?[\d\.]+)\s*(px|pt|em|rem|%)'
    )

    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
        for m in pattern.finditer(text):
            cls_name = m.group(1)
            val_brute = float(m.group(3))
            unit = m.group(4)
            
            if unit == "pt":
                val_px = val_brute * 1.333333
            elif unit in ("em", "rem"):
                val_px = val_brute * 16.0
            else:
                val_px = val_brute
                
            spacer_map[cls_name] = val_px
            
    return spacer_map


def parse_position_classes(soup: BeautifulSoup) -> Tuple[Dict[str, float], Dict[str, float]]:
    """
    Extrait les coordonnées brutes X (left) et Y (bottom) depuis les balises de style CSS.
    """
    x_map = {}
    y_map = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.get_text()
        for m in re.finditer(r'\.(x\w+)\s*\{\s*(?:left|margin-left)\s*:\s*([\d\.-]+)\s*px', text):
            x_map[m.group(1)] = float(m.group(2))
        for m in re.finditer(r'\.(y\w+)\s*\{\s*(?:bottom|top|margin-bottom|margin-top)\s*:\s*([\d\.-]+)\s*px', text):
            y_map[m.group(1)] = float(m.group(2))
    return x_map, y_map


def generate_visual_diagnostic(pdf_path: str, output_diagnostic_path: str) -> None:
    """
    Applique la conversion du PDF, trie les lignes, aplatit le DOM de manière
    récursive, réalise l'analyse géométrique et génère un rapport HTML visuel.
    """
    print(f"⚙️ Running high-fidelity diagnostic extraction on: {pdf_path}")
    
    # 1. Compile PDF to raw HTML
    raw_html_path = convert_pdf_to_html(pdf_path, DEFAULT_ASSETS_DIR)
    if not raw_html_path or not os.path.exists(raw_html_path):
        print("❌ Error: Failed to compile the PDF.")
        return

    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    matrix_map = parse_matrix_classes(soup)
    spacer_map = parse_spacer_widths(soup)
    x_map, y_map = parse_position_classes(soup)
    pages_list = soup.find_all("div", class_="pf")

    print(f"Parsed {len(matrix_map)} matrix scales, {len(spacer_map)} spacers and {len(x_map)} positions.")

    # 2. Run the SCALED hybrid layout grouping algorithm with visual sorting
    for page_idx, page_el in enumerate(pages_list):
        div_t_elements = page_el.find_all("div", class_="t")
        
        # Tri géométrique identique à la production
        def get_div_sort_key(div_t_node: Any) -> Tuple[float, float]:
            classes = div_t_node.get("class", [])
            x_val = 0.0
            y_val = 0.0
            for cls in classes:
                if cls in x_map:
                    x_val = x_map[cls]
                if cls in y_map:
                    y_val = y_map[cls]
            return -y_val, x_val

        sorted_div_t = sorted(div_t_elements, key=get_div_sort_key)

        for div_t in sorted_div_t:
            # Determine active line scaling factors
            classes = div_t.get("class", [])
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)
            
            # ── DESCENTE RÉCURSIVE (Flattening du DOM) ──
            flattened_children: List[Any] = []
            
            def flatten_element(element: Any, active_classes: List[str]) -> None:
                if isinstance(element, NavigableString):
                    if str(element).strip():
                        new_span = soup.new_tag("span", attrs={"class": " ".join(active_classes)})
                        new_span.string = str(element)
                        flattened_children.append(new_span)
                    else:
                        flattened_children.append(element)
                elif element.name == "span" and element.get("class") and "_" in element.get("class"):
                    flattened_children.append(element)
                elif element.name in ["span", "a", "b", "i", "sup", "sub", "em", "strong"]:
                    current_classes = list(active_classes)
                    if element.get("class"):
                        current_classes.extend(element.get("class"))
                    for child_node in list(element.contents):
                        flatten_element(child_node, current_classes)
                else:
                    flattened_children.append(element)

            for child in children:
                flatten_element(child, [])

            children = flattened_children
            div_t.clear()

            current_group_elements = []
            current_group_text = []

            def commit_group():
                if not current_group_elements:
                    return

                merged_text = "".join(current_group_text).strip()
                if merged_text:
                    # Create visual diagnostic Green frame
                    group_span = soup.new_tag("span", attrs={
                        "style": (
                            "border: 1px solid #48bb78; "
                            "background-color: rgba(72,187,120,0.15); "
                            "border-radius: 2px; "
                            "padding: 1px; "
                            "display: inline;"
                        ),
                        "title": f"Merged Phrase: '{merged_text}'"
                    })
                    for el in current_group_elements:
                        group_span.append(el)
                    div_t.append(group_span)
                else:
                    for el in current_group_elements:
                        div_t.append(el)

                current_group_text.clear()
                current_group_elements.clear()

            # Analyse géométrique avec détection de valeur absolue
            for child in children:
                child_text = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                
                # Filter out raw accent artifacts
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
                    scaled_width = width * sx_orig
                    
                    # CORRECTION GÉOMÉTRIQUE : abs() sur les spacers aplatis
                    if abs(scaled_width) >= THRESHOLD_PX:
                        commit_group()
                        div_t.append(child)
                    elif scaled_width >= 2.5:
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                    else:
                        current_group_elements.append(child)
                else:
                    if isinstance(child, str):
                        current_group_text.append(str(child))
                        current_group_elements.append(child)
                    else:
                        current_group_text.append(child.get_text())
                        current_group_elements.append(child)

            commit_group()

    # 3. Inject diagnostic sidebar instructions legend
    legend_div = soup.new_tag("div", attrs={
        "style": (
            "position: fixed; "
            "top: 20px; "
            "left: 20px; "
            "width: 320px; "
            "background: rgba(255,255,255,0.95); "
            "border: 1px solid #e2e8f0; "
            "border-radius: 12px; "
            "padding: 20px; "
            "box-shadow: 0 10px 25px rgba(0,0,0,0.15); "
            "z-index: 99999; "
            "font-family: sans-serif; "
            "user-select: none;"
        )
    })
    legend_div.innerHTML = """
        <h3 style="margin: 0 0 10px 0; color: #2d3748; font-size: 16px;">RockTranslate Analyzer</h3>
        <p style="margin: 0 0 15px 0; color: #718096; font-size: 12px; line-height: 1.4;">
            Visualizing dynamic text grouping and column detection.
        </p>
        <div style="display: flex; align-items: center; margin-bottom: 8px;">
            <span style="width: 24px; height: 14px; border: 1px solid #48bb78; background: rgba(72,187,120,0.15); margin-right: 10px; border-radius: 2px;"></span>
            <span style="font-size: 11px; color: #4a5568; font-weight: bold;">Green Zone: Merged Prose</span>
        </div>
        <div style="display: flex; align-items: center;">
            <span style="width: 24px; border-left: 2px dashed #f56565; background: rgba(245,101,101,0.1); text-align: center; font-size: 9px; color: #f56565; margin-right: 10px; padding: 2px 0;">✂</span>
            <span style="font-size: 11px; color: #4a5568; font-weight: bold;">Red Line / Scissors: Column Cut</span>
        </div>
    """
    soup.body.append(legend_div)

    # 4. Save visual diagnostic file
    with open(output_diagnostic_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print(f"✅ Diagnostic HTML report compiled at: {output_diagnostic_path}")
    
    # 5. Automatically open the file in default browser
    webbrowser.open(f"file:///{os.path.abspath(output_diagnostic_path)}")


if __name__ == "__main__":
    # Create diagnostic output folder if missing
    os.makedirs(os.path.join(project_root, "diagnostic_runs"), exist_ok=True)
    
    # Replace with any of your laboratory target test PDF paths
    target_pdf = "2_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
    diagnostic_output = os.path.join(project_root, "diagnostic_runs", "diagnostic_visual.html")
    
    if os.path.exists(target_pdf):
        generate_visual_diagnostic(target_pdf, diagnostic_output)
    else:
        print(
            f"❌ Diagnostic target not found at: {target_pdf}\n"
            f"Please place your target PDF inside the root directory and run again."
        )