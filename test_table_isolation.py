"""
test_table_isolation.py — Moteur Géométrique de Tableaux v2
─────────────────────────────────────────────────────────────
Améliorations v2 :
  • Discriminateur numpy : écart-type des gouttières (rejet du texte bicolonne)
  • Analyse de la longueur moyenne des cellules (prose vs valeurs atomiques)
  • Ratio chiffres/mots pondéré sur l'ensemble du bloc
  • Validation croisée multi-signaux avant toute acceptation de zone
"""

import fitz
import os
import webbrowser
import numpy as np
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Tuple

# ── Configuration ───────────────────────────────────────────
# PDF_PATH  = "2_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
PDF_PATH  = "1_PDFsam_5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
PAGE_IDX  = 0

# ── Seuils du discriminateur ────────────────────────────────
# Écart-type max (pt) des positions X des gouttières pour qu'elles soient
# considérées "stables" → colonne de tableau.
# Au-delà, c'est du texte justifié (gouttière qui bouge).
GUTTER_STD_MAX          = 8.0   # pt  — clé du discriminateur

# Longueur moyenne max (nb chars) d'une "cellule" dans un vrai tableau.
# La prose produit des cellules très longues (> 60 chars typiquement).
CELL_AVG_LEN_MAX        = 55.0  # chars

# Nombre minimum de lignes pour déclencher l'analyse de stabilité.
MIN_LINES_FOR_STABILITY = 2

# Ratio minimum de lignes avec ≥2 gouttières pour le Pilier B.
GRID_RATIO_MIN          = 0.50

# ============================================================
# STRUCTURES DE DONNÉES
# ============================================================

@dataclass
class Word:
    x0: float; y0: float; x1: float; y1: float
    text: str
    block_no: int; line_no: int; word_no: int

    @property
    def cx(self): return (self.x0 + self.x1) / 2.0
    @property
    def cy(self): return (self.y0 + self.y1) / 2.0


@dataclass
class TextLine:
    y: float
    words: List[Word]

    @property
    def min_x(self): return min(w.x0 for w in self.words)
    @property
    def max_x(self): return max(w.x1 for w in self.words)
    @property
    def text(self):  return " ".join(w.text for w in self.words)

# ============================================================
# DISCRIMINATEUR NUMPY — cœur de la v2
# ============================================================

def _extract_gutters_per_line(line: TextLine, min_gap: float = 12.0) -> List[Tuple[float, float]]:
    """Retourne les gouttières (gap_x0, gap_x1) d'une ligne."""
    gutters = []
    for i in range(1, len(line.words)):
        gap_x0 = line.words[i-1].x1
        gap_x1 = line.words[i].x0
        if gap_x1 - gap_x0 > min_gap:
            gutters.append((gap_x0, gap_x1))
    return gutters


