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
from bs4 import BeautifulSoup

# Ensure correct execution paths
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Safe package imports
try:
    from core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from core.html_transformer import convert_pdf_to_html, parse_matrix_classes, parse_spacer_widths
except ImportError:
    from src.core.constants import DEFAULT_ASSETS_DIR, THRESHOLD_PX, ACCENTS_TO_IGNORE
    from src.core.html_transformer import convert_pdf_to_html, parse_matrix_classes, parse_spacer_widths


def generate_visual_diagnostic(pdf_path: str, output_diagnostic_path: str) -> None:
    """
    Translates a real PDF layout, executes scaled spacing diagnostics,
    generates a visual HTML report, and launches it in the default browser.
    """
    print(f"⚙️ Running high-fidelity diagnostic extraction on: {pdf_path}")
    
    # 1. Compile PDF to raw HTML using our downloader fallback utility
    raw_html_path = convert_pdf_to_html(pdf_path, DEFAULT_ASSETS_DIR)
    if not raw_html_path or not os.path.exists(raw_html_path):
        print("❌ Error: Failed to compile the PDF with pdf2htmlEX.")
        return

    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    matrix_map = parse_matrix_classes(soup)
    spacer_map = parse_spacer_widths(soup)
    pages_list = soup.find_all("div", class_="pf")

    print(f"Parsed {len(matrix_map)} matrix scales and {len(spacer_map)} spacer definitions.")

    # 2. Run the SCALED hybrid layout grouping algorithm
    for page_el in pages_list:
        for div_t in page_el.find_all("div", class_="t"):
            # Determine active line scaling factors
            classes = div_t.get("class", [])
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)
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

            # Process layout children geometrically
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
                    # --- SCALED WIDTH CHECK (Our core layout fix) ---
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
                    # Accumulate raw text nodes or styles
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
    target_pdf = "1_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
    diagnostic_output = os.path.join(project_root, "diagnostic_runs", "diagnostic_visual.html")
    
    if os.path.exists(target_pdf):
        generate_visual_diagnostic(target_pdf, diagnostic_output)
    else:
        print(
            f"❌ Diagnostic target not found at: {target_pdf}\n"
            f"Please place a test PDF named 'sample.pdf' inside 'src/assets/' and run again."
        )