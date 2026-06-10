# core/html_transformer.py

import os, re
import subprocess
from typing import Callable
from bs4 import BeautifulSoup, NavigableString

# Importation découplée de notre nouvel utilitaire de téléchargement
from utils.downloader import check_and_download_pdf2htmlex, DEFAULT_ASSETS_DIR

ACCENTS_TO_IGNORE = {'´', '`', '¨', 'ˆ', '˜', '¸', 'ˇ', '¯', '˘', '˙', '˚', '˝', '˛', '⇑', '⇓'}


def convert_pdf_to_html(
    pdf_path: str, 
    assets_dir: str = DEFAULT_ASSETS_DIR, 
    on_progress: Callable[[int, int], None] = None
) -> str | None:
    """
    Convertit un fichier PDF en HTML brut en utilisant l'exécutable local pdf2htmlEX
    en lisant en direct la progression des pages.
    """
    pdf2htmlex_exe = check_and_download_pdf2htmlex(assets_dir)
    if not pdf2htmlex_exe:
        return None

    pdf_dir = os.path.dirname(os.path.abspath(pdf_path))
    pdf_filename = os.path.basename(pdf_path)
    html_filename = f"{os.path.splitext(pdf_filename)[0]}_raw.html"
    output_html_path = os.path.join(pdf_dir, html_filename)

    if os.path.exists(output_html_path):
        return output_html_path # Évite de re-compiler si déjà présent

    cmd = [
        os.path.abspath(pdf2htmlex_exe),
        "--zoom", "1.3",
        pdf_filename,
        html_filename
    ]
    
    print(f"⚙️ Conversion haute fidélité du PDF en cours ({pdf_filename})...")
    # On utilise Popen pour pouvoir lire la sortie de progression en temps réel
    process = subprocess.Popen(
        cmd, cwd=pdf_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )

    # Lecture en direct du flux stderr de pdf2htmlEX
    while True:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break
        
        # pdf2htmlEX écrit sa progression sous la forme : "Working: 1/12"
        if "Working:" in line:
            match = re.search(r"Working:\s*(\d+)/(\d+)", line)
            if match and on_progress:
                current_page = int(match.group(1))
                total_pages = int(match.group(2))
                on_progress(current_page, total_pages)

    process.wait()
    if process.returncode == 0 and os.path.exists(output_html_path):
        print("✅ Fichier HTML brut généré.")
        return output_html_path
    return None

    
# DEPRACATED
def wrap_text_nodes_recursively(soup, parent_element, trans_idx_ref, original_texts_map) -> None: # DEPRACATED
    """
    Parcourt récursivement les nœuds enfants d'un élément pour envelopper tous les textes bruts,
    tout en préservant les spacers d'origine sans les altérer.
    """
    children = list(parent_element.contents)
    parent_element.clear()

    for child in children:
        if isinstance(child, NavigableString):
            # C'est du texte brut : on l'enveloppe pour la traduction
            text_val = str(child)
            if text_val.strip():
                text_id = f"t-{trans_idx_ref[0]}"
                original_texts_map[text_id] = text_val
                
                new_span = soup.new_tag("span", attrs={
                    "class": "trans-span",
                    "data-trans-id": text_id,
                    "data-orig-text": text_val
                })
                new_span.string = text_val
                parent_element.append(new_span)
                trans_idx_ref[0] += 1
            else:
                parent_element.append(child)
                
        elif child.name == "span" and child.get("class") and any(c.startswith("_") for c in child.get("class")):
            # C'est une balise d'espacement (spacer) de pdf2htmlEX : on la conserve strictement intacte
            parent_element.append(child)
            
        elif child.name in ["span", "a", "b", "i", "sup", "sub", "em", "strong"]:
            # C'est un conteneur stylisé ou un lien : on descend récursivement à l'intérieur
            wrap_text_nodes_recursively(soup, child, trans_idx_ref, original_texts_map)
            parent_element.append(child)
            
        else:
            # Sécurité pour tout autre type d'élément HTML
            parent_element.append(child)