def _gutter_stability_score(lines: List[TextLine], page_width: float, pilier: str = "A") -> dict:
    """
    Analyse numpy des gouttières sur un bloc de lignes.

    Retourne un dictionnaire de signaux :
      - std_mean   : moyenne des écarts-types des centres de gouttières
                     (faible → colonnes stables → tableau)
      - n_gutters  : nombre moyen de gouttières par ligne
      - cell_avg   : longueur moyenne des "cellules" (texte entre gouttières)
      - consistent : True si le bloc ressemble structurellement à un tableau
    """
    # Collecte des centres de gouttières par ligne
    gutter_centers_per_line = []
    cell_lengths             = []

    for line in lines:
        gutters = _extract_gutters_per_line(line)
        if gutters:
            centers = [(g[0] + g[1]) / 2.0 for g in gutters]
            gutter_centers_per_line.append(centers)

        # Longueur des "cellules" : texte entre les gouttières
        splits = [0] + [i for i, w in enumerate(line.words)
                        if i > 0 and line.words[i].x0 - line.words[i-1].x1 > 12.0] + [len(line.words)]
        for k in range(len(splits) - 1):
            chunk = line.words[splits[k]:splits[k+1]]
            cell_text = " ".join(w.text for w in chunk)
            cell_lengths.append(len(cell_text))

    if not gutter_centers_per_line:
        return {"std_mean": 999.0, "n_gutters": 0.0, "cell_avg": 0.0, "consistent": False}

    # ── Écart-type des gouttières ──────────────────────────
    # On regroupe les gouttières par index de colonne (première, deuxième…)
    max_gutters = max(len(c) for c in gutter_centers_per_line)
    std_per_col = []

    for col_idx in range(max_gutters):
        positions = [
            centers[col_idx]
            for centers in gutter_centers_per_line
            if col_idx < len(centers)
        ]
        if len(positions) >= 2:
            std_per_col.append(float(np.std(positions)))

    std_mean  = float(np.mean(std_per_col)) if std_per_col else 999.0
    n_gutters = float(np.mean([len(c) for c in gutter_centers_per_line]))
    cell_avg  = float(np.mean(cell_lengths)) if cell_lengths else 0.0
    
    page_center = page_width / 2.0
    block_x0 = min(w.x0 for l in lines for w in l.words)
    block_x1 = max(w.x1 for l in lines for w in l.words)
    block_center = (block_x0 + block_x1) / 2.0

    # Et vérifier que le bloc couvre presque toute la page
    # block_width_ratio = (block_x1 - block_x0) / page_width

    # Si le bloc est très large (>70% de la page), c'est un tableau pleine page
    # → la gouttière centrale du layout = centre de la page, pas du bloc
    # → utiliser page_center seulement si le bloc ne couvre pas toute la page
    reference_center = block_center 



    CENTER_TOLERANCE = 20


    all_gutters = []
    for line in lines:
        for i in range(1, len(line.words)):
            g0 = line.words[i-1].x1
            g1 = line.words[i].x0
            gw = g1 - g0
            if gw > 12.0:
                all_gutters.append(((g0 + g1) / 2.0, gw))  # (center_x, width)

    # Projeter tous les mots sur l'axe X
    all_x_centers = [w.cx for l in lines for w in l.words]

    layout_gutter_found = False
    left_words  = np.array([])
    right_words = np.array([])
    near_center = np.array([])
    desert_ratio = 1.0
    
    # Si reference_center est None → pas de test de gouttière centrale possible
    # → ne pas rejeter sur ce critère
    if reference_center is None:
        layout_gutter_found = False
    else:
        
        if all_x_centers:
            arr = np.array(all_x_centers)
            left_words  = arr[arr < (page_center - CENTER_TOLERANCE)]
            right_words = arr[arr > (page_center + CENTER_TOLERANCE)]
            near_center = arr[np.abs(arr - page_center) < CENTER_TOLERANCE]
            
            desert_ratio = len(near_center) / len(arr)
            # Ratio d'équilibre entre gauche et droite
            balance_ratio = min(len(left_words), len(right_words)) / max(len(left_words), len(right_words)) if max(len(left_words), len(right_words)) > 0 else 0
            print("balance_ratio:", balance_ratio, "desert_ratio:", desert_ratio, "left_count:", len(left_words), "right_count:", len(right_words))
            
            layout_gutter_found = (
                desert_ratio < 0.08
                and len(left_words)  > 3
                and len(right_words) > 3
                and balance_ratio > 0.6   # les deux côtés sont peuplés de façon similaire
            )

    # ── Décision combinée ─────────────────────────────────
    # Un vrai tableau : gouttières stables ET cellules courtes
    # Texte bicolonne : gouttière centrale instable OU cellules très longues
    is_stable_gutter     = std_mean        <= GUTTER_STD_MAX
    is_short_cells       = cell_avg        <= CELL_AVG_LEN_MAX
    
    # consistent = is_stable_gutter and is_short_cells and not layout_gutter_found

    if pilier == "B":
        consistent = not layout_gutter_found and std_mean <= GUTTER_STD_MAX
    else:  # Pilier A (Booktabs) → std non fiable sur tableaux complexes
        consistent = not layout_gutter_found

    

    return {
        "std_mean"     : std_mean,
        "n_gutters"    : n_gutters,
        "cell_avg"     : cell_avg,
        "layout_gutter": layout_gutter_found,
        "desert_ratio" : desert_ratio,
        "left_count"   : int(len(left_words)),
        "right_count"  : int(len(right_words)),
        "consistent"   : consistent
    }

# ============================================================
# DÉTECTEUR DE TABLEAUX v2
# ============================================================

