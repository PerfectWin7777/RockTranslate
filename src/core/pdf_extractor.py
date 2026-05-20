"""
pdf_extractor.py — Lecture PDF via pypdfium2
Chemin : D:/Projets/RockTranslate/src/core/pdf_extractor.py

Responsabilité unique : ouvrir un PDF et retourner un Document
rempli de RawObjects prêts pour le SpatialClusterer.

Usage :
    extractor = PDFExtractor("Nsangou Ngapna et al._ASR_2024.pdf")
    document  = extractor.extract()
"""
import ctypes
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

        # 1. On extrait d'abord TOUS les objets de la page pour trouver les fonds
        page_objects = list(page.get_objects())
        
        # 2. On isole les rectangles (Paths) qui servent souvent de fond
        path_objects = []
        for obj in page_objects:
            obj_type = pdfium_c.FPDFPageObj_GetType(obj.raw)
            if obj_type == pdfium_c.FPDF_PAGEOBJ_PATH:
                try:
                    bounds = obj.get_bounds()
                    L, B, R, T = bounds
                    
                    # Ignore les paths trop petits (lignes fines, artefacts)
                    width  = R - L
                    height = T - B
                    if width < 5 or height < 2:
                        continue
                        
                    fill_r, fill_g, fill_b, fill_a   = self._get_obj_fill_color(obj.raw)
                    stroke_r, stroke_g, stroke_b, stroke_a = self._get_obj_stroke_color(obj.raw)
                    
                    # Épaisseur du trait
                    stroke_w = ctypes.c_float()
                    pdfium_c.FPDFPageObj_GetStrokeWidth(obj.raw, stroke_w)
                    
                    path_objects.append({
                        "bounds":       (L, B, R, T),
                        "fill_color":   (fill_r, fill_g, fill_b, fill_a),
                        "stroke_color": (stroke_r, stroke_g, stroke_b, stroke_a),
                        "stroke_width": stroke_w.value,
                    })
                except:
                    continue


        text_page = page.get_textpage()
        
        # ── TEST POLICE — à retirer après diagnostic ──
        # if page_num == 1:  # seulement page 1 pour ne pas spammer
        #     for obj in page.get_objects():
        #         if isinstance(obj, pdfium.PdfTextObj):
        #             try:
        #                 bounds = obj.get_bounds()
        #                 text = text_page.get_text_bounded(*bounds).strip()
        #                 font = obj.get_font()
        #                 name = font.get_base_name()
        #                 weight = font.get_weight()
        #                 print(f"Police: '{name}' | weight={weight} | text: '{text[:20]}'")
        #             except Exception as e:
        #                 print(f"Erreur police: {e}")

        # Test : mesure la largeur d'un mot via text_page
        # page_text = page.get_textpage()
        # # Compte les chars et récupère leurs bboxes
        # char_count = pdfium_c.FPDFText_CountChars(page_text)
        # print(f"Total chars page: {char_count}")

        # # Pour les 5 premiers chars
        # for i in range(min(5, char_count)):
        #     left = ctypes.c_double()
        #     right = ctypes.c_double()  
        #     bottom = ctypes.c_double()
        #     top = ctypes.c_double()
        #     pdfium_c.FPDFText_GetCharBox(page_text, i, left, right, bottom, top)
        #     char = pdfium_c.FPDFText_GetUnicode(page_text, i)
        #     print(f"  char={chr(char)} w={right.value - left.value:.2f}pt")

        # ── FIN TEST ──
        


        skipped   = 0

        for obj in page.get_objects():
            # On ne traite que les objets texte
            if not isinstance(obj, pdfium.PdfTextObj):
                continue

            raw = self._obj_to_raw(obj, text_page, path_objects, page_num)

            if raw is None:
                skipped += 1
                continue

            result.raw_objects.append(raw)

        if skipped:
            logger.debug(f"  Page {page_num} — {skipped} objets ignorés (vides/corrompus)")
        
        

        return result
    

    def _get_obj_fill_color(self, obj_raw) -> tuple:
        r, g, b, a = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        ok = pdfium_c.FPDFPageObj_GetFillColor(obj_raw, r, g, b, a)
        if ok:
            return (r.value, g.value, b.value, a.value)
        return (0, 0, 0, 0)

    def _get_obj_stroke_color(self, obj_raw) -> tuple:
        r, g, b, a = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        ok = pdfium_c.FPDFPageObj_GetStrokeColor(obj_raw, r, g, b, a)
        if ok:
            return (r.value, g.value, b.value, a.value)
        return (0, 0, 0, 0)

    # ──────────────────────────────────────────
    # Conversion objet PDFium → RawObject
    # ──────────────────────────────────────────

    def _obj_to_raw(
        self,
        obj: pdfium.PdfTextObj,
        text_page: pdfium.PdfTextPage,
        path_objects: list,
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

        # Récupère la matrice
        try:
            m = obj.get_matrix()
            matrix = (m.a, m.b, m.c, m.d, m.e, m.f)
            # Scale verticale = sqrt(c² + d²) pour les matrices avec rotation
            import math
            scale = math.sqrt(m.c**2 + m.d**2)
            if scale > 0.1:
                font_size = font_size * scale  # ← la vraie taille
        except Exception:
            matrix = (1.0, 0.0, 0.0, 1.0, L, B)


        # Si font_size est 0 ou absurde (cas Elsevier matrice scale)
        # on estime depuis la hauteur de la bbox
        if font_size <= 0 or font_size > 200:
            font_size = abs(T - B)

        # if ' ' in text and len(text) < 15:
        #     print(f"MOT COUPÉ: '{text}' bbox=({L:.1f},{B:.1f},{R:.1f},{T:.1f})")

        # Filtre les objets dont la hauteur est aberrante
        # (cellules de tableaux Elsevier encodées avec bbox pleine hauteur)
        bbox_height = abs(T - B)
        bbox_width  = abs(R - L)

        # Un objet texte normal : hauteur < 3× sa largeur
        # Un objet tableau Elsevier : hauteur >> largeur (ratio inversé)
        # if bbox_height > 50 and bbox_height > bbox_width * 3:
        #     logger.debug(f"  Objet tableau ignoré: h={bbox_height:.1f} w={bbox_width:.1f} '{text[:20]}'")
        #     return None

        # if abs(T - B) > 50:
        #    print(f"OBJET GÉANT: h={abs(T-B):.1f} text='{text[:30]}' font={font_size:.1f}")


        # Filtre les guillemets/apostrophes isolés parasites
        if text in {'"', "'", "''", '""', '"', '"', ''', '''}:
            return None

        import ctypes

        try:
            r = ctypes.c_uint()
            g = ctypes.c_uint()
            b = ctypes.c_uint()
            a = ctypes.c_uint()
            ok = pdfium_c.FPDFPageObj_GetFillColor(obj.raw, r, g, b, a)
            if ok:
                color = (r.value / 255.0, g.value / 255.0, b.value / 255.0)
                # print(f"  COLOR: r={r.value} g={g.value} b={b.value} | text='{text[:20]}'")
            else:
                color = (0.0, 0.0, 0.0)
        except Exception as e:
            print(f"  COLOR erreur: {e}")
            color = (0.0, 0.0, 0.0)
        
        # print(f"font={font_size:.1f} | matrix=({m.a:.2f},{m.b:.2f},{m.c:.2f},{m.d:.2f}) | scale={scale:.2f} | text='{text[:15]}'")
        
     
        font = obj.get_font()
        raw_font_name = font.get_base_name() # Ex: "AdvEPSTIM+Bold"
        font_name_lower = raw_font_name.lower()
        
        
        # Détection du gras
        weight = font.get_weight()
        is_bold = weight >= 600 or "bold" in font_name_lower
        
        # Détection de l'italique
        is_italic = any(x in font_name_lower for x in ["italic", "oblique", "-it"])
        
        # Nettoyage du nom pour le CSS (on garde le radical)
        # On enlève les préfixes Elsevier (Adv...) et les suffixes de style
        clean_name = raw_font_name.split('+')[-1]
        for term in ["bold", "italic", "oblique", "regular", "-", "pt"]:
            clean_name = clean_name.lower().replace(term.lower(), "")
        clean_name = clean_name.strip().capitalize()



        # --- DÉTECTION DU FOND (Sondage) ---
        # On cherche si un rectangle est "sous" ce texte
        bg_color = (255, 255, 255) # Blanc par défaut
        for path in path_objects:
            pL, pB, pR, pT = path["bounds"]
            # Si le rectangle contient le centre du texte, c'est son fond
            if pL <= (L+R)/2 <= pR and pB <= (B+T)/2 <= pT:
                fr, fg, fb, fa = path["fill_color"]
                bg_color = (fr, fg, fb)
                break # On prend le premier trouvé (le plus proche en Z-order)

        
           

        

        return RawObject(
            text=text,
            left=L, 
            bottom=B, 
            right=R, 
            top=T,
            font_size=font_size,
            matrix=matrix,
            color=color,
            font_name=clean_name if clean_name else "Serif",
            font_weight=700 if is_bold else 400,
            is_italic=is_italic,
             bg_color=bg_color
        )