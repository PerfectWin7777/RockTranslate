"""
RockTranslate — Bilingual side-by-side PDF
Path: src/rocktranslate/core/side_by_side.py

Builds a study/print copy where every sheet shows the original page on the
left and its translation on the right, at their exact sizes (vector content
of both PDFs is kept: no rasterization, text stays selectable).

Author: RockTranslate Contributors
License: MIT License
"""

from typing import List, Optional

from loguru import logger

GUTTER_PT = 18.0   # white strip between the two pages (1/4 inch)


def make_side_by_side(original_pdf: str, translated_pdf: str, output_pdf: str,
                      first_page: int = 1, pages: Optional[List[int]] = None,
                      password: Optional[str] = None) -> int:
    """
    Writes `output_pdf`: original page | translated page on each sheet.

    Args:
        original_pdf: Source PDF.
        translated_pdf: Translated PDF. Its first page is page `first_page` of
            the original (a translated page range starts at that page).
        output_pdf: Destination file.
        first_page: 1-based original page matching translated page 1.
        pages: Optional 1-based original pages to keep (default: every page
            present in the translated PDF).
        password: Password of a protected original.

    Returns:
        Number of sheets written.
    """
    from pypdf import PageObject, PdfReader, PdfWriter, Transformation

    source = PdfReader(original_pdf)
    if source.is_encrypted:
        source.decrypt(password or "")
    translated = PdfReader(translated_pdf)
    writer = PdfWriter()

    for t_index, t_page in enumerate(translated.pages):
        o_number = first_page + t_index
        if o_number > len(source.pages) or (pages and o_number not in pages):
            continue
        o_page = source.pages[o_number - 1]
        ow, oh = float(o_page.mediabox.width), float(o_page.mediabox.height)
        tw, th = float(t_page.mediabox.width), float(t_page.mediabox.height)
        # The translation is drawn at the original's height (printing may have
        # changed its size by a few points)
        scale = oh / th if th else 1.0
        sheet = PageObject.create_blank_page(width=ow + GUTTER_PT + tw * scale, height=oh)
        sheet.merge_transformed_page(o_page, Transformation().translate(-float(o_page.mediabox.left),
                                                                        -float(o_page.mediabox.bottom)))
        sheet.merge_transformed_page(t_page, Transformation()
                                     .translate(-float(t_page.mediabox.left), -float(t_page.mediabox.bottom))
                                     .scale(scale, scale).translate(ow + GUTTER_PT, 0))
        writer.add_page(sheet)

    count = len(writer.pages)
    with open(output_pdf, "wb") as f:
        writer.write(f)
    logger.info(f"Side-by-side PDF: {count} sheets -> {output_pdf}")
    return count
