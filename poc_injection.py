"""
poc_injection_table.py — Test d'injection sur les tableaux (Page 5 uniquement)
"""

import os
import webbrowser
import tempfile
import json

from core.fitz_extractor import FitzExtractor
from core.reading_order import ReadingOrderSorter
from reconstruction.html_builder import HTMLBuilder
from core.domain import FitzDocument, FitzTableBlock

PDF_PATH = "Nsangou Ngapna et al._ASR_2024.pdf"  # Adaptez le nom de votre PDF
TARGET_PAGE = 5 # Nous ciblons uniquement la page 5 (contenant le grand tableau)

def mock_translate_table_by_cells(block: FitzTableBlock):
    """
    Regroupe spatialement les mots du tableau en cellules virtuelles
    et injecte une fausse traduction à l'intérieur de chaque cellule.
    """
    if not block.words:
        return

    # 1. Regroupement par lignes physiques (hauteur similaire)
    sorted_words = sorted(block.words, key=lambda w: (w["top"], w["x0"]))
    lines = []
    current_line = []
    for w in sorted_words:
        if not current_line:
            current_line.append(w)
        else:
            if abs(w["top"] - current_line[-1]["top"]) < 4.0:
                current_line.append(w)
            else:
                lines.append(current_line)
                current_line = [w]
    if current_line:
        lines.append(current_line)
        
    # 2. Regroupement horizontal par cellules (écart < 15px)
    cells = []
    for line in lines:
        line_sorted = sorted(line, key=lambda w: w["x0"])
        current_cell = []
        for w in line_sorted:
            if not current_cell:
                current_cell.append(w)
            else:
                gap = w["x0"] - current_cell[-1]["x1"]
                if gap < 15.0:
                    current_cell.append(w)
                else:
                    cells.append(current_cell)
                    current_cell = [w]
        if current_cell:
            cells.append(current_cell)

    # 3. Reconstruction des mots du bloc avec le faux texte traduit par cellule
    new_words = []
    for cell_words in cells:
        left = min(w["x0"] for w in cell_words)
        top = min(w["top"] for w in cell_words)
        right = max(w["x1"] for w in cell_words)
        bottom = max(w["bottom"] for w in cell_words)
        original_text = " ".join(w["text"] for w in cell_words if w.get("text"))
        
        # Fausse traduction de la cellule entière
        translated_text = f"{original_text}"
        
        first = cell_words[0]
        new_words.append({
            "text": translated_text,
            "x0": left,
            "top": top,
            "x1": right,
            "bottom": bottom,
            "font_size":  6.5,
            "is_bold": first.get("is_bold", False),
            "is_italic": first.get("is_italic", False),
            "color": first.get("color", "rgb(0,0,0)")
        })
        
    block.words = new_words


def main():
    print(f"Extraction ciblée de la Page {TARGET_PAGE}...")
    import fitz
    from core.table_detector import page_has_table

    extractor = FitzExtractor(PDF_PATH)
    pdf = fitz.open(PDF_PATH)

    doc = FitzDocument(path=PDF_PATH)

    # Extraction d'une seule page spécifique
    page_obj = pdf[TARGET_PAGE - 1]
    has_tables = page_has_table(page_obj)
    
    print(f"Page {TARGET_PAGE} chargée — tableaux détectés : {has_tables}")
    
    fitz_page = extractor._extract_page(
        page_obj, 
        TARGET_PAGE, 
        extract_tables=has_tables
    )
    doc.pages.append(fitz_page)
    pdf.close()

    sorter = ReadingOrderSorter()
    fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)

    # Injection du texte simulé
    total_blocks = 0
    total_tables = 0
    for block in fitz_page.blocks:
        if type(block).__name__ == "FitzTableBlock":
            # Si c'est un tableau, on applique notre regroupement spatial de test
            mock_translate_table_by_cells(block)
            total_tables += 1
        else:
            # Si c'est un paragraphe normal, on lui applique la traduction classique
            block.translated_text = f"{block.text}"
            total_blocks += 1

    print(f"Simulés : {total_blocks} paragraphes et {total_tables} tableau(x).")

    # Génération et ouverture du HTML
    html = HTMLBuilder.build_document(doc, show_blurred_overlay=False)

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", encoding="utf-8", delete=False
    )
    tmp.write(html)
    tmp.close()

    print(f"Visualisation disponible à l'adresse : {tmp.name}")
    webbrowser.open(f"file://{tmp.name}")

if __name__ == "__main__":
    main()