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
    et injecte vos animations Shimmer vivantes, le Glass dépoli et le Loader Circulaire.
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    # 1. Analyse récursive BeautifulSoup et injection des enveloppes d'isolations (row-wrapper & trans-span)
    text_divs = soup.find_all("div", class_="t")
    original_texts_map = {}
    trans_idx_ref = [0] # Passage par référence pour l'indexation récursive unique

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

        /* ── ANIMATION DU CHARGEMENT CIRCULAIRE DE VOTRE PROTOTYPE ── */
        .circular-loader {
            border: 4px solid #f3f4f6 !important;
            border-top: 4px solid #4f8ef7 !important;
            border-radius: 50% !important;
            width: 36px !important;
            height: 36px !important;
            animation: spin 1s linear infinite !important;
            margin-bottom: 12px !important;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    """
    soup.head.append(style_tag)

    # 4. Injection du JavaScript d'accompagnement (Streaming & initialisation de transition)
    script_tag = soup.new_tag("script")
    script_tag.string = """
        // Étape 1 : Retirer le Glass Dépoli d'une page et basculer ses lignes en Squelettes (shimmers)
        window.preparePageForTranslation = function(pageIdx) {
            var glass = document.getElementById('glass-overlay-t-' + pageIdx);
            if (glass) {
                // Transition de fondu douce lors de la disparition
                glass.style.transition = 'opacity 0.3s ease-out';
                glass.style.opacity = '0';
                setTimeout(function() { 
                    glass.remove(); 
                }, 300);
            }

            // Basculement de toutes les lignes (row-wrapper) de cette page en squelettes animés !
            // pdf2htmlEX utilise les formats pf1, pf2, ..., pfa, pfb pour les ID de pages
            var pageHex = (pageIdx + 1).toString(16);
            var pageElement = document.getElementById('pf' + pageHex);
            if (pageElement) {
                var wrappers = pageElement.querySelectorAll('.row-wrapper');
                wrappers.forEach(function(wrapper) {
                    wrapper.classList.add('translated-skeleton');
                });
            }
        };

        // Étape 2 : Remplacement progressif mot par mot lors de la traduction reçue
        window.streamTranslatedElementById = function(transId, translatedText) {
            var el = document.querySelector('.trans-span[data-trans-id="' + transId + '"]');
            if (!el) return;

            var wrapper = el.closest('.row-wrapper');
            var origWidth = parseFloat(wrapper.getAttribute('data-orig-width'));

            // ── DEBLOCAGE AUTOMATIQUE ET TRANSITION EN SQUELETTES DE LA PAGE EN COURS ──
            // Recherche du conteneur de page parent (.pf)
            var pageElement = el.closest('.pf');
            if (pageElement) {
                var pageId = pageElement.id; // Ex: "pf1" ou "pfa"
                var pageHex = pageId.replace('pf', '');
                var pageIdx = parseInt(pageHex, 16) - 1; // Conversion hexadécimale en index 0-based
                
                // Si le voile dépoli de verre est toujours présent, on le retire et on active les squelettes de la page !
                var glass = document.getElementById('glass-overlay-t-' + pageIdx);
                if (glass) {
                    window.preparePageForTranslation(pageIdx);
                }
            }

            // On retire le squelette de la ligne complète dès qu'un élément commence à s'écrire
            if (wrapper.classList.contains('translated-skeleton')) {
                wrapper.classList.remove('translated-skeleton');
            }

            // Transition d'apparition d'écriture fluide
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

        // Étape 3 : Mesure géométrique initiale à l'ouverture du document (Pas de squelette appliqué !)
        window.onload = function() {
            var wrappers = document.querySelectorAll('.row-wrapper');
            wrappers.forEach(function(wrapper) {
                var origWidth = wrapper.getBoundingClientRect().width;
                wrapper.setAttribute('data-orig-width', origWidth);
            });
        };
    """
    soup.body.append(script_tag)

    # 5. Enregistrement du fichier HTML instrumenté complet
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map