"""
debug_extractor.py — Validation visuelle du pipeline complet
Chemin : D:/Projets/RockTranslate/debug_extractor.py

Lance depuis la racine du projet :
    python debug_extractor.py

Montre les paragraphes reconstruits sur le vrai PDF Elsevier.
Critères de succès :
    ✅ > 200 objets par page
    ✅ Paragraphes lisibles et cohérents
    ✅ Phrases cross-page fusionnées
    ✅ 2 colonnes détectées sur les bonnes pages
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from loguru import logger
from core.pdf_extractor import PDFExtractor
from core.spatial_clusterers import SpatialClusterer

# ── Config loguru : affichage clair dans le terminal ──────────────────
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    level="DEBUG",
    colorize=True,
)

PDF_PATH = r"D:\Projets\RockTranslate\Nsangou Ngapna et al._ASR_2024.pdf"
MAX_PAGES = 3        # Limiter pour le debug (mettre None pour tout le PDF)
SHOW_OBJECTS = True # Mettre True pour voir les RawObjects bruts


def main():
    logger.info("=" * 60)
    logger.info("RockTranslate — Debug Pipeline")
    logger.info("=" * 60)

    # ── ÉTAPE 1 : Extraction ─────────────────────────────────────────
    extractor = PDFExtractor(PDF_PATH)
    document  = extractor.extract()

    sc = SpatialClusterer()
    all_page_blocks = []

    pages_to_process = document.pages[:MAX_PAGES] if MAX_PAGES else document.pages

    for page in pages_to_process:
        logger.info("-" * 50)
        logger.info(f"TRAITEMENT PAGE {page.number}")
        logger.info("-" * 50)

        if SHOW_OBJECTS:
            logger.debug(f"  Objets bruts (10 premiers) :")
            for obj in page.raw_objects[:10]:
                logger.debug(
                    f"    text={obj.text!r:12s} "
                    f"bbox=({obj.left:.1f},{obj.bottom:.1f},{obj.right:.1f},{obj.top:.1f}) "
                    f"fs={obj.font_size:.1f}"
                )

        # ── ÉTAPE 2 : Clustering ─────────────────────────────────────
        blocks = sc.process_page(
            raw_objects=page.raw_objects,
            page_width=page.width,
            page_number=page.number,
        )

        all_page_blocks.append(blocks)

        col_counts = {}
        for b in blocks:
            col_counts[b.column] = col_counts.get(b.column, 0) + 1

        num_cols = max(col_counts.keys(), default=0)
        if num_cols <= 1:
            logger.info(f"  Layout : 1 colonne — {len(blocks)} blocs")
        else:
            logger.info(
                f"  Layout : 2 colonnes — "
                f"{col_counts.get(1, 0)} blocs gauche, "
                f"{col_counts.get(2, 0)} blocs droite"
            )

        # ── ÉTAPE 3 : Affichage paragraphes ──────────────────────────
        logger.info(f"  Paragraphes reconstruits :")
        for i, block in enumerate(blocks):
            preview = block.text[:120].replace("\n", " ")
            flag = ""
            if block.continues_on_next_page:
                flag = " ⚠️  [→ suite page suivante]"
            if block.continued_from_prev_page:
                flag = " ⚠️  [← suite de la page précédente]"
            logger.info(f"    [{i+1:02d}] col={block.column} | {preview!r}{flag}")

    # ── ÉTAPE 4 : Cross-page ─────────────────────────────────────────
    if len(all_page_blocks) >= 2:
        logger.info("=" * 60)
        logger.info("DÉTECTION CROSS-PAGE")
        logger.info("=" * 60)

        for i in range(len(all_page_blocks) - 1):
            p_blocks, n_blocks = sc.merge_cross_page(
                all_page_blocks[i],
                all_page_blocks[i + 1]
            )
            cross = [b for b in p_blocks if b.continues_on_next_page]
            if cross:
                logger.warning(
                    f"  Page {i+1}→{i+2} : phrase coupée détectée"
                )
                logger.warning(f"    Fin page {i+1}   : {cross[-1].last_line_text!r}")
                logger.warning(f"    Début page {i+2} : {all_page_blocks[i+1][0].first_line_text!r}")
            else:
                logger.info(f"  Page {i+1}→{i+2} : pas de coupure cross-page")

    # ── ÉTAPE 5 : Paragraphes finaux (prêts pour le LLM) ─────────────
    logger.info("=" * 60)
    logger.info("PARAGRAPHES FINAUX → LLM")
    logger.info("=" * 60)

    flat_blocks = [b for page_b in all_page_blocks for b in page_b]
    paragraphs  = sc.build_paragraphs(flat_blocks)

    logger.info(f"  Total : {len(paragraphs)} paragraphes prêts pour traduction")
    for i, para in enumerate(paragraphs):
        cross_flag = " [CROSS-PAGE]" if para.is_cross_page else ""
        logger.info(f"  [{i+1:02d}]{cross_flag} {para.text[:100]!r}")

    logger.info("=" * 60)
    logger.info("✅ Pipeline OK — prêt pour branchement LLM")
    logger.info("=" * 60)
    
    import json
    page1_data = []
    for obj in document.pages[0].raw_objects:
        page1_data.append({
            "t": obj.text,
            "b": (obj.left, obj.bottom, obj.right, obj.top),
            "fs": obj.font_size
        })
    with open("page1_dump.json", "w") as f:
        json.dump(page1_data, f)

if __name__ == "__main__":
    main()