class TableDetector:

    def __init__(self):
        self.x_cluster_tolerance = 12.0
        self.line_merge_tolerance = 4.0

    # ── Extraction ──────────────────────────────────────────

    def _extract_words(self, page: fitz.Page) -> List[Word]:
        rot_matrix = page.rotation_matrix
        words = []
        for w in page.get_text("words"):
            rect = fitz.Rect(w[0], w[1], w[2], w[3]) * rot_matrix
            words.append(Word(
                x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                text=w[4], block_no=w[5], line_no=w[6], word_no=w[7]
            ))
        return words

    def _build_lines(self, words: List[Word]) -> List[TextLine]:
        lines_map = defaultdict(list)
        for w in words:
            assigned = False
            for y_key in list(lines_map.keys()):
                if abs(y_key - w.cy) <= self.line_merge_tolerance:
                    lines_map[y_key].append(w)
                    assigned = True
                    break
            if not assigned:
                lines_map[w.cy].append(w)

        lines = []
        for y, lw in lines_map.items():
            lw.sort(key=lambda x: x.x0)
            if len(lw) >= 2:
                lines.append(TextLine(y=y, words=lw))
        lines.sort(key=lambda l: l.y)
        return lines

    # ── Détection multi-gouttières (Pilier B helper) ────────

    def _detect_multi_gutter_grid(self, lines: List[TextLine]) -> bool:
        if len(lines) < 3:
            return False
        for idx in range(len(lines) - 2):
            window = lines[idx:idx+3]
            line_gaps = []
            for line in window:
                gaps = []
                for i in range(1, len(line.words)):
                    g0 = line.words[i-1].x1
                    g1 = line.words[i].x0
                    if g1 - g0 > 12.0:
                        gaps.append((g0, g1))
                line_gaps.append(gaps)

            aligned = 0
            for g1_x0, g1_x1 in line_gaps[0]:
                ov2 = [g for g in line_gaps[1] if max(g1_x0, g[0]) < min(g1_x1, g[1])]
                for g2 in ov2:
                    ox0, ox1 = max(g1_x0, g2[0]), min(g1_x1, g2[1])
                    if any(max(ox0, g3[0]) < min(ox1, g3[1]) for g3 in line_gaps[2]):
                        aligned += 1
                        break
            if aligned >= 2:
                return True
        return False

    # ── Détection principale ────────────────────────────────

    def get_table_boundaries(self, page: fitz.Page, lines: List[TextLine]) -> List[Tuple]:
        drawings = page.get_drawings()
        page_w   = page.rect.width
        rot_mat  = page.rotation_matrix

        hrules = []
        for d in drawings:
            rect = d.get("rect")
            if rect:
                r = fitz.Rect(rect) * rot_mat
                w = r.x1 - r.x0
                h = r.y1 - r.y0
                if w > page_w * 0.30 and h < 4.0:
                    hrules.append(r.y0)
        hrules.sort()

        zones   = []
        used_y  = set()

        # ── Pilier A : Booktabs ─────────────────────────────
        for i in range(len(hrules) - 1):
            y_top = hrules[i]
            y_bot = hrules[i+1]

            block_lines = [l for l in lines if y_top <= l.y <= y_bot]
            if len(block_lines) < 2:
                continue

            total_words = sum(len(l.words) for l in block_lines)
            if total_words == 0:
                continue

            digit_count = sum(
                sum(1 for c in w.text if c.isdigit())
                for l in block_lines for w in l.words
            )
            digit_ratio = digit_count / total_words

            gap_counts  = []
            for l in block_lines:
                gaps = sum(
                    1 for idx in range(1, len(l.words))
                    if l.words[idx].x0 - l.words[idx-1].x1 > 12.0
                )
                gap_counts.append(gaps)

            grid_ratio = sum(1 for g in gap_counts if g >= 2) / len(gap_counts)

            if not ((digit_ratio > 0.15) or (grid_ratio >= GRID_RATIO_MIN)):
                continue
            
            print(f"   [Pilier A] y={y_top:.0f}-{y_bot:.0f} | "
            f"nb_lignes={len(block_lines)} → "
            f"{'analyse' if len(block_lines) >= MIN_LINES_FOR_STABILITY else 'SKIP discriminateur (trop court)'}")
            # ── DISCRIMINATEUR v2 ──────────────────────────
            if len(block_lines) >= MIN_LINES_FOR_STABILITY:
                scores = _gutter_stability_score(block_lines, page_w, pilier="A")
                print(f"   [Pilier A] y={y_top:.0f}-{y_bot:.0f} | "
                      f"std={scores['std_mean']:.1f} "
                      f"cell_avg={scores['cell_avg']:.1f} "
                        f"layout_gutter={scores['layout_gutter']} "
                        f"desert_ratio={scores['desert_ratio']:.3f} "   # ← ajouter
                        f"left={scores['left_count']} "                  # ← ajouter
                        f"right={scores['right_count']} "                # ← ajouter
                        f"consistent={scores['consistent']}")
                
                if not scores["consistent"]:
                    print(f"   ↳ REJETÉ (texte bicolonne détecté)")
                    continue

            x0 = min(w.x0 for l in block_lines for w in l.words) - 5
            x1 = max(w.x1 for l in block_lines for w in l.words) + 5
            # Chercher les lignes juste au-dessus de y_top (header potentiel)
            prev_hrules = [h for h in hrules if h < y_top]
            y_start = (max(prev_hrules) - 3) if prev_hrules else (y_top - 5)

            zones.append((x0, y_start, x1, y_bot + 5))
            used_y.update([y_top, y_bot])

        # ── Pilier B : borderless ───────────────────────────
        grid_lines = []
        for i, line in enumerate(lines):
            is_grid = any(
                self._detect_multi_gutter_grid(lines[max(0, i+o):i+o+3])
                for o in [-2, -1, 0]
                if 0 <= i + o < len(lines) - 2
            )
            if is_grid:
                grid_lines.append(line)

        if grid_lines:
            clusters, current = [], [grid_lines[0]]
            for l in grid_lines[1:]:
                if l.y - current[-1].y < 35.0:
                    current.append(l)
                else:
                    clusters.append(current)
                    current = [l]
            clusters.append(current)

            for cluster in clusters:
                if len(cluster) < 2:
                    continue

                gap_counts = []
                for line in cluster:
                    gaps = sum(
                        1 for idx in range(1, len(line.words))
                        if line.words[idx].x0 - line.words[idx-1].x1 > 12.0
                    )
                    gap_counts.append(gaps)

                grid_ratio = sum(1 for g in gap_counts if g >= 2) / len(gap_counts)
                if grid_ratio < GRID_RATIO_MIN:
                    continue
                
                print(f"   [Pilier B] cluster y={cluster[0].y:.0f}-{cluster[-1].y:.0f} | "
                f"nb_lignes={len(cluster)} → "
                f"{'analyse' if len(cluster) >= MIN_LINES_FOR_STABILITY else 'SKIP discriminateur (trop court)'}")

                # ── DISCRIMINATEUR v2 ──────────────────────
                if len(cluster) >= MIN_LINES_FOR_STABILITY:
                    scores = _gutter_stability_score(cluster, page_w, pilier="B")
                    print(f"   [Pilier B] cluster y={cluster[0].y:.0f}-{cluster[-1].y:.0f} | "
                          f"std={scores['std_mean']:.1f} "
                          f"cell_avg={scores['cell_avg']:.1f} "
                            f"layout_gutter={scores['layout_gutter']} "
                            f"desert_ratio={scores['desert_ratio']:.3f} "   # ← ajouter
                            f"left={scores['left_count']} "                  # ← ajouter
                            f"right={scores['right_count']} "                # ← ajouter
                            f"consistent={scores['consistent']}")
                    

                    if not scores["consistent"]:
                        print(f"   ↳ REJETÉ (texte bicolonne détecté)")
                        continue

                cy_top = min(l.y for l in cluster) - 10
                cy_bot = max(l.y for l in cluster) + 10
                if not any(max(cy_top, z[1]) < min(cy_bot, z[3]) for z in zones):
                    x0 = min(w.x0 for l in cluster for w in l.words) - 5
                    x1 = max(w.x1 for l in cluster for w in l.words) + 5
                    zones.append((x0, cy_top, x1, cy_bot))

        return zones

