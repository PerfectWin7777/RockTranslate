"""
translation_viewer.py — Rendu PDF via PDFium (logique finale)
Chemin : D:/Projets/RockTranslate/src/ui/translation_viewer.py

Stratégie arrêtée :
  - PDFium pour lire ET écrire (meilleure fidélité que PyMuPDF)
  - Option A : matrice originale conservée, font_size=1.0 (fix Elsevier)
  - Blocs noirs → traduits (reflow mot par mot)
  - Blocs bleus / URLs / emails → conservés tels quels
  - Cache blanc objet par objet (bbox exacte de chaque RawObject)
  - Reflow du texte traduit dans la zone du bloc original
"""

import os
import shutil
import ctypes
import math
from collections import Counter

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from ui.pdf_viewer import PDFViewer
from core.domain import Paragraph, Block, RawObject


# ─────────────────────────────────────────────
# Helpers PDFium bas niveau
# ─────────────────────────────────────────────

def _get_fill_color(obj_raw) -> tuple[int, int, int, int]:
    """Lit la couleur fill RGBA via pointeurs ctypes."""
    r, g, b, a = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    ok = pdfium_c.FPDFPageObj_GetFillColor(obj_raw, r, g, b, a)
    if ok:
        return (r.value, g.value, b.value, a.value)
    return (0, 0, 0, 255)


def _set_text_utf16(text_obj, text: str):
    """Encode et injecte le texte en UTF-16LE dans un objet PDFium."""
    print(f"  UTF16 input: '{text[:30]}' → {[hex(ord(c)) for c in text[:5]]}")
    utf16 = text.encode("utf-16-le") + b"\x00\x00"
    buf = (ctypes.c_ubyte * len(utf16)).from_buffer_copy(utf16)
    pdfium_c.FPDFText_SetText(
        text_obj,
        ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort))
    )


def _get_true_font_size(raw_obj: RawObject) -> float:
    """
    font_size est déjà corrigé dans pdf_extractor (scale appliquée).
    On clamp juste pour éviter les valeurs aberrantes.
    """
    return max(6.0, min(raw_obj.font_size, 72.0))


def _dominant_color(block: Block) -> tuple[int, int, int]:
    """
    Retourne la couleur dominante du bloc (vote par nombre de caractères).
    Couleur en RGB 0-255.
    """
    counts: Counter = Counter()
    for line in block.lines:
        for span in line.spans:
            for obj in span.raw_objects:
                # obj.color est en float (0.0-1.0) depuis pdf_extractor
                # On convertit en int 0-255 pour la comparaison
                c = tuple(int(v * 255) for v in obj.color)
                counts[c] += len(obj.text)
    if not counts:
        return (0, 0, 0)
    return counts.most_common(1)[0][0]



def _make_white_rect(page_raw, L: float, B: float, R: float, T: float, pad: float = 0.5):
    """Insère un rectangle blanc pour cacher un objet texte."""
    rect = pdfium_c.FPDFPageObj_CreateNewPath(L - pad, B - pad)
    pdfium_c.FPDFPath_LineTo(rect, R + pad, B - pad)
    pdfium_c.FPDFPath_LineTo(rect, R + pad, T + pad)
    pdfium_c.FPDFPath_LineTo(rect, L - pad, T + pad)
    pdfium_c.FPDFPath_Close(rect)
    pdfium_c.FPDFPageObj_SetFillColor(rect, 255, 255, 255, 255)
    pdfium_c.FPDFPath_SetDrawMode(rect, 1, 0)
    pdfium_c.FPDFPage_InsertObject(page_raw, rect)


def _write_word(doc_raw, page_raw, font, word: str,
                x: float, y: float, fs: float,
                color: tuple[int, int, int] = (0, 0, 0)):
    """
    Écrit un mot à (x, y) avec la taille fs.
    Règle unique : CreateTextObj(fs) + matrice identité + position.
    fs EST la taille finale — pas de double scale.
    """
    text_obj = pdfium_c.FPDFPageObj_CreateTextObj(doc_raw, font, fs)
    _set_text_utf16(text_obj, word)
 
    r, g, b = color
    pdfium_c.FPDFPageObj_SetFillColor(text_obj, r, g, b, 255)
 
    raw_m = pdfium_c.FS_MATRIX()
    raw_m.a = 1.0   # identité — scale déjà dans CreateTextObj
    raw_m.b = 0.0
    raw_m.c = 0.0
    raw_m.d = 1.0   # identité
    raw_m.e = x     # position X
    raw_m.f = y     # position Y
    pdfium_c.FPDFPageObj_SetMatrix(text_obj, raw_m)
    pdfium_c.FPDFPage_InsertObject(page_raw, text_obj)
 



