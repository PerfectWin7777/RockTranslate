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


def instrument_html(raw_html_path: str, output_html_path: str) -> dict[str, str]:
    """
    Analyse le fichier HTML de pdf2htmlEX, isole les zones de texte sans toucher
    aux spacers de colonnes, et injecte le CSS/JS de production.
    
    Retourne :
        dict[str, str]: Un dictionnaire des textes d'origine à traduire {"id_texte": "texte_anglais"}
    """
    with open(raw_html_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    text_divs = soup.find_all("div", class_="t")
    original_texts_map = {}
    trans_idx = 0

    # 1. Analyse BeautifulSoup de la structure et injection des balises d'isolation (row-wrapper & trans-span)
    for div in text_divs:
        children = list(div.contents)
        div.clear() # On vide la ligne pour la reconstruire avec nos éléments d'isolation

        # Enveloppe globale protectrice de ligne
        wrapper = soup.new_tag("span", attrs={"class": "row-wrapper"})
        div.append(wrapper)

        for child in children:
            if isinstance(child, NavigableString):
                text_val = str(child)
                if text_val.strip():
                    text_id = f"t-{trans_idx}"
                    original_texts_map[text_id] = text_val
                    
                    new_span = soup.new_tag("span", attrs={
                        "class": "trans-span",
                        "data-trans-id": text_id,
                        "data-orig-text": text_val
                    })
                    new_span.string = text_val
                    wrapper.append(new_span)
                    trans_idx += 1
                else:
                    wrapper.append(child)
            elif child.name == "a":
                # Traitement récursif de sécurité pour les liens hypertextes
                a_children = list(child.contents)
                child.clear()
                for a_child in a_children:
                    if isinstance(a_child, NavigableString):
                        a_text_val = str(a_child)
                        if a_text_val.strip():
                            text_id = f"t-{trans_idx}"
                            original_texts_map[text_id] = a_text_val
                            
                            new_span = soup.new_tag("span", attrs={
                                "class": "trans-span",
                                "data-trans-id": text_id,
                                "data-orig-text": a_text_val
                            })
                            new_span.string = a_text_val
                            child.append(new_span)
                            trans_idx += 1
                        else:
                            child.append(a_child)
                    else:
                        child.append(a_child)
                wrapper.append(child)
            else:
                # Préservation des balises d'espacement (spacers) de pdf2htmlEX
                wrapper.append(child)

    # 2. Injection du style CSS de production (Squelettes shimmer & styles de lignes)
    style_tag = soup.new_tag("style")
    style_tag.string = """
        .row-wrapper {
            display: inline-block !important;
            white-space: nowrap !important;
        }
        .trans-span {
            display: inline-block;
        }
        .translated-skeleton {
            color: transparent !important; /* Rend le texte d'origine invisible */
            background: linear-gradient(90deg, #e2e8f0 25%, #cbd5e1 50%, #e2e8f0 75%) !important;
            background-size: 200% 100% !important;
            animation: loading-shimmer 1.5s infinite linear !important;
            border-radius: 3px !important;
        }
        @keyframes loading-shimmer {
            0% { background-position: -200% 0; }
            100% { background-position: 200% 0; }
        }
    """
    soup.head.append(style_tag)

    # 3. Injection du moteur JavaScript universel (Streaming d'écriture et compression scaleX)
    script_tag = soup.new_tag("script")
    script_tag.string = """
        // Fonction universelle appelée par PyQt, CLI ou API pour injecter une traduction reçue
        window.streamTranslatedElementById = function(transId, translatedText) {
            var el = document.querySelector('.trans-span[data-trans-id="' + transId + '"]');
            if (!el) return;

            el.classList.remove('translated-skeleton');
            el.innerHTML = "";

            var wrapper = el.closest('.row-wrapper');
            var origWidth = parseFloat(wrapper.getAttribute('data-orig-width'));

            var words = translatedText.split(" ");
            var currentWordIdx = 0;

            function appendNextWord() {
                if (currentWordIdx < words.length) {
                    el.innerHTML += (currentWordIdx === 0 ? "" : " ") + words[currentWordIdx];
                    currentWordIdx++;
                    
                    // Réduction d'échelle horizontale de l'enveloppe entière si nécessaire
                    compressWrapperIfNeeded(wrapper, origWidth);
                    
                    setTimeout(appendNextWord, 15); // Débit fluide à l'écriture (15ms)
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

        // Phase d'initialisation : Mesure géométrique et activation des squelettes d'attente
        window.onload = function() {
            var wrappers = document.querySelectorAll('.row-wrapper');
            wrappers.forEach(function(wrapper) {
                var origWidth = wrapper.getBoundingClientRect().width;
                wrapper.setAttribute('data-orig-width', origWidth);
            });

            var spans = document.querySelectorAll('.trans-span');
            spans.forEach(function(el) {
                el.classList.add('translated-skeleton');
            });
        };
    """
    soup.body.append(script_tag)

    # 4. Enregistrement du fichier instrumenté de production
    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    return original_texts_map