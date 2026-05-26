"""
test_formula_detector.py — Calibration du FormulaDetector sur pages réelles
Usage: python test_formula_detector.py <pdf_path> <page_num>
"""
import sys, os
sys.path.insert(0, os.path.abspath("src"))

import fitz
import pdfplumber
from core.formula_detector import FormulaDetector
from core.fitz_extractor import FitzExtractor
from core.reading_order import ReadingOrderSorter

PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "Nsangou Ngapna et al._ASR_2024.pdf"
PAGE_NUM = int(sys.argv[2]) if len(sys.argv) > 2 else 9

print(f"\n=== FormulaDetector — Page {PAGE_NUM} ===\n")

# 1. Extraction des blocs via le pipeline existant
extractor = FitzExtractor(PDF_PATH)
sorter    = ReadingOrderSorter()
doc_fitz  = fitz.open(PDF_PATH)
page      = doc_fitz[PAGE_NUM - 1]
fitz_page = extractor._extract_page(page, PAGE_NUM)
fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)
doc_fitz.close()

# 2. Mots pdfplumber pour la page
with pdfplumber.open(PDF_PATH) as pdf:
    p = pdf.pages[PAGE_NUM - 1]
    all_words = p.extract_words(x_tolerance=1, y_tolerance=3)

# 3. FormulaDetector
detector = FormulaDetector(
    page_width=fitz_page.width,
    page_height=fitz_page.height,
    all_words=all_words,
    threshold=4.0,
)

# 4. Analyse de chaque bloc
from core.domain import FitzTableBlock
text_blocks = [b for b in fitz_page.blocks if not isinstance(b, FitzTableBlock)]

print(f"{'SCORE':>6} {'ISO':>4} {'CTR':>4} {'BV':>6} {'NA':>6} {'TW':>6} | TEXTE")
print("─" * 90)

for block in text_blocks:
    feat = detector.extract_features(block)
    is_formula = feat.score >= detector.threshold
    label = "🔴 FORMULA" if is_formula else "  texte  "
    text_preview = block.text[:55].replace("\n", " ")
    print(
        f"{feat.score:>6.1f} "
        f"{'Y' if feat.is_isolated else 'N':>4} "
        f"{'Y' if feat.is_centered else 'N':>4} "
        f"{feat.baseline_variance:>6.2f} "
        f"{feat.non_alpha_ratio:>6.2f} "
        f"{feat.avg_token_width:>6.1f} "
        f"| {label} | {text_preview}"
    )

formulas = [b for b in text_blocks if detector.is_formula(b)]
print(f"\n→ {len(formulas)} formule(s) détectée(s) sur {len(text_blocks)} blocs texte")