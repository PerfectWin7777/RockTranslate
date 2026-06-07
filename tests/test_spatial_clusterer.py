"""
test_spatial_clusterer.py — Validation du SpatialClusterer

3 tests critiques :
  TEST 1 : Abstract reconstruit en 1 bloc cohérent
  TEST 2 : 2 colonnes détectées sur une page Elsevier double-colonne
  TEST 3 : Phrase cross-page correctement détectée et fusionnée
"""


from core.domain import RawObject
from core.spatial_clusterers import SpatialClusterer


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def make_raw(text: str, left: float, bottom: float,
             right: float, top: float, font_size: float = 9.0) -> RawObject:
    """Crée un RawObject avec une matrice identité (cas standard)."""
    return RawObject(
        text=text,
        left=left, bottom=bottom, right=right, top=top,
        font_size=font_size,
        matrix=(1.0, 0.0, 0.0, 1.0, left, bottom)
    )


def run_test(name: str, fn):
    try:
        fn()
        print(f"  ✅  {name}")
    except AssertionError as e:
        print(f"  ❌  {name}")
        print(f"       → {e}")
    except Exception as e:
        print(f"  💥  {name} — exception inattendue : {e}")
        import traceback; traceback.print_exc()


# ──────────────────────────────────────────────────────────────
# TEST 1 : fragments atomiques → 1 bloc cohérent
# ──────────────────────────────────────────────────────────────

def test_abstract_is_one_block():
    """
    Simule les fragments atomiques de l'abstract Elsevier.
    Chaque 'mot' est un RawObject séparé sur la même ligne Y.
    On attend : 1 seul bloc, texte cohérent.
    """
    sc = SpatialClusterer()

    # Ligne 1 de l'abstract — fragments simulant PDFium atomique
    # Y = 700 (coordonnées PDF, origine bas-gauche)
    line1 = [
        make_raw("Complex",  30,  695, 72,  705),
        make_raw("geology",  74,  695, 110, 705),
        make_raw("and",      112, 695, 128, 705),
        make_raw("tectonics", 130, 695, 185, 705),
        make_raw("of",       187, 695, 197, 705),
        make_raw("the",      199, 695, 215, 705),
        make_raw("SW",       217, 695, 234, 705),
    ]

    # Ligne 2 — même Y approx (± 2pt)
    line2 = [
        make_raw("Cameroon",  30, 683, 82,  693),
        make_raw("Atlantic",  84, 683, 133, 693),
        make_raw("Coast",    135, 683, 167, 693),
        make_raw("are",      169, 683, 183, 693),
        make_raw("responsible", 185, 683, 243, 693),
    ]

    # Ligne 3 — nouveau paragraphe (grand gap vertical)
    line3 = [
        make_raw("Introduction", 30, 550, 115, 562, font_size=10.0),
    ]

    raw_objects = line1 + line2 + line3

    blocks = sc.process_page(raw_objects, page_width=595.0, page_number=1)

    # On doit obtenir 2 blocs : abstract + titre section
    assert len(blocks) >= 2, (
        f"Attendu ≥2 blocs, obtenu {len(blocks)}"
    )

    # Le premier bloc (Y le plus haut) doit contenir le début de l'abstract
    # Les blocs sont triés du haut vers le bas → le plus grand Y en premier
    abstract_block = blocks[0]
    assert "Complex" in abstract_block.text, (
        f"Bloc 0 ne contient pas 'Complex'.\n"
        f"       Blocs obtenus : {[(i, b.text[:40]) for i,b in enumerate(blocks)]}"
    )
    assert "responsible" in abstract_block.text, (
        f"Ligne 2 non fusionnée dans le bloc 0 : '{abstract_block.text[:80]}'"
    )

    print(f"       Bloc abstract : '{abstract_block.text[:70]}...'")
    print(f"       Nombre de blocs : {len(blocks)}")


# ──────────────────────────────────────────────────────────────
# TEST 2 : détection de 2 colonnes
# ──────────────────────────────────────────────────────────────

