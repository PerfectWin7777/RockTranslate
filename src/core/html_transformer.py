# core/html_transformer.py

import os
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


def instrument_html(raw_html_path: str, output_html_path: str) -> dict[str, str]:
    """
    Analyse le fichier HTML de pdf2htmlEX, isole récursivement le texte,
    et injecte vos animations Shimmer vivantes et d'apparitions d'origine.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    text_divs = soup.find_all("div", class_="t")
    original_texts_map = {}
    trans_idx_ref = [0] # Passage par référence pour l'indexation récursive unique

    # 1. Analyse récursive BeautifulSoup et injection des enveloppes d'isolations (row-wrapper & trans-span)
    for div in text_divs:
        children = list(div.contents)
        div.clear()

        # Enveloppe globale protectrice de ligne
        wrapper = soup.new_tag("span", attrs={"class": "row-wrapper"})
        div.append(wrapper)

        # Descente récursive pour envelopper 100% des chaînes de texte de la ligne
        for child in children:
            if isinstance(child, NavigableString):
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
                    wrapper.append(new_span)
                    trans_idx_ref[0] += 1
                else:
                    wrapper.append(child)
            elif child.name == "span" and child.get("class") and any(c.startswith("_") for c in child.get("class")):
                wrapper.append(child)
            elif child.name in ["span", "a", "b", "i", "sup", "sub", "em", "strong"]:
                wrap_text_nodes_recursively(soup, child, trans_idx_ref, original_texts_map)
                wrapper.append(child)
            else:
                wrapper.append(child)

    # 2. Injection de vos styles originaux d'animation Shimmer dynamique et Fade-In d'écriture
    style_tag = soup.new_tag("style")
    style_tag.string = """
        /* ── MASQUAGE DE LA BARRE LATÉRALE pdf2htmlEX ET RECENTrage ── */
        #sidebar { 
            display: none !important; 
        }
        #page-container { 
            left: 0 !important; 
            margin: 0 auto !important; 
        }

        .row-wrapper {
            display: inline-block !important;
            white-space: nowrap !important;
            border-radius: 3px !important;
            transition: transform 0.1s ease-out;
        }
        .trans-span {
            display: inline-block;
        }
        
        /* ── ANIMATIONS VIVANTES DU SQUELETTE (SUR LA LIGNE ENTIÈRE) ── */
        @keyframes loading-shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        .translated-skeleton {
            background: linear-gradient(90deg, #f1f5f9 25%, #cbd5e1 50%, #f1f5f9 75%) !important;
            background-size: 200% 100% !important;
            animation: loading-shimmer 1.8s infinite linear !important;
            border-radius: 4px !important;
        }
        
        /* CORRECTIF DE SPÉCIFICITÉ : Rend absolument tous les sous-éléments transparents sous le Shimmer */
        .translated-skeleton,
        .translated-skeleton * {
            color: transparent !important;
            text-decoration: none !important;
        }
        
        .fade-in {
            animation: fadeInEffect 0.5s ease-out forwards;
        }
        
        @keyframes fadeInEffect {
            from { opacity: 0; transform: translateY(1px); }
            to   { opacity: 1; transform: translateY(0); }
        }
    """
    soup.head.append(style_tag)

    # 3. Injection du moteur JavaScript avec transition d'apparition Fade-In
    script_tag = soup.new_tag("script")
    script_tag.string = """
        window.streamTranslatedElementById = function(transId, translatedText) {
            var el = document.querySelector('.trans-span[data-trans-id="' + transId + '"]');
            if (!el) return;

            var wrapper = el.closest('.row-wrapper');
            var origWidth = parseFloat(wrapper.getAttribute('data-orig-width'));

            // On retire le squelette de la ligne complète dès qu'un élément commence à s'écrire
            if (wrapper.classList.contains('translated-skeleton')) {
                wrapper.classList.remove('translated-skeleton');
            }

            // Application de la transition d'apparition fluide
            el.classList.add('fade-in');
            el.innerHTML = "";

            var words = translatedText.split(" ");
            var currentWordIdx = 0;

            function appendNextWord() {
                if (currentWordIdx < words.length) {
                    el.innerHTML += (currentWordIdx === 0 ? "" : " ") + words[currentWordIdx];
                    currentWordIdx++;
                    
                    compressWrapperIfNeeded(wrapper, origWidth);
                    
                    setTimeout(appendNextWord, 15);
                } else {
                    compressWrapperIfNeeded(wrapper, origWidth);
                }
            }
            appendNextWord();
        };

        function compressWrapperIfNeeded(wrapper, origWidth) {
            if (origWidth <= 0) return;
            
            wrapper.style.transform = 'none';
            var currentWidth = wrapper.getBoundingClientRect().width;
            
            if (currentWidth > origWidth) {
                var scale = origWidth / currentWidth;
                wrapper.style.transform = 'scaleX(' + scale + ')';
                wrapper.style.transformOrigin = 'left center';
            }
        }

        window.onload = function() {
            var wrappers = document.querySelectorAll('.row-wrapper');
            wrappers.forEach(function(wrapper) {
                var origWidth = wrapper.getBoundingClientRect().width;
                wrapper.setAttribute('data-orig-width', origWidth);
                
                // Le Shimmer est appliqué sur la ligne entière
                wrapper.classList.add('translated-skeleton');
            });
        };
    """
    soup.body.append(script_tag)

    # 4. Enregistrement de l'espace de travail
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map