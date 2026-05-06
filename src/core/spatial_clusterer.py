"""
spatial_clusterer.py — Cerveau de RockTranslate
Chemin : D:/Projets/RockTranslate/src/core/spatial_clusterer.py

Pipeline :
    RawObjects
        ↓ merge_accents_and_superscripts()   ← fusionne accents/exposants
        ↓ detect_page_zones()                ← découpe la page en zones 1col/2col
        ↓ Pour chaque zone :
            cluster_spans()
            build_lines()
            build_blocks()
        ↓ sort_reading_order()
        ↓ [entre pages] merge_cross_page()
        ↓ build_paragraphs()
        → List[Paragraph] prêts pour le LLM
"""

from core.domain import RawObject, Span, Line, Block, Paragraph


# ─────────────────────────────────────────────────────────────
# Constantes internes (non exposées, dérivées du contenu)
# ─────────────────────────────────────────────────────────────
_MIN_GUTTER_WIDTH  = 15.0   # px minimum pour qu'un vide soit une gouttière
_ZONE_BAND_HEIGHT  = 40.0   # hauteur d'une bande d'analyse (pt)
_GUTTER_SEARCH_PCT = 0.35   # on cherche dans les N% centraux du texte réel


class SpatialClusterer:
    """
    Regroupe les fragments texte atomiques PDFium en unités linguistiques.

    Paramètres :
        span_x_gap_factor  : écart X max entre deux fragments du même span
        block_gap_factor   : gap vertical > N * line_height → nouveau bloc
    """

    def __init__(
        self,
        span_x_gap_factor: float = 1.2,
        block_gap_factor: float  = 2.0,
    ):
        self.span_x_gap_factor = span_x_gap_factor
        self.block_gap_factor  = block_gap_factor

    # ══════════════════════════════════════════════════════════
    # PRÉ-TRAITEMENT : accents & exposants
    # ══════════════════════════════════════════════════════════

    def merge_accents_and_superscripts(
        self, raw_objects: list[RawObject]
    ) -> list[RawObject]:
        """
        Fusionne les accents (´ ` ^ ¨) et exposants (a, b, *)
        avec l'objet le plus proche horizontalement.

        Exemple avant : ['S', 'e', '´', 'b', 'a', 's', 't', 'i', 'e', 'n']
        Exemple après  : ['Sé', 'b', 'a', 's', 't', 'i', 'e', 'n']

        Critères de fusion :
          - chevauchement horizontal (l'accent est "dans" la lettre)
            OU proximité immédiate (gap X < 2pt)
          - chevauchement vertical partiel (tolérance 5pt pour exposants)
        """
        if not raw_objects:
            return []

        sorted_objs = sorted(raw_objects, key=lambda o: o.left)
        merged: list[RawObject] = []

        for curr in sorted_objs:
            if not merged:
                merged.append(curr)
                continue

            prev = merged[-1]

            h_overlap = min(curr.right, prev.right) - max(curr.left, prev.left)
            is_near_x = (curr.left - prev.right) < 2.0
            v_overlap  = min(curr.top, prev.top) - max(curr.bottom, prev.bottom)
            is_same_row = v_overlap > -8.0  # tolérance exposants/indices

            if (h_overlap > -2.0 or is_near_x) and is_same_row:
                # Fusion : on étend la bbox de prev et on concatène le texte
                prev.text  += curr.text
                prev.right  = max(prev.right,  curr.right)
                prev.top    = max(prev.top,    curr.top)
                prev.bottom = min(prev.bottom, curr.bottom)
            else:
                merged.append(curr)

        return merged

    # ══════════════════════════════════════════════════════════
    # ÉTAPE 1 : RawObjects → Spans
    # ══════════════════════════════════════════════════════════

    def cluster_spans(self, raw_objects: list[RawObject]) -> list[Span]:
        """
        Regroupe les fragments atomiques en spans (mots/groupes de mots).
        Utilise le chevauchement vertical plutôt que des seuils fixes —
        robuste face aux polices Elsevier à taille 1pt + matrice.

        Critères de regroupement :
          - chevauchement vertical : les deux bbox partagent au moins
            une fraction de leur hauteur (same_line)
          - gap horizontal raisonnable : < span_x_gap_factor * hauteur_ref
        """
        if not raw_objects:
            return []

        sorted_objs = sorted(
            raw_objects, key=lambda o: (round(o.bottom, 1), o.left)
        )

        spans: list[Span] = []
        current_group: list[RawObject] = [sorted_objs[0]]

        for obj in sorted_objs[1:]:
            prev    = current_group[-1]
            ref_h   = max(obj.height, prev.height, 8.0)

            # Overlap vertical (positif = chevauchement, négatif = séparation)
            v_overlap = min(obj.top, prev.top) - max(obj.bottom, prev.bottom)
            same_line = v_overlap > -2.0

            # Gap horizontal acceptable
            close_x = (obj.left - prev.right) < (ref_h * self.span_x_gap_factor)

            if same_line and close_x:
                current_group.append(obj)
            else:
                spans.append(Span.from_raw_objects(current_group))
                current_group = [obj]

        spans.append(Span.from_raw_objects(current_group))
        return spans

    # ══════════════════════════════════════════════════════════
    # ÉTAPE 2 : Spans → Lines
    # ══════════════════════════════════════════════════════════

    def build_lines(self, spans: list[Span]) -> list[Line]:
        """
        Regroupe les spans sur la même bande verticale en lignes.
        Utilise le chevauchement vertical (25% min) pour être robuste
        aux exposants et indices qui décalent le y_center.

        NB : on ne fusionne PAS des spans de colonnes différentes —
        un grand gap horizontal (> 2 * hauteur) coupe la ligne.
        """
        if not spans:
            return []

        sorted_spans = sorted(spans, key=lambda s: (-s.y_center, s.left))
        lines: list[Line] = []
        current_line: list[Span] = [sorted_spans[0]]

        for span in sorted_spans[1:]:
            prev = current_line[-1]

            # Overlap vertical : partagent-ils la même bande Y ?
            overlap  = min(span.top, prev.top) - max(span.bottom, prev.bottom)
            min_h    = min(span.height, prev.height) or 1.0
            same_row = overlap > (min_h * 0.25)

            # Gap horizontal : colonnes différentes ?
            ref_h        = max(span.height, prev.height, 8.0)
            x_gap        = span.left - prev.right
            diff_column  = x_gap > (ref_h * 2.5)

            if same_row and not diff_column:
                current_line.append(span)
            else:
                lines.append(Line.from_spans(current_line))
                current_line = [span]

        lines.append(Line.from_spans(current_line))
        return lines

    # ══════════════════════════════════════════════════════════
    # ÉTAPE 3 : Lines → Blocks
    # ══════════════════════════════════════════════════════════

    def build_blocks(
        self, lines: list[Line], page_number: int = 0
    ) -> list[Block]:
        """
        Regroupe les lignes consécutives en blocs (paragraphes visuels).
        Nouveau bloc si :
          - gap vertical > block_gap_factor * hauteur_ligne
          - OU pas de chevauchement horizontal (colonnes différentes)
        """
        if not lines:
            return []

        sorted_lines = sorted(lines, key=lambda l: -l.top)
        blocks: list[Block] = []
        current_group: list[Line] = [sorted_lines[0]]

        for line in sorted_lines[1:]:
            prev      = current_group[-1]
            v_gap     = prev.bottom - line.top
            h_overlap = (
                min(prev.right, line.right) - max(prev.left, line.left)
            )

            # Seuil de gap vertical basé sur la hauteur de la ligne courante
            gap_threshold = line.height * self.block_gap_factor

            # Nouveau bloc si :
            #   - gap vertical trop grand
            #   - OU pas de chevauchement horizontal du tout (colonnes séparées)
            #     → seuil strict à 0 (pas de tolérance négative)
            new_block = v_gap > gap_threshold or h_overlap < 0

            if new_block:
                blocks.append(Block.from_lines(current_group, page_number))
                current_group = [line]
            else:
                current_group.append(line)

        blocks.append(Block.from_lines(current_group, page_number))

        # Post-processing : recolle les blocs trop fragmentés
        return self._merge_touching_blocks(blocks, page_number)

    def _merge_touching_blocks(
        self, blocks: list[Block], page_number: int
    ) -> list[Block]:
        """
        Fusionne les blocs visuellement contigus fragmentés à tort.
        
        Règles strictes pour éviter les fusions inter-colonnes :
          - Même colonne obligatoire (b1.column == b2.column)
          - Gap vertical < 8pt
          - Chevauchement horizontal réel (> 10pt) — pas juste "proche"
          - Largeurs compatibles (ratio > 0.5) — évite de fusionner
            un titre centré avec un paragraphe
        """
        if len(blocks) < 2:
            return blocks

        changed = True
        while changed:
            changed = False
            result: list[Block] = []
            skip: set[int] = set()

            for i, b1 in enumerate(blocks):
                if i in skip:
                    continue

                merged_block = b1
                for j in range(i + 1, len(blocks)):
                    if j in skip:
                        continue
                    b2 = blocks[j]

                    # ── Règle 1 : même colonne obligatoire ──────────
                    if merged_block.column != b2.column:
                        continue

                    # ── Règle 2 : gap vertical faible ───────────────
                    v_dist = max(
                        merged_block.bottom - b2.top,
                        b2.bottom - merged_block.top,
                        0.0
                    )
                    if v_dist >= 8:
                        continue

                    # ── Règle 3 : chevauchement horizontal réel ─────
                    h_overlap = (
                        min(merged_block.right, b2.right)
                        - max(merged_block.left, b2.left)
                    )
                    if h_overlap <= 10:
                        continue

                    # ── Règle 4 : largeurs compatibles ──────────────
                    w1 = merged_block.right - merged_block.left
                    w2 = b2.right - b2.left
                    if w1 > 0 and w2 > 0:
                        ratio = min(w1, w2) / max(w1, w2)
                        if ratio < 0.5:
                            continue

                    # Fusion validée
                    combined = sorted(
                        merged_block.lines + b2.lines,
                        key=lambda l: -l.top,
                    )
                    merged_block = Block.from_lines(combined, page_number)
                    merged_block.column = b1.column
                    skip.add(j)
                    changed = True

                result.append(merged_block)
            blocks = result

        return blocks

    # ══════════════════════════════════════════════════════════
    # DÉTECTION DE ZONES — CŒUR DU FIX
    # ══════════════════════════════════════════════════════════

    def _find_gutter(
        self,
        objects: list[RawObject],
        page_width: float,
    ) -> float:
        """
        Cherche la gouttière (vide vertical) dans une liste d'objets.
        Les marges de recherche sont dérivées du contenu réel,
        pas de constantes dures.

        Retourne l'abscisse X du centre de la gouttière,
        ou 0.0 si aucune gouttière trouvée.
        """
        if not objects:
            return 0.0

        # Marges réelles du texte (pas de la page)
        text_left  = min(o.left  for o in objects)
        text_right = max(o.right for o in objects)
        text_width = text_right - text_left

        if text_width < 100:
            return 0.0

        # Zone de recherche : N% centraux du texte réel
        search_start = text_left  + text_width * _GUTTER_SEARCH_PCT
        search_end   = text_right - text_width * _GUTTER_SEARCH_PCT

        if search_end <= search_start:
            return 0.0

        # Histogramme d'occupation X (résolution 1pt)
        steps      = int(page_width) + 1
        occupancy  = [0] * steps

        for obj in objects:
            x0 = int(max(0, obj.left))
            x1 = int(min(steps - 1, obj.right))
            for x in range(x0, x1 + 1):
                occupancy[x] += 1

        # Fenêtre glissante adaptative (2% de la largeur texte)
        window = max(10, int(text_width * 0.02))

        best_sum = float("inf")
        best_x   = 0.0

        xi = int(search_start)
        xe = int(search_end) - window
        for i in range(xi, xe):
            s = sum(occupancy[i : i + window])
            if s < best_sum:
                best_sum = s
                best_x   = i + window / 2.0

        # Valide : le vide doit être significativement moins dense
        # que la moyenne générale
        avg_density = sum(occupancy) / max(steps, 1)
        gutter_density = best_sum / window

        if avg_density > 0 and gutter_density / avg_density < 0.3:
            return best_x
        if gutter_density < 1.0:   # zone vraiment vide
            return best_x

        return 0.0

    def detect_page_zones(
        self,
        raw_objects: list[RawObject],
        page_width: float,
        page_height: float,
        forced_gutter: float = 0.0,
    ) -> list[dict]:
        """
        Découpe la page en zones horizontales, chacune avec son layout.

        Algorithme :
          1. Découpe en bandes Y de _ZONE_BAND_HEIGHT pts
          2. Pour chaque bande : cherche une gouttière
          3. Fusionne les bandes consécutives de même layout
          4. Retourne la liste de zones

        Retourne une liste de dicts :
            [
              {"y_top": 841, "y_bot": 500, "layout": "1col", "objects": [...]},
              {"y_top": 500, "y_bot":   0, "layout": "2col",
               "gutter_x": 297.5,         "objects": [...]},
            ]
        """
        if not raw_objects:
            return []

        y_max = max(o.top    for o in raw_objects)
        y_min = min(o.bottom for o in raw_objects)

        # ── Bandes Y ──────────────────────────────────────────────
        bands: list[dict] = []
        y = y_max

        while y > y_min:
            y_bot = max(y - _ZONE_BAND_HEIGHT, y_min)
            band_objs = [
                o for o in raw_objects
                if o.bottom < y and o.top > y_bot
            ]

            if band_objs:
                if forced_gutter > 0:
                    left  = [o for o in band_objs if o.x_center <= forced_gutter]
                    right = [o for o in band_objs if o.x_center >  forced_gutter]
                    
                    # Vérifie qu'il y a vraiment un vide entre les deux groupes
                    # Un objet pleine largeur (traverse la gouttière) → 1col
                    full_width = [
                        o for o in band_objs
                        if o.left < (forced_gutter - 30) and o.right > (forced_gutter + 30)
                    ]
                    
                    if left and right and not full_width:
                        gutter_x = forced_gutter
                        layout   = "2col"
                    else:
                        gutter_x = 0.0
                        layout   = "1col"
                bands.append({
                    "y_top":    y,
                    "y_bot":    y_bot,
                    "layout":   layout,
                    "gutter_x": gutter_x,
                    "objects":  band_objs,
                })

            y = y_bot

        if not bands:
            return []

        # ── Fusion des bandes consécutives de même layout ─────────
        zones: list[dict] = []
        current = bands[0].copy()
        current["objects"] = list(bands[0]["objects"])

        for band in bands[1:]:
            same_layout = band["layout"] == current["layout"]

            # Pour 2col, on vérifie aussi que la gouttière est au même endroit
            # (tolérance 20pt) — évite de fusionner des double-cols décalées
            if same_layout and current["layout"] == "2col":
                same_layout = (
                    abs(band["gutter_x"] - current["gutter_x"]) < 20
                )

            if same_layout:
                current["y_bot"]   = band["y_bot"]
                current["objects"] += band["objects"]
                # Met à jour la gouttière (moyenne des bandes fusionnées)
                if current["layout"] == "2col":
                    current["gutter_x"] = (
                        current["gutter_x"] + band["gutter_x"]
                    ) / 2
            else:
                zones.append(current)
                current = band.copy()
                current["objects"] = list(band["objects"])

        zones.append(current)
        return zones

    # ══════════════════════════════════════════════════════════
    # PIPELINE COMPLET : RawObjects → Blocks ordonnés
    # ══════════════════════════════════════════════════════════

    def find_document_gutter(
        self,
        all_pages_objects: list[list[RawObject]],
        page_width: float,
    ) -> float:
        """
        Trouve la gouttière globale du document par vote sur toutes les pages.
        Retourne la médiane des gouttières valides (entre 30% et 70% de page_width).
        Cette valeur stable est ensuite imposée à toutes les pages via forced_gutter.
        """
        gutters = []
        for page_objs in all_pages_objects:
            g = self._find_gutter(page_objs, page_width)
            if page_width * 0.30 < g < page_width * 0.70:
                gutters.append(g)

        if not gutters:
            return 0.0

        gutters.sort()
        return gutters[len(gutters) // 2]

    def process_page(
        self,
        raw_objects: list[RawObject],
        page_width: float,
        page_number: int = 0,
        page_height: float = 841.9,
        forced_gutter: float = 0.0,
    ) -> list[Block]:
        """
        Pipeline complet pour une page.

        1. Fusionne accents et exposants
        2. Détecte les zones (1col / 2col) par bandes Y
           Si forced_gutter > 0, utilise cette gouttière globale
           au lieu de la chercher bande par bande.
        3. Pour chaque zone, traite ses objets indépendamment
        4. Retourne tous les blocs dans l'ordre de lecture
        """
        if not raw_objects:
            return []

        # ── Pré-traitement ────────────────────────────────────────
        objects = self.merge_accents_and_superscripts(raw_objects)

        # ── Détection des zones ───────────────────────────────────
        zones = self.detect_page_zones(
            objects, page_width, page_height, forced_gutter
        )

        final_blocks: list[Block] = []

        for zone in zones:
            zone_objs   = zone["objects"]
            layout      = zone["layout"]
            gutter_x    = zone.get("gutter_x", 0.0)

            if layout == "1col":
                # ── Zone pleine largeur ───────────────────────────
                spans  = self.cluster_spans(zone_objs)
                lines  = self.build_lines(spans)
                blocks = self.build_blocks(lines, page_number)
                for b in blocks:
                    b.column = 0
                # Tri haut → bas
                blocks.sort(key=lambda b: -b.top)
                final_blocks.extend(blocks)

            else:
                # ── Zone double colonne ───────────────────────────
                left_objs  = [o for o in zone_objs if o.x_center <= gutter_x]
                right_objs = [o for o in zone_objs if o.x_center >  gutter_x]

                # Colonne gauche
                if left_objs:
                    spans  = self.cluster_spans(left_objs)
                    lines  = self.build_lines(spans)
                    blocks = self.build_blocks(lines, page_number)
                    for b in blocks:
                        b.column = 1
                    blocks.sort(key=lambda b: -b.top)
                    final_blocks.extend(blocks)

                # Colonne droite
                if right_objs:
                    spans  = self.cluster_spans(right_objs)
                    lines  = self.build_lines(spans)
                    blocks = self.build_blocks(lines, page_number)
                    for b in blocks:
                        b.column = 2
                    blocks.sort(key=lambda b: -b.top)
                    final_blocks.extend(blocks)

        return final_blocks

    # ══════════════════════════════════════════════════════════
    # CROSS-PAGE
    # ══════════════════════════════════════════════════════════

    def merge_cross_page(
        self,
        page_blocks: list[Block],
        next_page_blocks: list[Block],
    ) -> tuple[list[Block], list[Block]]:
        """
        Détecte et marque les phrases coupées entre deux pages.

        Heuristiques (ordre de priorité) :
          1. Tiret de coupure : dernier mot se termine par '-'
          2. Phrase non terminée : pas de '.?!:' en fin de bloc
          3. Suite commence par une minuscule
        """
        if not page_blocks or not next_page_blocks:
            return page_blocks, next_page_blocks

        last_block  = page_blocks[-1]
        first_block = next_page_blocks[0]
        last_text   = last_block.last_line_text.strip()
        first_text  = first_block.first_line_text.strip()

        is_cross = False

        if last_text.endswith("-"):
            is_cross = True
        elif last_text and last_text[-1] not in ".?!:":
            is_cross = True
        elif first_text and first_text[0].islower():
            is_cross = True

        if is_cross:
            last_block.continues_on_next_page  = True
            first_block.continued_from_prev_page = True

        return page_blocks, next_page_blocks

    # ══════════════════════════════════════════════════════════
    # PARAGRAPHES FINAUX → LLM
    # ══════════════════════════════════════════════════════════

    def build_paragraphs(self, blocks: list[Block]) -> list[Paragraph]:
        """
        Fusionne les blocs cross-page et crée les Paragraphs finaux.
        C'est ce que reçoit le LLM pour traduction.
        """
        paragraphs: list[Paragraph] = []
        pending: list[Block] = []

        for block in blocks:
            pending.append(block)
            if block.continues_on_next_page:
                continue
            paragraphs.append(Paragraph.from_blocks(pending))
            pending = []

        if pending:
            paragraphs.append(Paragraph.from_blocks(pending))

        return paragraphs