def test_two_columns_detected():
    """
    Simule une page Elsevier avec 2 colonnes.
    Colonne gauche : x_center ≈ 150, colonne droite : x_center ≈ 440
    Page A4 : largeur ≈ 595 pt
    """
    sc = SpatialClusterer()
    PAGE_WIDTH = 595.0

    # Colonne gauche (x: 30 → 270)
    left_col_objects = []
    y = 700
    for i in range(6):
        left_col_objects += [
            make_raw(f"motG{i}a", 30,  y-5, 100, y+5),
            make_raw(f"motG{i}b", 105, y-5, 175, y+5),
            make_raw(f"motG{i}c", 180, y-5, 270, y+5),
        ]
        y -= 20

    # Colonne droite (x: 310 → 560)
    right_col_objects = []
    y = 700
    for i in range(6):
        right_col_objects += [
            make_raw(f"motD{i}a", 310, y-5, 380, y+5),
            make_raw(f"motD{i}b", 385, y-5, 455, y+5),
            make_raw(f"motD{i}c", 460, y-5, 560, y+5),
        ]
        y -= 20

    raw_objects = left_col_objects + right_col_objects

    spans  = sc.cluster_spans(raw_objects)
    lines  = sc.build_lines(spans)
    blocks = sc.build_blocks(lines, page_number=2)
    num_cols = sc.detect_columns(blocks, PAGE_WIDTH)

    assert num_cols == 2, f"Attendu 2 colonnes, obtenu {num_cols}"

    col1_blocks = [b for b in blocks if b.column == 1]
    col2_blocks = [b for b in blocks if b.column == 2]

    assert len(col1_blocks) > 0, "Aucun bloc en colonne 1"
    assert len(col2_blocks) > 0, "Aucun bloc en colonne 2"

    print(f"       Colonnes détectées : {num_cols}")
    print(f"       Blocs col.1 : {len(col1_blocks)}, blocs col.2 : {len(col2_blocks)}")


# ──────────────────────────────────────────────────────────────
# TEST 3 : phrase coupée cross-page
# ──────────────────────────────────────────────────────────────

def test_cross_page_sentence():
    """
    Simule une phrase coupée entre page 1 et page 2.

    Page 1 (fin) : "...variations in erosion rates,"  ← pas de point final
    Page 2 (début) : "in river incision, and in channel..."  ← commence en minuscule
    """
    sc = SpatialClusterer()

    # Dernier bloc de la page 1
    page1_objects = [
        make_raw("variations", 30, 100, 100, 110),
        make_raw("in",        102, 100, 115, 110),
        make_raw("erosion",   117, 100, 163, 110),
        make_raw("rates,",    165, 100, 200, 110),   # ← virgule, pas de point
    ]

    # Premier bloc de la page 2
    page2_objects = [
        make_raw("in",       30, 730, 45,  740),     # ← minuscule
        make_raw("river",    47, 730, 80,  740),
        make_raw("incision,", 82, 730, 136, 740),
        make_raw("and",     138, 730, 158, 740),
        make_raw("in",      160, 730, 174, 740),
        make_raw("channel", 176, 730, 220, 740),
    ]

    p1_blocks = sc.process_page(page1_objects,  page_width=595.0, page_number=1)
    p2_blocks = sc.process_page(page2_objects, page_width=595.0, page_number=2)

    p1_blocks, p2_blocks = sc.merge_cross_page(p1_blocks, p2_blocks)

    assert p1_blocks[-1].continues_on_next_page, (
        "Le dernier bloc de la page 1 devrait avoir continues_on_next_page=True"
    )
    assert p2_blocks[0].continued_from_prev_page, (
        "Le premier bloc de la page 2 devrait avoir continued_from_prev_page=True"
    )

    # Vérifier que build_paragraphs fusionne bien les deux
    all_blocks = p1_blocks + p2_blocks
    paragraphs = sc.build_paragraphs(all_blocks)

    # Le paragraphe cross-page doit contenir les deux morceaux
    cross_page_paras = [p for p in paragraphs if p.is_cross_page]
    assert len(cross_page_paras) >= 1, (
        f"Aucun paragraphe cross-page détecté. Paragraphes : {[p.text for p in paragraphs]}"
    )

    merged_text = cross_page_paras[0].text
    assert "rates" in merged_text and "incision" in merged_text, (
        f"Texte fusionné incomplet : '{merged_text}'"
    )

    print(f"       Texte fusionné : '{merged_text}'")


# ──────────────────────────────────────────────────────────────
# Lancement
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🧪 Tests SpatialClusterer — RockTranslate\n")
    run_test("Abstract reconstruit en 1 bloc cohérent",  test_abstract_is_one_block)
    run_test("2 colonnes détectées (layout Elsevier)",   test_two_columns_detected)
    run_test("Phrase coupée cross-page détectée+fusionnée", test_cross_page_sentence)
    print()