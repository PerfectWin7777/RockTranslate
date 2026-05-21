"""
poc_render.py — Production-Grade Offline Page Renderer
Utilizes our unified FitzExtractor, ReadingOrderSorter, and HTMLBuilder pipeline.

Usage:
    python poc_render.py "Nsangou Ngapna et al._ASR_2024.pdf" [page_number]
"""

import sys
import os

# 1. Resolve search path to dynamically include modules located under 'src/'
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

import fitz  # PyMuPDF
from core.domain import FitzDocument
from core.fitz_extractor import FitzExtractor
from core.reading_order import ReadingOrderSorter
from reconstruction.html_builder import HTMLBuilder


def main():
    if len(sys.argv) < 2:
        print("Usage: python poc_render.py <pdf_path> [page_number]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    if not os.path.exists(pdf_path):
        print(f"❌ Error: File not found at: {pdf_path}")
        sys.exit(1)

    print(f"=== RockTranslate Offline Renderer ===")
    print(f"Loading document: {pdf_path}")
    print(f"Targeting Page: {page_num}")

    try:
        # 2. Open PDF using PyMuPDF (fitz)
        pdf = fitz.open(pdf_path)
        total_pages = len(pdf)

        if page_num < 1 or page_num > total_pages:
            print(f"❌ Error: Page number must be between 1 and {total_pages}.")
            pdf.close()
            sys.exit(1)

        target_page_obj = pdf[page_num - 1]

        # 3. Instantiate our production pipeline components
        extractor = FitzExtractor(pdf_path)
        sorter = ReadingOrderSorter()

        print("-> Extracting layout, vector paths, and generating background PNG...")
        # Extract raw page blocks, vector paths and generate background base64 image
        fitz_page = extractor._extract_page(target_page_obj, page_num)

        print("-> Running topological reading order sorting and alignment detection...")
        # Process block classifications, columns alignments and sorting
        fitz_page.blocks = sorter.process_page_layout(fitz_page.blocks, fitz_page.width)

        # Create a temporary FitzDocument containing only the target page
        temp_document = FitzDocument(path=pdf_path, pages=[fitz_page])

        print("-> Compiling page blocks and graphic paths to HTML...")
        # Render the complete continuous HTML document
        html_content = HTMLBuilder.build_document(temp_document, show_blurred_overlay=False)

        # 4. Save HTML to output file
        output_filename = f"poc_page_{page_num}.html"
        with open(output_filename, "w", encoding="utf-8") as f:
            f.write(html_content)

        pdf.close()
        print(f"✅ Success! HTML rendered output saved at: {output_filename}")

    except Exception as e:
        print(f"❌ Pipeline rendering failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()