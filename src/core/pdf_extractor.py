"""
pdf_extractor.py — Lecture PDF via pypdfium2
Chemin : D:/Projets/RockTranslate/src/core/pdf_extractor.py

Responsabilité unique : ouvrir un PDF et retourner un Document
rempli de RawObjects prêts pour le SpatialClusterer.

Usage :
    extractor = PDFExtractor("Nsangou Ngapna et al._ASR_2024.pdf")
    document  = extractor.extract()
"""

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from loguru import logger

from core.domain import RawObject, Page, Document


class PDFExtractor:
    """
    Lit un PDF page par page et extrait les objets texte atomiques.
    Chaque objet texte devient un RawObject avec :
        - text    : le contenu textuel réel (via text_page)
        - bbox    : position absolue (L, B, R, T) en points PDF
        - matrix  : transformation appliquée (a, b, c, d, e, f)
        - font_size : taille de police effective
    """

    # Filtre les objets sans texte utile ou corrompus
    _CORRUPT_CHARS = {'\ufffd', '\x00', '\r', '\n'}

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

    # ──────────────────────────────────────────
    # API publique
    # ──────────────────────────────────────────

    def extract(self) -> Document:
        """
        Pipeline complet : ouvre le PDF, extrait toutes les pages.
        Retourne un Document prêt pour SpatialClusterer.
        """
        doc = Document(path=self.pdf_path)

        pdf = pdfium.PdfDocument(self.pdf_path)
        total_objects = 0

        logger.info(f"Ouverture : {self.pdf_path} — {len(pdf)} pages")

        for page_num in range(len(pdf)):
            page_obj = pdf[page_num]
            page = self._extract_page(page_obj, page_num + 1)
            doc.pages.append(page)
            total_objects += len(page.raw_objects)
            logger.info(
                f"Page {page_num + 1} — "
                f"{len(page.raw_objects)} objets extraits "
                f"({page.width:.1f} × {page.height:.1f} pt)"
            )

        pdf.close()
        logger.info(
            f"Document complet : {len(doc.pages)} pages, "
            f"{total_objects} objets total"
        )
        return doc

    # ──────────────────────────────────────────
    # Extraction d'une page
    # ──────────────────────────────────────────

    def _extract_page(self, page: pdfium.PdfPage, page_num: int) -> Page:
        """
        Extrait tous les objets texte d'une page.
        Retourne une Page avec raw_objects remplis.
        """
        width  = page.get_width()
        height = page.get_height()
        result = Page(number=page_num, width=width, height=height)

        text_page = page.get_textpage()
        skipped   = 0

        for obj in page.get_objects():
            # On ne traite que les objets texte
            if not isinstance(obj, pdfium.PdfTextObj):
                continue

            raw = self._obj_to_raw(obj, text_page, page_num)

            if raw is None:
                skipped += 1
                continue

            result.raw_objects.append(raw)

        if skipped:
            logger.debug(f"  Page {page_num} — {skipped} objets ignorés (vides/corrompus)")

        return result

    # ──────────────────────────────────────────
    # Conversion objet PDFium → RawObject
    # ──────────────────────────────────────────

    def _obj_to_raw(
        self,
        obj: pdfium.PdfTextObj,
        text_page: pdfium.PdfTextPage,
        page_num: int
    ) -> RawObject | None:
        """
        Convertit un PdfTextObj en RawObject.
        Retourne None si l'objet est vide, corrompu, ou hors page.
        """
        try:
            bounds = obj.get_bounds()
        except Exception:
            return None

        L, B, R, T = bounds

        # Bbox invalide (objet dégénéré)
        if R <= L or T <= B:
            return None

        # Récupère le texte réel via text_page (plus fiable que obj.get_text())
        try:
            text = text_page.get_text_bounded(L, B, R, T)
        except Exception:
            return None

        # Nettoie et filtre
        text = text.strip()
        if not text:
            return None
        if all(c in self._CORRUPT_CHARS for c in text):
            return None

        # Matrice de transformation
        try:
            m = obj.get_matrix()
            matrix = (m.a, m.b, m.c, m.d, m.e, m.f)
        except Exception:
            matrix = (1.0, 0.0, 0.0, 1.0, L, B)

        # Taille de police
        try:
            font_size = obj.get_font_size()
        except Exception:
            # Fallback : hauteur de la bbox
            font_size = abs(T - B)

        # Si font_size est 0 ou absurde (cas Elsevier matrice scale)
        # on estime depuis la hauteur de la bbox
        if font_size <= 0 or font_size > 200:
            font_size = abs(T - B)

        if ' ' in text and len(text) < 15:
            print(f"MOT COUPÉ: '{text}' bbox=({L:.1f},{B:.1f},{R:.1f},{T:.1f})")

        # Filtre les objets dont la hauteur est aberrante
        # (cellules de tableaux Elsevier encodées avec bbox pleine hauteur)
        bbox_height = abs(T - B)
        bbox_width  = abs(R - L)

        # Un objet texte normal : hauteur < 3× sa largeur
        # Un objet tableau Elsevier : hauteur >> largeur (ratio inversé)
        if bbox_height > 50 and bbox_height > bbox_width * 3:
            logger.debug(f"  Objet tableau ignoré: h={bbox_height:.1f} w={bbox_width:.1f} '{text[:20]}'")
            return None

        # if abs(T - B) > 50:
        #    print(f"OBJET GÉANT: h={abs(T-B):.1f} text='{text[:30]}' font={font_size:.1f}")


        # Filtre les guillemets/apostrophes isolés parasites
        if text in {'"', "'", "''", '""', '"', '"', ''', '''}:
            return None
            

        return RawObject(
            text=text,
            left=L, bottom=B, right=R, top=T,
            font_size=font_size,
            matrix=matrix,
        )