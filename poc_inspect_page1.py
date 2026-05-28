"""
poc_inspect_page1.py — Inspecte la page 1 en utilisant l'API officielle
"""

import os
import fitz
import json
from core.fitz_extractor import FitzExtractor
from core.cid_normalizer import build_cid_maps

PDF_PATH = "Nsangou Ngapna et al._ASR_2024.pdf"  # Adaptez si besoin

def main():
    if not os.path.exists(PDF_PATH):
        print(f"Fichier introuvable : {PDF_PATH}")
        return

    print("--- DÉBUT DE L'INSPECTION DE LA PAGE 1 (API OFFICIELLE) ---")
    extractor = FitzExtractor(PDF_PATH)
    pdf = fitz.open(PDF_PATH)
    page = pdf[0]  # Page 1

    # Initialisation indispensable des CID maps pour éviter le crash
    extractor.cid_maps = build_cid_maps(pdf)

    # Extraction via l'API officielle (identique au comportement du logiciel complet)
    fitz_page = extractor._extract_page(page, 1, extract_tables=True)

    print(f"\nDimensions de la page 1 : {fitz_page.width:.1f}x{fitz_page.height:.1f}")
    print(f"Nombre de blocs totaux extraits : {len(fitz_page.blocks)}")

    tables_count = 0
    paragraphs_count = 0

    for idx, block in enumerate(fitz_page.blocks):
        b_type = type(block).__name__
        
        if b_type == "FitzTableBlock":
            tables_count += 1
            print(f"\n[BLOC {idx}] TABLEAU ({b_type}) :")
            print(f"  BBox : left={block.left:.1f}, top={block.top:.1f}, right={block.right:.1f}, bottom={block.bottom:.1f}")
            print(f"  Nombre de mots : {len(block.words)}")
            # Extrait des 15 premiers mots pour voir ce qui est capturé
            sample = " ".join(w["text"] for w in block.words[:15])
            print(f"  Texte capturé : \"{sample}...\"")
        else:
            paragraphs_count += 1
            print(f"\n[BLOC {idx}] PARAGRAPHE ({b_type}) :")
            print(f"  BBox : left={block.left:.1f}, top={block.top:.1f}, right={block.right:.1f}, bottom={block.bottom:.1f}")
            print(f"  Texte : \"{block.text[:120]}...\"")

    print(f"\n--- BILAN DE L'EXTRACTION ---")
    print(f"Tableaux (FitzTableBlock) : {tables_count}")
    print(f"Paragraphes (FitzBlock)    : {paragraphs_count}")
    
    pdf.close()

if __name__ == "__main__":
    main()