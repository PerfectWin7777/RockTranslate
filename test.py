# import pypdfium2 as pdfium
# import pypdfium2.raw as pdfium_c
# import ctypes

# def final_massacre_test(pdf_path, output_path):
#     doc = pdfium.PdfDocument(pdf_path)
#     page = doc[0]
#     text_page = page.get_textpage()
    
#     data_to_inject = []
#     print("--- PHASE 1 : COLLECTE DES DONNÉES ---")
    
#     for obj in page.get_objects():
#         if isinstance(obj, pdfium.PdfTextObj):
#             bounds = obj.get_bounds()
#             text = text_page.get_text_bounded(*bounds)
#             if text.strip():
#                 m = obj.get_matrix()
#                 # ON STOCKE LES VALEURS BRUTES POUR ÉVITER L'ERREUR D'UNPACKING
#                 data_to_inject.append({
#                     'text': text.strip(),
#                     'bounds': bounds, 
#                     'matrix_vals': (m.a, m.b, m.c, m.d, m.e, m.f),
#                     'size': obj.get_font_size()
#                 })

#     print(f"--- PHASE 2 : CACHE ET RÉ-INJECTION ---")
#     font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica-Bold")
    
#     for item in data_to_inject:
#         L, B, R, T = item['bounds']
#         # Petit padding de sécurité pour bien cacher
#         L, B, R, T = L-0.5, B-0.5, R+0.5, T+0.5

#         # 1. RECTANGLE BLANC (Cache)
#         rect = pdfium_c.FPDFPageObj_CreateNewPath(L, B)
#         pdfium_c.FPDFPath_LineTo(rect, R, B)
#         pdfium_c.FPDFPath_LineTo(rect, R, T)
#         pdfium_c.FPDFPath_LineTo(rect, L, T)
#         pdfium_c.FPDFPath_Close(rect)
        
#         pdfium_c.FPDFPageObj_SetFillColor(rect, 255, 255, 255, 255)
#         # On utilise le nom de fonction correct pour les objets Path
#         pdfium_c.FPDFPath_SetDrawMode(rect, 1, 0) 
#         pdfium_c.FPDFPage_InsertObject(page.raw, rect)

#         # 2. TEXTE FIX (Injection)
#         text_obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, item['size'])
#         placeholder = f"FIX: {item['text'][:10]}"
#         utf16_bytes = placeholder.encode("utf-16-le") + b"\x00\x00"
#         utf16_buffer = (ctypes.c_ubyte * len(utf16_bytes)).from_buffer_copy(utf16_bytes)
#         pdfium_c.FPDFText_SetText(text_obj, ctypes.cast(utf16_buffer, ctypes.POINTER(ctypes.c_ushort)))
        
#         pdfium_c.FPDFPageObj_SetFillColor(text_obj, 0, 0, 0, 255) # Noir
        
#         # CONSTRUCTION DE LA MATRICE SANS ERREUR
#         raw_matrix = pdfium_c.FS_MATRIX()
#         raw_matrix.a, raw_matrix.b, raw_matrix.c, raw_matrix.d, raw_matrix.e, raw_matrix.f = item['matrix_vals']
#         pdfium_c.FPDFPageObj_SetMatrix(text_obj, raw_matrix)
        
#         pdfium_c.FPDFPage_InsertObject(page.raw, text_obj)

#     # FIN ET SAUVEGARDE
#     pdfium_c.FPDFPage_GenerateContent(page.raw)
#     doc.save(output_path)
#     doc.close()
#     print(f"\nTERMINE ! Fichier : {output_path}")

# final_massacre_test("Nsangou Ngapna et al._ASR_2024.pdf", "MASSACRE_FINAL.pdf")

















"""
test_massacre_color.py — Test PDFium : copie objet par objet avec couleur exacte
Lance : python test_massacre_color.py mon_fichier.pdf
"""
import sys
import ctypes
import math

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c


def get_true_font_size(obj, m):
    """Calcule la vraie taille depuis la matrice (fix Elsevier)."""
    try:
        nominal = obj.get_font_size()
        scale = math.sqrt(m.c**2 + m.d**2)
        if scale > 0.1:
            return nominal * scale
        return nominal
    except Exception:
        return 10.0


def get_fill_color(obj_raw):
    """Lit la couleur fill via pointeurs ctypes."""
    r = ctypes.c_uint()
    g = ctypes.c_uint()
    b = ctypes.c_uint()
    a = ctypes.c_uint()
    ok = pdfium_c.FPDFPageObj_GetFillColor(obj_raw, r, g, b, a)
    if ok:
        return (r.value, g.value, b.value, a.value)
    return (0, 0, 0, 255)


def set_text_utf16(text_obj, text: str):
    """Encode et injecte le texte en UTF-16LE dans un objet PDFium."""
    utf16 = text.encode("utf-16-le") + b"\x00\x00"
    buf = (ctypes.c_ubyte * len(utf16)).from_buffer_copy(utf16)
    pdfium_c.FPDFText_SetText(
        text_obj,
        ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort))
    )


