# src/reconstruction/pdf_builder.py

import os
import fitz  # PyMuPDF
from loguru import logger

def merge_pdfs(pdf_paths: list[str], output_path: str) -> bool:
    """
    Assemble plusieurs fichiers PDF individuels en un seul document PDF unifié.
    
    Args:
        pdf_paths: Liste des chemins d'accès vers les fichiers PDF unitaires.
        output_path: Chemin de destination pour le PDF fusionné final.
        
    Returns:
        bool: True si la fusion a réussi, False en cas d'erreur.
    """
    if not pdf_paths:
        logger.warning("Aucun fichier PDF fourni pour la fusion.")
        return False

    logger.info(f"Début de l'assemblage de {len(pdf_paths)} pages vers : {output_path}")
    
    # Création d'un document PDF vierge
    merged_document = fitz.open()

    try:
        for idx, path in enumerate(pdf_paths):
            if not os.path.exists(path):
                logger.error(f"Fichier manquant lors de la fusion : {path}")
                # Nous continuons malgré tout pour ne pas bloquer l'assemblage global
                continue
            
            # Ouverture temporaire de la page unitaire
            page_doc = fitz.open(path)
            
            # Insertion de toutes les pages du fichier courant (ici, toujours 1 page)
            merged_document.insert_pdf(page_doc)
            page_doc.close()

        # Enregistrement du fichier assemblé avec option d'optimisation (linear=True)
        merged_document.save(output_path, garbage=3, deflate=True)
        merged_document.close()
        
        logger.info(f"Fusion réussie. Document complet généré avec succès : {output_path}")
        return True

    except Exception as e:
        logger.error(f"Erreur durant l'assemblage des PDF : {e}")
        try:
            merged_document.close()
        except Exception:
            pass
        return False