# DEPRACATED
def _wrap_children_recursively(soup, element, idx, original_texts_map, tid_to_page, page_idx, sx_orig, sy_orig):# DEPRACATED
    """
    Descend récursivement dans les éléments imbriqués d'une div.t
    pour wrapper tous les TextNodes, sans row-wrapper ni style complexe.
    Préserve intacts les spacers pdf2htmlEX (class="_").
    """
    for child in list(element.children):
        if isinstance(child, NavigableString) and child.strip():
            tid = f"t-{idx[0]}"
            original_texts_map[tid] = str(child)
            tid_to_page[tid] = page_idx

            span = soup.new_tag("span", attrs={
                "data-trans-id": tid,
                "data-sx": str(sx_orig),
                "data-sy": str(sy_orig),
                "style": "display:inline;"
            })
            span.string = str(child)
            child.replace_with(span)
            idx[0] += 1

        elif hasattr(child, "get"):
            classes = child.get("class", [])
            # Spacer pdf2htmlEX → ne pas toucher
            if "_" in classes:
                continue
            elif child.name in ["span", "a", "b", "i", "sup", "sub", "em", "strong"]:
                _wrap_children_recursively(soup, child, idx, original_texts_map, tid_to_page, page_idx, sx_orig, sy_orig)



def parse_matrix_classes(soup) -> dict:
    matrix_map = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        for m in re.finditer(
            r'\.(m\w+)\{transform:matrix\(([\d.]+),[\d.]+,[\d.]+,([\d.]+),', text
        ):
            cls = m.group(1)
            sx  = float(m.group(2))
            sy  = float(m.group(3))
            matrix_map[cls] = (sx, sy)
    return matrix_map


def parse_spacer_widths(soup) -> dict:
    """
    Analyse les classes d'espacement de pdf2htmlEX pour extraire la largeur
    physique en pixels de chaque spacer (ex: ._19 { width: 85.123px; } -> {"19": 85.123})
    """
    spacer_map = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        for m in re.finditer(r'\._(\w+)\s*\{\s*width\s*:\s*([\d\.]+)\s*px\s*;?\s*\}', text):
            cls = m.group(1)
            width = float(m.group(2))
            spacer_map[cls] = width
    return spacer_map



