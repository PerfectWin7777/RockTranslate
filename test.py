import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import ctypes

def final_massacre_test(pdf_path, output_path):
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[0]
    text_page = page.get_textpage()
    
    data_to_inject = []
    print("--- PHASE 1 : COLLECTE DES DONNÉES ---")
    
    for obj in page.get_objects():
        if isinstance(obj, pdfium.PdfTextObj):
            bounds = obj.get_bounds()
            text = text_page.get_text_bounded(*bounds)
            if text.strip():
                m = obj.get_matrix()
                # ON STOCKE LES VALEURS BRUTES POUR ÉVITER L'ERREUR D'UNPACKING
                data_to_inject.append({
                    'text': text.strip(),
                    'bounds': bounds, 
                    'matrix_vals': (m.a, m.b, m.c, m.d, m.e, m.f),
                    'size': obj.get_font_size()
                })

    print(f"--- PHASE 2 : CACHE ET RÉ-INJECTION ---")
    font = pdfium_c.FPDFText_LoadStandardFont(doc.raw, b"Helvetica-Bold")
    
    for item in data_to_inject:
        L, B, R, T = item['bounds']
        # Petit padding de sécurité pour bien cacher
        L, B, R, T = L-0.5, B-0.5, R+0.5, T+0.5

        # 1. RECTANGLE BLANC (Cache)
        rect = pdfium_c.FPDFPageObj_CreateNewPath(L, B)
        pdfium_c.FPDFPath_LineTo(rect, R, B)
        pdfium_c.FPDFPath_LineTo(rect, R, T)
        pdfium_c.FPDFPath_LineTo(rect, L, T)
        pdfium_c.FPDFPath_Close(rect)
        
        pdfium_c.FPDFPageObj_SetFillColor(rect, 255, 255, 255, 255)
        # On utilise le nom de fonction correct pour les objets Path
        pdfium_c.FPDFPath_SetDrawMode(rect, 1, 0) 
        pdfium_c.FPDFPage_InsertObject(page.raw, rect)

        # 2. TEXTE FIX (Injection)
        text_obj = pdfium_c.FPDFPageObj_CreateTextObj(doc.raw, font, item['size'])
        placeholder = f"FIX: {item['text'][:10]}"
        utf16_bytes = placeholder.encode("utf-16-le") + b"\x00\x00"
        utf16_buffer = (ctypes.c_ubyte * len(utf16_bytes)).from_buffer_copy(utf16_bytes)
        pdfium_c.FPDFText_SetText(text_obj, ctypes.cast(utf16_buffer, ctypes.POINTER(ctypes.c_ushort)))
        
        pdfium_c.FPDFPageObj_SetFillColor(text_obj, 0, 0, 0, 255) # Noir
        
        # CONSTRUCTION DE LA MATRICE SANS ERREUR
        raw_matrix = pdfium_c.FS_MATRIX()
        raw_matrix.a, raw_matrix.b, raw_matrix.c, raw_matrix.d, raw_matrix.e, raw_matrix.f = item['matrix_vals']
        pdfium_c.FPDFPageObj_SetMatrix(text_obj, raw_matrix)
        
        pdfium_c.FPDFPage_InsertObject(page.raw, text_obj)

    # FIN ET SAUVEGARDE
    pdfium_c.FPDFPage_GenerateContent(page.raw)
    doc.save(output_path)
    doc.close()
    print(f"\nTERMINE ! Fichier : {output_path}")

final_massacre_test("Nsangou Ngapna et al._ASR_2024.pdf", "MASSACRE_FINAL.pdf")