def _simulate_height(text: str, fs: float, width: float) -> float:
    """
    Simule la hauteur totale sans rien écrire.
    Retourne la hauteur en pts nécessaire pour faire tenir le texte.
    """
    words = text.split()
    if not words:
        return 0.0
 
    line_height = fs * 1.25
    char_width  = fs * 0.52
    space_width = fs * 0.25
 
    x     = 0.0
    lines = 1
    for word in words:
        word_w = len(word) * char_width
        if x + word_w > width and x > 0:
            x = 0.0
            lines += 1
        x += word_w + space_width
 
    return lines * line_height
 
def _build_char_widths(page: pdfium.PdfPage) -> dict[str, float]:
    """Retourne {char: largeur_en_pts} — largeur absolue sur la page."""
    text_page  = page.get_textpage()
    char_count = pdfium_c.FPDFText_CountChars(text_page)
    widths: dict[str, list[float]] = {}
    
    for i in range(char_count):
        left   = ctypes.c_double()
        right  = ctypes.c_double()
        bottom = ctypes.c_double()
        top    = ctypes.c_double()
        ok = pdfium_c.FPDFText_GetCharBox(text_page, i, left, right, bottom, top)
        if not ok:
            continue
        w = right.value - left.value
        h = abs(top.value - bottom.value)  # hauteur ≈ font_size réelle
        if w <= 0 or h <= 0:
            continue
        char_code = pdfium_c.FPDFText_GetUnicode(text_page, i)
        if char_code == 0:
            continue
        try:
            char = chr(char_code)
        except Exception:
            continue
        # On stocke (largeur, hauteur) pour calculer le ratio w/h
        widths.setdefault(char, []).append((w, h))
    
    # Ratio w/h = proportion indépendante de la taille
    result = {}
    for c, pairs in widths.items():
        ratios = [w/h for w, h in pairs if h > 0]
        if ratios:
            result[c] = sum(ratios) / len(ratios)
    return result



def _measure_word(word: str, char_widths: dict[str, float], fallback_fs: float) -> float:
    """
    Mesure la largeur d'un mot en pts depuis le cache de métriques.
    Fallback : 0.52 * fs si le caractère est inconnu.
    """
    total = 0.0
    for ch in word:
        total += char_widths.get(ch, fallback_fs * 0.52)
    return total

