# core/html_transformer.py

import os, re
import subprocess
from bs4 import BeautifulSoup, NavigableString

# Importation découplée de notre nouvel utilitaire de téléchargement
from utils.downloader import check_and_download_pdf2htmlex, DEFAULT_ASSETS_DIR



def convert_pdf_to_html(pdf_path: str, assets_dir: str = DEFAULT_ASSETS_DIR) -> str | None:
    """
    Convertit un fichier PDF en HTML brut en utilisant l'exécutable local pdf2htmlEX.
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
    result = subprocess.run(
        cmd, cwd=pdf_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120
    )
    if result.returncode == 0 and os.path.exists(output_html_path):
        print("✅ Fichier HTML brut généré.")
        return output_html_path
    return None

def wrap_text_nodes_recursively(soup, parent_element, trans_idx_ref, original_texts_map) -> None:
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


def _wrap_children_recursively(soup, element, idx, original_texts_map, tid_to_page, page_idx, sx_orig, sy_orig):
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



def instrument_html(raw_html_path: str, output_html_path: str) -> tuple[dict, dict]:
    """
    Analyse le fichier HTML de pdf2htmlEX, isole récursivement le texte,
    et injecte vos animations Shimmer vivantes, le Glass dépoli et le Loader Circulaire.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    # 1. Analyse récursive BeautifulSoup et injection des enveloppes d'isolations (row-wrapper & trans-span)
    matrix_map = parse_matrix_classes(soup)
    pages_list = soup.find_all("div", class_="pf")

    original_texts_map = {}
    tid_to_page = {}
    idx = [0]

    for div_t in soup.find_all("div", class_="t"):
        # Trouver le (sx, sy) de cette div
        classes = div_t.get("class", [])
        sx_orig, sy_orig = 1.0, 1.0
        for cls in classes:
            if cls in matrix_map:
                sx_orig, sy_orig = matrix_map[cls]
                break

        # Trouver la page parente
        page_el = div_t.find_parent("div", class_="pf")
        page_idx = pages_list.index(page_el) if page_el in pages_list else 0

        for child in list(div_t.children):
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
                child_classes  = child.get("class", [])
                if "_" not in child_classes  and child.name in ["span", "a", "b", "i", "sup", "sub", "em", "strong"]:
                    _wrap_children_recursively(soup, child, idx, original_texts_map, tid_to_page, page_idx, sx_orig, sy_orig)
                    
    # 2. INJECTION DE VOTRE GLASS DE POLI SUR TOUTES LES PAGES DU DOCUMENT (div.pf)
    pages = soup.find_all("div", class_="pf")
    for page_idx, page in enumerate(pages):
        # Création du conteneur dépoli à haute spécificité graphique
        glass_div = soup.new_tag("div", attrs={
            "id": f"glass-overlay-t-{page_idx}",
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
    style_tag.string = """
        #sidebar { display: none !important; }
        #page-container { left: 0 !important; margin: 0 auto !important; }

        @keyframes loading-shimmer {
            0%   { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        .shimmer-line {
            background: linear-gradient(90deg, #f1f5f9 25%, #cbd5e1 50%, #f1f5f9 75%) !important;
            background-size: 200% 100% !important;
            animation: loading-shimmer 1.8s infinite linear !important;
            border-radius: 2px !important;
            color: transparent !important;
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
        window.applyTranslation = function(transId, translatedText, sxOrig, syOrig) {
            var span = document.querySelector('[data-trans-id="' + transId + '"]');
            if (!span) return;
            var divT = span.closest('div.t');
            if (!divT) return;

            if (!divT.hasAttribute('data-orig-sw')) {
                divT.style.transform = 'matrix(' + sxOrig + ',0,0,' + syOrig + ',0,0)';
                divT.setAttribute('data-orig-sw', divT.scrollWidth);
                divT.setAttribute('data-sx-orig', sxOrig);
                divT.setAttribute('data-sy-orig', syOrig);
            }

            var origSW = parseFloat(divT.getAttribute('data-orig-sw'));
            var sx     = parseFloat(divT.getAttribute('data-sx-orig'));
            var sy     = parseFloat(divT.getAttribute('data-sy-orig'));

            span.textContent = translatedText;

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

            page.querySelectorAll('div.t').forEach(function(divT) {
                divT.classList.add('shimmer-line');
            });
        };
    
    """
    soup.body.append(script_tag)

    # 5. Enregistrement du fichier HTML instrumenté complet
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map, tid_to_page