# ============================================================
# RECONSTRUCTEUR DE GRILLE (inchangé)
# ============================================================

def reconstruct_table_grid(zone, page_words, lines):
    x0, y0, x1, y1 = zone
    zone_words = [
    w for w in page_words 
    if x0 <= w.cx <= x1 
    and y0 <= w.cy <= y1
    and (w.y1 - w.y0) < 20.0   # exclure mots avec bbox trop haute (rotatés)
]
    zone_lines = [l for l in lines if y0 <= l.y <= y1]
    if not zone_words or not zone_lines:
        return []

    steps     = int(x1 - x0) + 2
    histogram = [0] * steps
    for w in zone_words:
        for x in range(int(max(0, w.x0 - x0)), int(min(steps - 1, w.x1 - x0)) + 1):
            histogram[x] += 1

    columns, in_col, col_start = [], False, 0
    for x in range(steps):
        if histogram[x] > 0 and not in_col:
            in_col, col_start = True, x
        elif histogram[x] == 0 and in_col:
            in_col = False
            columns.append((col_start + x0, x + x0))
    if in_col:
        columns.append((col_start + x0, steps - 1 + x0))

    merged_cols, current_col = [], columns[0] if columns else None
    for next_col in (columns[1:] if columns else []):
        if next_col[0] - current_col[1] < 6.0:
            current_col = (current_col[0], max(current_col[1], next_col[1]))
        else:
            merged_cols.append(current_col)
            current_col = next_col
    if current_col:
        merged_cols.append(current_col)

    

    grid = []
    for line in zone_lines:
        row = [""] * len(merged_cols)
        for w in line.words:
            best_idx, best_ov = 0, -1.0
            for ci, (cx0, cx1) in enumerate(merged_cols):
                ov = min(w.x1, cx1) - max(w.x0, cx0)
                if ov > best_ov:
                    best_ov, best_idx = ov, ci
            if best_ov > 0:
                row[best_idx] += w.text + " "
        grid.append([c.strip() for c in row])
    return grid

