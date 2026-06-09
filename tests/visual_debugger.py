import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import ctypes
from old.pdf_extractor import PDFExtractor
from old.spatial_clusterers import SpatialClusterer

def draw_rect(page_raw, bounds, color=(255, 0, 0), thickness=1):
    """Dessine un rectangle creux (Stroke) via l'API C."""
    L, B, R, T = bounds
    path = pdfium_c.FPDFPageObj_CreateNewPath(L, B)
    pdfium_c.FPDFPath_LineTo(path, R, B)
    pdfium_c.FPDFPath_LineTo(path, R, T)
    pdfium_c.FPDFPath_LineTo(path, L, T)
    pdfium_c.FPDFPath_Close(path)
    
    # Couleur et mode Stroke (bordure)
    pdfium_c.FPDFPageObj_SetStrokeColor(path, color[0], color[1], color[2], 255)
    pdfium_c.FPDFPath_SetDrawMode(path, 0, 1) # 0=Pas de fill, 1=Stroke
    pdfium_c.FPDFPageObj_SetStrokeWidth(path, thickness)
    pdfium_c.FPDFPage_InsertObject(page_raw, path)

def generate_visual_diagnostic(pdf_path, output_path):
    # 1. Extraction et Clustering via ton pipeline
    extractor = PDFExtractor(pdf_path)
    document = extractor.extract()
    sc = SpatialClusterer()
    
    # 2. Re-charger le PDF pour dessiner par-dessus
    pdf = pdfium.PdfDocument(pdf_path)
    
    for page_idx, page_data in enumerate(document.pages):
        page = pdf[page_idx]
        
        # --- DESSIN DES BLOCKS (BLEU) ---
        # On relance le clustering pour cette page
        # 1. Calculer la gouttière globale UNE SEULE FOIS
        all_raw = [page.raw_objects for page in document.pages]
        gutter = sc.find_document_gutter(all_raw, document.pages[0].width)
        print(f"Gouttière globale détectée : {gutter:.1f} pt")

        # 2. Utiliser cette gouttière pour toutes les pages
        blocks = sc.process_page(
            page_data.raw_objects,
            page_data.width,
            page_data.number,
            page_data.height,
            forced_gutter=gutter   # ← nouveau paramètre
        )
        
        for block in blocks:
            # Rectangle BLEU pour le bloc final (Paragraphe)
            draw_rect(page.raw, (block.left, block.bottom, block.right, block.top), 
                      color=(0, 0, 255), thickness=2)
            # print(f"col={block.column}  x={block.left:.1f}-{block.right:.1f}  y={block.bottom:.1f}-{block.top:.1f}  gutter_x={block.gutter_x:.1f}")
            
        # --- DESSIN DES RAW OBJECTS (ROUGE) ---
        for obj in page_data.raw_objects:
            # Rectangle ROUGE pour l'atome extrait
            draw_rect(page.raw, (obj.left, obj.bottom, obj.right, obj.top), 
                      color=(255, 0, 0), thickness=0.5)
            
        # print(f"\n=== PAGE {page_idx+1} — blocs bruts ===")
        # for b in blocks:
        #     print(f"  col={b.column}  x={b.left:.0f}-{b.right:.0f}  y={b.bottom:.0f}-{b.top:.0f}  '{b.text[:40]}'")
        
        # print(f"\n=== PAGE {page_idx+1} — objets larges (raw) ===")
        # for o in page_data.raw_objects:
        #     if (o.right - o.left) > 200:
        #         print(f"  x={o.left:.0f}-{o.right:.0f}  y={o.bottom:.0f}-{o.top:.0f}  '{o.text[:40]}'")

        # Dans le diagnostic, pour chaque page, affiche les blocs triés par top
        # et vérifie si bottom[i] < top[i+1]
        # blocks_sorted = sorted(blocks, key=lambda b: -b.top)
        # for i in range(len(blocks_sorted)-1):
        #     b1 = blocks_sorted[i]
        #     b2 = blocks_sorted[i+1]
        #     if b1.column == b2.column and b1.bottom < b2.top:
        #         print(f"OVERLAP col={b1.column}: bloc1 bottom={b1.bottom:.1f} < bloc2 top={b2.top:.1f}")
        #         print(f"  bloc1: '{b1.text[:40]}'")
        #         print(f"  bloc2: '{b2.text[:40]}'")
         
        # if page_idx == 2:  # page 3 (index 0)
        #     print("\n=== RAW OBJECTS zone y=224-290 ===")
        #     for o in page_data.raw_objects:
        #         if 224 <= o.bottom <= 290:
        #             print(f"  x={o.left:.0f}-{o.right:.0f}  y={o.bottom:.0f}-{o.top:.0f}  '{o.text}'")

        pdfium_c.FPDFPage_GenerateContent(page.raw)
    
    pdf.save(output_path)
    pdf.close()
    print(f"Diagnostic généré : {output_path}")

if __name__ == "__main__":
    generate_visual_diagnostic(
        r"D:\Projets\RockTranslate\1_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf",
        "DIAGNOSTIC.pdf"
    )