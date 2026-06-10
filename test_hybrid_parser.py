import os
import re
import webbrowser
from bs4 import BeautifulSoup

# Nom des fichiers
INPUT_HTML_FILENAME = "1_PDFsam_Nsangou Ngapna et al._ASR_2024_raw.html"
OUTPUT_HTML_FILENAME = "output_test_visualization.html"


def parse_spacer_widths(soup) -> dict:
    """
    Scanne les balises <style> et extrait la largeur physique en pixels
    de chaque classe d'espacement (ex: ._19{width:85.123px;} -> {"19": 85.123})
    """
    spacer_map = {}
    for style_tag in soup.find_all("style"):
        text = style_tag.string or ""
        # Expression régulière pour capturer le nom du spacer et sa largeur en px
        for m in re.finditer(r'\._(\w+)\s*\{\s*width\s*:\s*([\d\.]+)\s*px\s*;?\s*\}', text):
            cls = m.group(1)
            width = float(m.group(2))
            spacer_map[cls] = width
    return spacer_map


def generate_visual_test():
    if not os.path.exists(INPUT_HTML_FILENAME):
        print(f"❌ Erreur : Le fichier brut '{INPUT_HTML_FILENAME}' est introuvable.")
        print("Veuillez placer ce script dans le même répertoire que votre fichier HTML.")
        return

    print("📖 Lecture du fichier brut...")
    with open(INPUT_HTML_FILENAME, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    # 1. Analyse géométrique des largeurs d'espacement
    spacer_map = parse_spacer_widths(soup)
    print(f"📐 {len(spacer_map)} classes d'espacement CSS analysées.")

    # Seuil en pixels : Tout espace >= 20px est considéré comme une colonne de tableau
    THRESHOLD_PX = 20.0

    print("⚡ Analyse et marquage géométrique des lignes...")
    
    # 2. Parcours et reconstruction des div.t
    for div_t in soup.find_all("div", class_="t"):
        children = list(div_t.contents)
        div_t.clear()  # Vider pour reconstruire visuellement

        current_group_text = []
        current_group_elements = []

        def commit_group():
            nonlocal current_group_text, current_group_elements
            if not current_group_elements:
                return
            
            merged_text = "".join(current_group_text).strip()
            if merged_text:
                # Créer un cadre vert pour l'unité fusionnée qui sera envoyée à l'IA
                group_span = soup.new_tag("span", attrs={
                    "style": "background-color: rgba(40, 167, 69, 0.2); border: 1px solid #28a745; border-radius: 3px; padding: 1px 2px; margin: 0 1px; display: inline-block; vertical-align: middle;",
                    "title": f"Envoyé au LLM d'un seul bloc : '{merged_text}'"
                })
                for el in current_group_elements:
                    group_span.append(el)
                div_t.append(group_span)
            else:
                for el in current_group_elements:
                    div_t.append(el)
            
            current_group_text = []
            current_group_elements = []

        for child in children:
            is_spacer = False
            width = 0.0

            # Détecter si le nœud enfant est un spacer pdf2htmlEX
            if child.name == "span" and child.get("class"):
                classes = child.get("class")
                if "_" in classes:
                    is_spacer = True
                    for cls in classes:
                        if cls.startswith("_") and len(cls) > 1:
                            idx_str = cls[1:]
                            width = spacer_map.get(idx_str, 0.0)
                            break

            if is_spacer:
                if width >= THRESHOLD_PX:
                    # Grand espace (Tableau) -> On valide l'unité en cours
                    commit_group()
                    # Injecter une barre rouge pointillée pour simuler la séparation de colonne
                    spacer_indicator = soup.new_tag("span", attrs={
                        "style": f"display: inline-block; width: {width}px; background-color: rgba(220, 53, 69, 0.15); border-left: 2px dashed #dc3545; border-right: 2px dashed #dc3545; height: 14px; vertical-align: middle; text-align: center; font-size: 8px; color: #dc3545; line-height: 14px; font-weight: bold; overflow: hidden;",
                        "title": f"Coupure de tableau ! Largeur : {width}px"
                    })
                    spacer_indicator.string = "✂"
                    div_t.append(spacer_indicator)
                else:
                    # Petit espace (Espace inter-mots normal) -> On continue de fusionner
                    current_group_elements.append(child)
                    current_group_text.append(" ")
            else:
                # Texte ou balise de style classique
                if isinstance(child, str):
                    current_group_text.append(str(child))
                    current_group_elements.append(child)
                else:
                    current_group_text.append(child.get_text())
                    current_group_elements.append(child)

        # Enregistrer le dernier groupe restant
        commit_group()

    # 3. Injection d'un panneau d'explications flottant pour vous guider
    legend_div = soup.new_tag("div", attrs={
        "style": (
            "position: fixed; top: 15px; left: 15px; z-index: 100000; "
            "background: rgba(255, 255, 255, 0.96); padding: 18px; border-radius: 10px; "
            "box-shadow: 0 10px 30px rgba(0,0,0,0.25); border: 1px solid #ddd; "
            "font-family: 'Segoe UI', Arial, sans-serif; font-size: 13px; width: 320px; line-height: 1.5;"
        )
    })
    legend_div.string = ""
    
    title = soup.new_tag("h3", attrs={"style": "margin: 0 0 10px 0; color: #1e293b; font-size: 15px; font-weight: bold;"})
    title.string = "Analyseur Hybride RockTranslate"
    legend_div.append(title)

    desc = soup.new_tag("p", attrs={"style": "margin: 0 0 12px 0; color: #64748b; font-size: 12px;"})
    desc.string = "Visualisez comment l'algorithme découpe vos textes et vos tableaux avant de les envoyer à la traduction."
    legend_div.append(desc)

    # Indicateur Vert
    row1 = soup.new_tag("div", attrs={"style": "display: flex; align-items: center; margin-bottom: 8px;"})
    box1 = soup.new_tag("div", attrs={"style": "width: 24px; height: 16px; background: rgba(40, 167, 69, 0.2); border: 1px solid #28a745; border-radius: 3px; margin-right: 10px;"})
    label1 = soup.new_tag("span", attrs={"style": "color: #334155; font-weight: 500;"})
    label1.string = "Zone Verte : Phrase fusionnée"
    row1.append(box1)
    row1.append(label1)
    legend_div.append(row1)

    # Indicateur Rouge
    row2 = soup.new_tag("div", attrs={"style": "display: flex; align-items: center;"})
    box2 = soup.new_tag("div", attrs={"style": "width: 24px; height: 16px; background: rgba(220, 53, 69, 0.15); border-left: 2px dashed #dc3545; border-right: 2px dashed #dc3545; margin-right: 10px;"})
    label2 = soup.new_tag("span", attrs={"style": "color: #334155; font-weight: 500;"})
    label2.string = "Zone Rouge / Ciseaux : Coupure tableau"
    row2.append(box2)
    row2.append(label2)
    legend_div.append(row2)

    soup.body.append(legend_div)

    # 4. Sauvegarde et ouverture
    print(f"💾 Écriture du fichier de test de sortie dans '{OUTPUT_HTML_FILENAME}'...")
    with open(OUTPUT_HTML_FILENAME, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print("🌐 Ouverture de la visualisation dans votre navigateur...")
    webbrowser.open("file://" + os.path.abspath(OUTPUT_HTML_FILENAME))
    print("✅ Terminé. Observez la page qui vient de s'ouvrir pour vérifier la précision de la découpe.")


if __name__ == "__main__":
    generate_visual_test()