# ============================================================
# EXÉCUTION
# ============================================================

def execute_test():
    print(f"📖 Analyse : {PDF_PATH}  (Page {PAGE_IDX + 1})\n")
    doc  = fitz.open(PDF_PATH)
    page = doc[PAGE_IDX]

    detector = TableDetector()
    words    = detector._extract_words(page)
    lines    = detector._build_lines(words)

    print("── Analyse des blocs ──────────────────────────────────")
    table_zones = detector.get_table_boundaries(page, lines)
    print(f"\n✅ Résultat final : {len(table_zones)} tableau(x) retenu(s).")
    for i, z in enumerate(table_zones):
        print(f"   [T{i+1}] x0={z[0]:.1f} y0={z[1]:.1f} x1={z[2]:.1f} y1={z[3]:.1f}")

    grids_data = []
    for i, zone in enumerate(table_zones):
        grid = reconstruct_table_grid(zone, words, lines)
        grids_data.append(grid)
        print(f"\n{'='*65}")
        print(f"📊 TABLEAU N°{i+1}")
        print(f"{'='*65}")
        if grid:
            cw = [max(len(r[c]) for r in grid) for c in range(len(grid[0]))]
            for row in grid:
                print("  | " + " | ".join(cell.ljust(cw[ci]) for ci, cell in enumerate(row)) + " |")
        print(f"{'='*65}")

    # ── HTML ────────────────────────────────────────────────
    tables_html = ""
    for i, grid in enumerate(grids_data):
        if not grid:
            continue
        header = "".join(f"<th>{c}</th>" for c in grid[0])
        rows   = "".join(
            "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
            for row in grid[1:]
        )
        tables_html += f"""
        <div class="table-card">
            <h3>Tableau {i+1}</h3>
            <table><thead><tr>{header}</tr></thead><tbody>{rows}</tbody></table>
        </div>"""

    html = f"""<!DOCTYPE html>
<html><head>
<meta charset="UTF-8">
<title>Extracteur de Tableaux v2</title>
<style>
  body {{font-family:'Segoe UI',sans-serif;background:#f1f5f9;color:#1e293b;padding:40px;display:flex;flex-direction:column;align-items:center;}}
  .container {{width:100%;max-width:1000px;}}
  h2 {{color:#0f172a;border-bottom:2px solid #cbd5e1;padding-bottom:8px;margin-bottom:24px;}}
  .table-card {{background:white;padding:24px;border-radius:12px;box-shadow:0 4px 6px -1px rgba(0,0,0,.1);margin-bottom:40px;}}
  h3 {{color:#2563eb;margin-bottom:16px;}}
  table {{width:100%;border-collapse:collapse;font-size:13px;}}
  th,td {{border:1px solid #e2e8f0;padding:10px 14px;text-align:left;}}
  th {{background:#f8fafc;font-weight:600;color:#475569;}}
  tr:hover {{background:#f8fafc;}}
</style></head>
<body><div class="container">
  <h2>📊 Extracteur de Tableaux v2 — numpy discriminator</h2>
  {tables_html}
</div></body></html>"""

    out = "test_table_isolation.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n🎉 HTML généré : '{out}'")
    doc.close()
    webbrowser.open(out)


if __name__ == "__main__":
    execute_test()