def instrument_html(raw_html_path: str, output_html_path: str) -> tuple[dict, dict]:
    """
    Analyse le fichier HTML brut, applique l'algorithme de regroupement hybride
    basé sur l'espacement pour regrouper les phrases et isoler les colonnes de tableaux,
    puis injecte les styles de transition et l'écouteur de messages.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    matrix_map = parse_matrix_classes(soup)
    spacer_map = parse_spacer_widths(soup)
    pages_list = soup.find_all("div", class_="pf")

    original_texts_map = {}
    tid_to_page = {}
    idx = [0]
    
    # Seuil de coupure (20 pixels) : au-dessus, c'est un tableau ou un grand saut structurel
    THRESHOLD_PX = 20.0

    for page_idx, page_el in enumerate(pages_list):
        for div_t in page_el.find_all("div", class_="t"):
            # Déterminer les coefficients d'échelle d'origine (sx, sy) de la ligne
            classes = div_t.get("class", [])
            sx_orig, sy_orig = 1.0, 1.0
            for cls in classes:
                if cls in matrix_map:
                    sx_orig, sy_orig = matrix_map[cls]
                    break

            children = list(div_t.contents)
            div_t.clear()

            current_group_text = []
            current_group_elements = []

            def commit_group():
                nonlocal current_group_text, current_group_elements
                if not current_group_elements:
                    return

                # Fusionner le texte brut contenu dans ce groupe
                merged_text = "".join(current_group_text).strip()
                # print(f"🔍 Extraction de Groupe : {current_group_text} ➡️ Fusionné en : '{merged_text}'")
                if merged_text:
                    gid = f"g-{idx[0]}"
                    original_texts_map[gid] = merged_text
                    tid_to_page[gid] = page_idx

                    # ── DÉTECTION DES COULEURS ET DES LIENS D'ORIGINE ──
                    inherited_classes = ["trans-span"]
                    for el in current_group_elements:
                        if hasattr(el, "get"):
                            el_classes = el.get("class", [])
                            # On copie les classes de couleurs (fc1, fc2 etc.) et de polices
                            for cls in el_classes:
                                if cls.startswith("fc") or cls.startswith("sc"):
                                    inherited_classes.append(cls)

                    # Création du conteneur de groupe sémantique avec héritage de style
                    group_span = soup.new_tag("span", attrs={
                        "class": " ".join(inherited_classes),
                        "data-trans-id": gid,
                        "data-sx": str(sx_orig),
                        "data-sy": str(sy_orig),
                        "style": "display:inline;"
                    })
                    for el in current_group_elements:
                        group_span.append(el)
                    div_t.append(group_span)
                    idx[0] += 1
                else:
                    # En cas d'espaces vides ou nœuds sans texte, on les restitue tels quels
                    for el in current_group_elements:
                        div_t.append(el)

                current_group_text.clear()
                current_group_elements.clear()

            # Analyse et répartition géométrique de chaque nœud enfant
            for child in children:
                # Récupérer le texte nettoyé du nœud pour vérification
                child_text = child.get_text().strip() if hasattr(child, "get_text") else str(child).strip()
                
                # Si c'est un accent flottant parasite du PDF, on l'élimine pour éviter de couper notre groupe
                if child_text in ACCENTS_TO_IGNORE:
                    continue

                is_spacer = False
                width = 0.0

                if child.name == "span" and child.get("class"):
                    child_classes = child.get("class")
                    if "_" in child_classes:
                        is_spacer = True
                        for cls in child_classes:
                            if cls.startswith("_") and len(cls) > 1:
                                width = spacer_map.get(cls[1:], 0.0)
                                break

                if is_spacer:
                    if width >= THRESHOLD_PX:
                        # Grand espace (Tableau ou Colonne) -> On valide le groupe actuel et on coupe
                        commit_group()
                        div_t.append(child)  # On conserve le spacer de structure intact dans la div
                    else:
                        # Petit espace (Espace entre deux mots) -> On l'accumule dans le groupe
                        current_group_elements.append(child)
                        current_group_text.append(" ")
                else:
                    # Texte brut ou balise de style inline classique (b, i, span etc)
                    if isinstance(child, str):
                        current_group_text.append(str(child))
                        current_group_elements.append(child)
                    else:
                        current_group_text.append(child.get_text())
                        current_group_elements.append(child)

            # Ne pas oublier de valider le groupe résiduel de la ligne
            commit_group()


                    
    # 2. INJECTION DE VOTRE GLASS DE POLI SUR TOUTES LES PAGES DU DOCUMENT (div.pf)
    for p_idx, page in enumerate(pages_list):
        # Création du conteneur dépoli à haute spécificité graphique
        glass_div = soup.new_tag("div", attrs={
            "id": f"glass-overlay-t-{p_idx}",
            "style": (
                "position: absolute; "
                "top: 5%; "
                "left: 5%; "
                "width: 90%; "
                "height: 90%; "
                "background: linear-gradient(135deg, rgba(255,255,255,0.45), rgba(255,255,255,0.15)); "
                "backdrop-filter: blur(18px); "
                "-webkit-backdrop-filter: blur(18px); "
                "border: 1px solid rgba(255,255,255,0.5); "
                "border-radius: 16px; "
                "box-shadow: 0 8px 32px rgba(31,38,135,0.25), 0 0 1px rgba(255,255,255,0.5); "
                "z-index: 1000; " # Se dessine par-dessus les éléments pdf2htmlEX
                "display: flex; "
                "justify-content: center; "
                "align-items: center; "
                "pointer-events: none;"
            )
        })

        # Encadré interne blanc opaque
        inner_div = soup.new_tag("div", attrs={
            "style": (
                "background: rgba(255,255,255,0.92); "
                "padding: 24px 40px; "
                "border-radius: 12px; "
                "text-align: center; "
                "box-shadow: 0 10px 30px rgba(0,0,0,0.15); "
                "display: flex; "
                "flex-direction: column; "
                "align-items: center;"
            )
        })

        # Injecter le chargeur circulaire
        loader_div = soup.new_tag("div", attrs={"class": "circular-loader"})
        inner_div.append(loader_div)

        # Injecter le texte informatif
        text_p = soup.new_tag("p", attrs={
            "style": "color:#1e293b; font-size:14px; font-weight:600; margin:0; font-family: sans-serif;"
        })
        text_p.string = "En attente de traduction..."
        inner_div.append(text_p)

        glass_div.append(inner_div)
        page.append(glass_div)

    # 3. Injection de vos styles CSS (Squelettes shimmer & styles de lignes & spin circulaire)
    style_tag = soup.new_tag("style")
    style_tag = soup.new_tag("style")
    style_tag.string = """
        #sidebar { display: none !important; }
        #page-container { left: 0 !important; margin: 0 auto !important; }

        /* Force l'espacement des mots traduits pour contourner les polices PDF à 0-width space */
        span[data-trans-id] {
            word-spacing: 0.25em !important;
        }

        @keyframes loading-shimmer {
            0%   { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        /* CIBLAGE ULTRA-PRÉCIS : Le Shimmer est appliqué aux spans individuels, pas aux lignes */
        .shimmer-line {
            display: inline-block !important; /* Force l'affichage pour porter le dégradé de chargement */
            background: linear-gradient(90deg, #f1f5f9 25%, #cbd5e1 50%, #f1f5f9 75%) !important;
            background-size: 200% 100% !important;
            animation: loading-shimmer 1.8s infinite linear !important;
            border-radius: 2px !important;
            color: transparent !important;
            min-width: 15px; /* Évite l'effondrement visuel des petits blocs */
        }
        .shimmer-line * { color: transparent !important; }

        .circular-loader {
            border: 4px solid #f3f4f6 !important;
            border-top: 4px solid #4f8ef7 !important;
            border-radius: 50% !important;
            width: 36px !important; height: 36px !important;
            animation: spin 1s linear infinite !important;
            margin-bottom: 12px !important;
        }
        @keyframes spin {
            0%   { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    """
    soup.head.append(style_tag)

    # 4. Injection du JavaScript d'accompagnement (Streaming & initialisation de transition)
    script_tag = soup.new_tag("script")
    script_tag.string = """
        window.applyTranslation = function(transId, translatedText) {
            var span = document.querySelector('[data-trans-id="' + transId + '"]');
            if (!span) return;
            var divT = span.closest('div.t');
            if (!divT) return;

            var sxOrig = parseFloat(span.getAttribute('data-sx') || '1');
            var syOrig = parseFloat(span.getAttribute('data-sy') || '1');

            if (!divT.hasAttribute('data-orig-sw')) {
                divT.style.transform = 'matrix(' + sxOrig + ',0,0,' + syOrig + ',0,0)';
                divT.setAttribute('data-orig-sw', divT.scrollWidth);
                divT.setAttribute('data-sx-orig', sxOrig);
                divT.setAttribute('data-sy-orig', syOrig);
            }

            var origSW = parseFloat(divT.getAttribute('data-orig-sw'));
            var sx     = parseFloat(divT.getAttribute('data-sx-orig'));
            var sy     = parseFloat(divT.getAttribute('data-sy-orig'));

            // Remplacer le contenu du groupe sémantique par la traduction
            span.textContent = translatedText;

            // CIBLAGE ULTRA-PRÉCIS : Retirer le Shimmer uniquement sur le span concerné
            span.classList.remove('shimmer-line');

            var newSW = divT.scrollWidth;
            if (newSW > 0 && origSW > 0) {
                var newSx = sx * (origSW / newSW);
                newSx = Math.min(newSx, sx);
                divT.style.transform = 'matrix(' + newSx + ',0,0,' + sy + ',0,0)';
            }
        };

        window.preparePageForTranslation = function(pageIdx) {
            var pages = document.querySelectorAll('.pf');
            var page = pages[pageIdx];
            if (!page) return;

            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (glass) {
                glass.style.transition = 'opacity 0.3s ease-out';
                glass.style.opacity = '0';
                setTimeout(function() { glass.remove(); }, 300);
            }

            // CIBLAGE ULTRA-PRÉCIS : On applique le Shimmer uniquement aux spans data-trans-id de la page
            page.querySelectorAll('span[data-trans-id]').forEach(function(span) {
                span.classList.add('shimmer-line');
            });
        };

        // Écouteur de messages cross-iframe sécurisé
        window.addEventListener('message', function(event) {
            var msg = event.data;
            if (!msg) return;

            if (msg.action === 'applyTranslation') {
                window.applyTranslation(msg.transId, msg.translatedText);
            } else if (msg.action === 'preparePage') {
                window.preparePageForTranslation(msg.pageIdx);
            }
        });
    """

    soup.body.append(script_tag)

    # 5. Enregistrement du fichier HTML instrumenté complet
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map, tid_to_page