def massacre_with_color(pdf_path: str, output_path: str):
    """
    Pour chaque objet texte de la page 1 :
      1. Cache avec rectangle blanc
      2. Réécrit le texte avec sa vraie couleur et taille
    But : valider que PDFium peut reproduire fidèlement objet par objet.
    """
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[0]
    page_raw = page.raw
    text_page = page.get_textpage()

    # ── PHASE 1 : collecte ───────────────────────────────────────
    print("PHASE 1 : Collecte des objets...")
    collected = []

    for obj in page.get_objects():
        if not isinstance(obj, pdfium.PdfTextObj):
            continue
        try:
            bounds = obj.get_bounds()
            L, B, R, T = bounds
            if R <= L or T <= B:
                continue

            text = text_page.get_text_bounded(L, B, R, T).strip()
            if not text:
                continue

            m = obj.get_matrix()
            fs = get_true_font_size(obj, m)
            r, g, b, a = get_fill_color(obj.raw)

            collected.append({
                "text":   text,
                "L": L, "B": B, "R": R, "T": T,
                "fs":     fs,
                "color":  (r, g, b, a),
                "matrix": (m.a, m.b, m.c, m.d, m.e, m.f),
            })
        except Exception as e:
            print(f"  SKIP objet : {e}")
            continue

    print(f"  → {len(collected)} objets collectés")

    # ── PHASE 2 : chargement de la police ────────────────────────
    # Helvetica pour le test — on remplacera par la police originale plus tard
    font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica")
    font_bold = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica-Bold")

    # ── PHASE 3 : cache blanc + réécriture ───────────────────────
    print("PHASE 3 : Cache + réécriture...")

    for i, item in enumerate(collected):
        L, B, R, T = item["L"], item["B"], item["R"], item["T"]
        pad = 0.5

        # — Cache blanc —
        rect_obj = pdfium_c.FPDFPageObj_CreateNewPath(L - pad, B - pad)
        pdfium_c.FPDFPath_LineTo(rect_obj, R + pad, B - pad)
        pdfium_c.FPDFPath_LineTo(rect_obj, R + pad, T + pad)
        pdfium_c.FPDFPath_LineTo(rect_obj, L - pad, T + pad)
        pdfium_c.FPDFPath_Close(rect_obj)
        pdfium_c.FPDFPageObj_SetFillColor(rect_obj, 255, 255, 255, 255)
        pdfium_c.FPDFPath_SetDrawMode(rect_obj, 1, 0)
        pdfium_c.FPDFPage_InsertObject(page_raw, rect_obj)

        # — Nouvel objet texte —
        fs = max(6.0, min(item["fs"], 72.0))
        text_obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, fs)

        # Texte : préfixe pour voir facilement ce qui a été réécrit
        new_text = item['text']
        set_text_utf16(text_obj, new_text)

        # Couleur originale
        r, g, b, a = item["color"]
        pdfium_c.FPDFPageObj_SetFillColor(text_obj, r, g, b, a)

        # Matrice : on garde e,f (position) et on remet scale identité
        # pour éviter le bug Elsevier matrice 1pt
        ma, mb, mc, md, me, mf = item["matrix"]
        raw_m = pdfium_c.FS_MATRIX()
        # Matrice normalisée : juste position, pas de scale
        raw_m.a = 1.0
        raw_m.b = 0.0
        raw_m.c = 0.0
        raw_m.d = 1.0
        raw_m.e = me  # position X
        raw_m.f = mf  # position Y
        pdfium_c.FPDFPageObj_SetMatrix(text_obj, raw_m)

        pdfium_c.FPDFPage_InsertObject(page_raw, text_obj)

        if i < 10:  # log les 10 premiers
            print(f"  [{i}] fs={fs:.1f} color=({r},{g},{b}) pos=({me:.0f},{mf:.0f}) '{item['text'][:25]}'")

    # ── PHASE 4 : sauvegarde ─────────────────────────────────────
    print("PHASE 4 : Sauvegarde...")
    pdfium_c.FPDFPage_GenerateContent(page_raw)
    doc.save(output_path)
    doc.close()
    print(f"✅ Fichier : {output_path}")
    print()
    print("CE QUE TU DOIS VOIR DANS LE PDF :")
    print("  - Chaque objet texte remplacé par [texte original]")
    print("  - Couleur bleue conservée pour les liens/citations")
    print("  - Taille approximativement correcte")
    print("  - Positionnement identique à l'original")


if __name__ == "__main__":
    # if len(sys.argv) < 2:
    #     print("Usage: python test_massacre_color.py fichier.pdf")
    #     sys.exit(1)
    # pdf_in = sys.argv[1]
    pdf_out = "_MASSACRE_COLOR.pdf"  # pdf_in.replace(".pdf", "_MASSACRE_COLOR.pdf")
    massacre_with_color("Nsangou Ngapna et al._ASR_2024.pdf", pdf_out)