def _reflow_text(doc_raw, page_raw, font,
                 translated_text: str,
                 block,
                 ref_matrix: tuple,
                 char_widths: dict,
                 color: tuple = (0, 0, 0)):

    import math
    ma, mb, mc, md, me, mf = ref_matrix
    fs_original = math.sqrt(mc**2 + md**2)
    if fs_original < 1.0:
        nb_lines = max(1, len(block.lines))
        fs_original = abs(block.top - block.bottom) / nb_lines / 1.25
    fs_original = max(5.0, min(fs_original, 72.0))

    block_width  = abs(block.right - block.left)
    block_height = abs(block.top   - block.bottom)
    line_height  = fs_original * 1.25

    def measure_word(word: str) -> float:
        """Mesure la largeur réelle d'un mot via GetBounds — sans GenerateContent."""
        tmp = pdfium_c.FPDFPageObj_CreateTextObj(doc_raw, font, fs_original)
        _set_text_utf16(tmp, word)
        raw_m = pdfium_c.FS_MATRIX()
        raw_m.a = 1.0; raw_m.b = 0.0
        raw_m.c = 0.0; raw_m.d = 1.0
        raw_m.e = 0.0; raw_m.f = 0.0  # position 0,0 pour mesure
        pdfium_c.FPDFPageObj_SetMatrix(tmp, raw_m)
        pdfium_c.FPDFPage_InsertObject(page_raw, tmp)
        
        L = ctypes.c_float(); R = ctypes.c_float()
        B = ctypes.c_float(); T = ctypes.c_float()
        pdfium_c.FPDFPageObj_GetBounds(tmp, L, B, R, T)
        w = R.value - L.value
        
        # Supprime l'objet temporaire
        pdfium_c.FPDFPage_RemoveObject(page_raw, tmp)
        pdfium_c.FPDFPageObj_Destroy(tmp)
        return max(w, fs_original * 0.2)

    # Mesure l'espace
    space_w = measure_word(" ")
    if space_w <= 0:
        space_w = fs_original * 0.28

    # Simulation pour font scaling
    def simulate(fs_scale: float) -> float:
        x, lines = 0.0, 1
        for word in translated_text.split():
            ww = measure_word(word) * fs_scale
            sw = space_w * fs_scale
            if x + ww > block_width and x > 0:
                x = 0.0
                lines += 1
            x += ww + sw
        return lines * fs_original * fs_scale * 1.25

    # Font scaling si nécessaire
    needed_h = simulate(1.0)
    fs_scale = 1.0
    if needed_h > block_height and needed_h > 0:
        fs_scale = max((block_height / needed_h) * 0.95, 5.0 / fs_original)

    target_fs   = fs_original * fs_scale
    line_height = target_fs * 1.25

    # Écriture finale mot par mot avec target_fs
    words = translated_text.split()
    x = block.left
    y = block.top - line_height

    for word in words:
        # Mesure à target_fs
        tmp = pdfium_c.FPDFPageObj_CreateTextObj(doc_raw, font, target_fs)
        _set_text_utf16(tmp, word)
        raw_m = pdfium_c.FS_MATRIX()
        raw_m.a = 1.0; raw_m.b = 0.0
        raw_m.c = 0.0; raw_m.d = 1.0
        raw_m.e = 0.0; raw_m.f = 0.0
        pdfium_c.FPDFPageObj_SetMatrix(tmp, raw_m)
        pdfium_c.FPDFPage_InsertObject(page_raw, tmp)
        L = ctypes.c_float(); R = ctypes.c_float()
        B = ctypes.c_float(); T = ctypes.c_float()
        pdfium_c.FPDFPageObj_GetBounds(tmp, L, B, R, T)
        word_w = R.value - L.value
        pdfium_c.FPDFPage_RemoveObject(page_raw, tmp)
        pdfium_c.FPDFPageObj_Destroy(tmp)

        sw = space_w * fs_scale

        if x + word_w > block.right and x > block.left:
            x = block.left
            y -= line_height

        if y < block.bottom - (block_height * 0.5 + fs_original):
            break

        _write_word(doc_raw, page_raw, font,
                    word + " ", x, y, target_fs, color)

        x += word_w + sw







# ─────────────────────────────────────────────
# TranslationViewer
# ─────────────────────────────────────────────

