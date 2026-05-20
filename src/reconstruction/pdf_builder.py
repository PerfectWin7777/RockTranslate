"""
pdf_builder.py — Reconstruction PDF avec texte traduit
Chemin : D:/Projets/RockTranslate/src/reconstruction/pdf_builder.py

Stratégie :
  1. Pour chaque paragraphe traduit :
     a. Couvre le texte original avec un rectangle blanc
     b. Réinjecte le texte traduit à la même position
  2. Sauvegarde le PDF modifié
"""

import ctypes
import os
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from loguru import logger
from core.domain import Paragraph


# Police embarquée (standard PDF — pas besoin de fichier externe)
_FONT_NAME = b"Helvetica"


class PDFBuilder:
    """
    Reconstruit un PDF en remplaçant le texte original par le texte traduit.
    """

    def __init__(self, original_path: str):
        self.original_path = original_path

    def rebuild(
        self,
        paragraphs: list[Paragraph],
        output_path: str,
    ) -> None:
        """
        Écrit un nouveau PDF à output_path avec les textes traduits.

        Pour chaque paragraphe :
          - Si translated_text est disponible → remplace
          - Sinon → laisse l'original intact
        """
        doc = pdfium.PdfDocument(self.original_path)

        # Groupe les paragraphes par page
        by_page: dict[int, list[Paragraph]] = {}
        for para in paragraphs:
            if para.translated_text:
                by_page.setdefault(para.page_number, []).append(para)

        logger.info(
            f"Reconstruction : {len(paragraphs)} paragraphes, "
            f"{len(by_page)} pages modifiées"
        )

        for page_num_1based, paras in by_page.items():
            page_idx = page_num_1based - 1
            if page_idx < 0 or page_idx >= len(doc):
                continue

            page = doc[page_idx]
            font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, _FONT_NAME)

            for para in paras:
                self._replace_paragraph(doc, page, font, para)

            pdfium_c.FPDFPage_GenerateContent(page.raw)
            logger.debug(f"  Page {page_num_1based} reconstruite ({len(paras)} paras)")

        doc.save(output_path)
        doc.close()
        logger.info(f"PDF reconstruit : {output_path}")

    def _replace_paragraph(
        self,
        doc: pdfium.PdfDocument,
        page: pdfium.PdfPage,
        font,
        para: Paragraph,
    ) -> None:
        """
        Couvre le paragraphe original et réinjecte le texte traduit.
        """
        L = para.left   - 1.0
        B = para.bottom - 1.0
        R = para.right  + 1.0
        T = para.top    + 1.0

        # ── 1. Rectangle blanc (cache) ──────────────────────────
        rect = pdfium_c.FPDFPageObj_CreateNewPath(L, B)
        pdfium_c.FPDFPath_LineTo(rect, R, B)
        pdfium_c.FPDFPath_LineTo(rect, R, T)
        pdfium_c.FPDFPath_LineTo(rect, L, T)
        pdfium_c.FPDFPath_Close(rect)
        pdfium_c.FPDFPageObj_SetFillColor(rect, 255, 255, 255, 255)
        pdfium_c.FPDFPath_SetDrawMode(rect, 1, 0)
        pdfium_c.FPDFPage_InsertObject(page.raw, rect)

        # ── 2. Injection texte traduit ──────────────────────────
        # Estime la taille de police depuis les blocs du paragraphe
        font_size = self._estimate_font_size(para)

        # Découpe le texte traduit en lignes qui rentrent dans la largeur
        lines = self._wrap_text(
            para.translated_text or "",
            max_width=R - L,
            font_size=font_size,
        )

        # Position de départ : coin haut-gauche du paragraphe
        # (PDF : Y croît vers le haut → on commence par T - font_size)
        y = T - font_size
        line_height = font_size * 1.25

        for line in lines:
            if y < B:
                break  # débordement : on s'arrête

            text_obj = pdfium_c.FPDFPageObj_CreateTextObj(
                doc.raw, font, font_size
            )

            # Encode en UTF-16-LE (requis par PDFium)
            utf16 = line.encode("utf-16-le") + b"\x00\x00"
            buf   = (ctypes.c_ubyte * len(utf16)).from_buffer_copy(utf16)
            pdfium_c.FPDFText_SetText(
                text_obj,
                ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort))
            )

            pdfium_c.FPDFPageObj_SetFillColor(text_obj, 0, 0, 0, 255)

            # Matrice de positionnement
            m = pdfium_c.FS_MATRIX()
            m.a, m.b, m.c, m.d = font_size, 0.0, 0.0, font_size
            m.e, m.f = L, y
            pdfium_c.FPDFPageObj_SetMatrix(text_obj, m)

            pdfium_c.FPDFPage_InsertObject(page.raw, text_obj)
            y -= line_height

    def _estimate_font_size(self, para: Paragraph) -> float:
        """Estime la taille de police depuis les lignes du paragraphe."""
        sizes = []
        for block in para.blocks:
            for line in block.lines:
                if line.font_size and line.font_size > 1:
                    sizes.append(line.font_size)
        if sizes:
            return sum(sizes) / len(sizes)
        return 9.0  # fallback Elsevier

    def _wrap_text(
        self, text: str, max_width: float, font_size: float
    ) -> list[str]:
        """
        Découpe le texte en lignes qui rentrent dans max_width.
        Heuristique : 1 caractère ≈ font_size * 0.5 pt de largeur.
        """
        if not text:
            return []

        char_width  = font_size * 0.50
        max_chars   = max(1, int(max_width / char_width))

        words  = text.split()
        lines  = []
        line   = ""

        for word in words:
            candidate = (line + " " + word).strip()
            if len(candidate) <= max_chars:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = word

        if line:
            lines.append(line)

        return lines