class TranslationViewer(PDFViewer):
    """
    Panneau droit de RockTranslate.
    Affiche le PDF original puis reconstruit avec les traductions.
    """

    def __init__(self):
        super().__init__()
        self.lbl_title.setText("Moteur de Rendu : PDFium Native")
        self._original_path: str | None = None
        self._output_path   = os.path.abspath("translated_preview.pdf")
        self._font          = None   # handle font PDFium (chargé une fois)

    # ──────────────────────────────────────────
    # API publique
    # ──────────────────────────────────────────

    def init_shadow(self, original_path: str):
        """Charge l'original dans le viewer droit en attendant la traduction."""
        self._original_path = original_path
        shutil.copy(original_path, self._output_path)
        self.load_pdf(self._output_path)

    def apply_translations(self, paragraphs: list[Paragraph]):
        """
        Reconstruit le PDF avec les textes traduits.
        Appelé depuis main_window après la simulation ou la vraie traduction.
        """
        if not self._original_path:
            print("❌ _original_path non défini")
            return

        print(f"✅ Reconstruction — {len(paragraphs)} paragraphes")
        curr_page = self.get_current_page_idx()

        # ── Ouverture du PDF original ──────────────────────────
        doc = pdfium.PdfDocument(self._original_path)

        # Charge la police une seule fois pour tout le document
        font_helv = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")

        # ── Regroupe les paragraphes par page ──────────────────
        pages_dict: dict[int, list[Paragraph]] = {}
        for para in paragraphs:
            if not para.translated_text:
                continue
            page_idx = para.blocks[0].page_number - 1
            pages_dict.setdefault(page_idx, []).append(para)

        # ── Traitement page par page ───────────────────────────
        for page_idx, page_paras in pages_dict.items():
            if page_idx < 0 or page_idx >= len(doc):
                continue

            page     = doc[page_idx]
            page_raw = page.raw

            # ← NOUVEAU : cache des largeurs pour cette page
            char_widths = _build_char_widths(page)
            space_width = char_widths.get(' ', None)  # largeur espace réelle
            if not space_width or space_width <= 0:
                space_width = None  # sera calculé depuis fs dans reflow
            
            print(f"  Page {page_idx+1} : {len(char_widths)} caractères mesurés")


            for para in page_paras:
                block = para.blocks[0]
                text  = para.translated_text

                # ── Décision : traduire ou skipper ? ──────────
                if not para.translated_text:
                    continue  # pas traduit = pas écrasé

                # ── Récupère fs depuis le premier RawObject ────
                first_raw = None
                # Collecte tous les raw_objects du bloc
                all_raws = [o for line in block.lines 
                            for span in line.spans 
                            for o in span.raw_objects]

                if all_raws:
                    # Prend celui avec la hauteur médiane (plus robuste que le premier)
                    all_raws.sort(key=lambda o: o.height)
                    first_raw = all_raws[len(all_raws) // 2]

                fs = _get_true_font_size(first_raw) if first_raw else 9.0

                # ── Cache tous les RawObjects du bloc ──────────
                # Récupère ref_matrix depuis le premier RawObject du bloc
                ref_matrix = (1.0, 0.0, 0.0, 10.0, block.left, block.top)  # fallback
                for line in block.lines:
                    for span in line.spans:
                        if span.raw_objects:
                            ref_matrix = span.raw_objects[0].matrix
                            break
                    else:
                        continue
                    break

                for line in block.lines:
                    for span in line.spans:
                        for raw_obj in span.raw_objects:
                            _make_white_rect(
                                page_raw,
                                raw_obj.left, raw_obj.bottom,
                                raw_obj.right, raw_obj.top,
                            )
                
                # Récupère le handle de police depuis l'objet PDFium original
                # via text_page sur la page courante
                original_font_raw = None
                text_page = page.get_textpage()
                for obj in page.get_objects():
                    if not isinstance(obj, pdfium.PdfTextObj):
                        continue
                    try:
                        bounds = obj.get_bounds()
                        # Cherche l'objet qui correspond à notre first_raw
                        if (abs(bounds[0] - first_raw.left) < 1.0 and 
                            abs(bounds[1] - first_raw.bottom) < 1.0):
                            font_obj = obj.get_font()
                            original_font_raw = font_obj.raw
                            break
                    except:
                        continue

                font_to_use = original_font_raw if original_font_raw else font_helv
                


                # ── Reflow du texte traduit dans la zone ───────
                _reflow_text(
                    doc.raw, page_raw, font_to_use,
                    text, block, ref_matrix, char_widths,
                    color=(0, 0, 0),
                )

                # print(f"  OK  page={page_idx+1} fs={fs:.1f} '{text[:40]}'")

            # Valide les changements de la page
            pdfium_c.FPDFPage_GenerateContent(page_raw)

        # ── Sauvegarde ─────────────────────────────────────────
        print("Sauvegarde...")
        self.clear()  # libère le verrou Windows sur le fichier

        try:
            doc.save(self._output_path)
        except Exception as e:
            import time
            self._output_path = os.path.abspath(f"preview_{int(time.time())}.pdf")
            doc.save(self._output_path)
            print(f"  Fichier alternatif : {self._output_path}")

        doc.close()

        self.load_pdf(self._output_path)
        self.goto_page(curr_page)
        print(f"✅ Reconstruction terminée : {self._output_path}")

    def apply_all_translations(self, paragraphs: list[Paragraph]):
        """Alias — appelé depuis main_window._on_finished()."""
        self.apply_translations(paragraphs)

    def clear_translations(self):
        """Recharge l'original sans traduction."""
        if self._original_path:
            self.init_shadow(self._original_path)