# RockTranslate — v2.0.6 : du traducteur au lecteur de PDF

_Rédigé le 2026-11-12. Fait suite à [ROADMAP_v2.0.5.md](ROADMAP_v2.0.5.md)._

La 2.0.6 regroupe deux choses :

1. **Les correctifs des bugs trouvés en testant la 2.0.5** (voir [CHANGELOG.md](CHANGELOG.md)).
2. **19 fonctions de lecture** qui font de RockTranslate un lecteur de PDF au quotidien : on lit l'original, et l'aide vient au passage qu'on lit.

Légende : ✅ fait et testé · 🧪 fait, à valider par l'auteur sur Windows.

---

## A. Traduire pendant la lecture

| # | Fonction | État | Où dans le code |
|---|---|---|---|
| 1 | **Bulle de traduction sur sélection** (barre flottante, clic droit, `Ctrl+T`), réponse en flux : 1er mot ≈ 1,2 s, paragraphe ≈ 2 s | ✅ | `assets/ui/js/reader.js` (barre, bulle), `core/api/reader_api.py` (`assist_start`), `core/assist.py` (`translate_text`) |
| 2 | **« Expliquer »** dans la même bulle (`Ctrl+E`) : passage en mots simples, symboles d'une formule | ✅ | `core/assist.py` (`explain_text`) |
| 3 | **Traduction continue** : les pages lues se traduisent au fil de la lecture | ✅ | `reader.js` (`setContinuous`), `reader_api.py` (`auto_translate_pages`) |
| 4 | **Maintenir Alt** pour voir l'original (vue traduction seule) | ✅ | `reader.js` (`altDown` / `altUp`) |

## B. Comprendre l'article sans le quitter

| # | Fonction | État | Où |
|---|---|---|---|
| 5 | **Citations cliquables** : aperçu de la référence, DOI, « Ouvrir et traduire » pour arXiv | ✅ | `reader.js` (`showPreview`, `resolveTarget`) |
| 6 | **Aperçu de Figure / Table / Équation** au survol (liens internes du PDF, aussi dans le volet traduit) | ✅ | `reader.js` (`linkHover`) |
| 7 | **Sommaire automatique** quand le PDF n'a pas de signets (titres numérotés, lettrés, connus) | ✅ | `assets/ui/js/sidepanel.js` (`rtDetectHeadings`) ; API : `Document.toc()` |
| 8 | **Glossaire de l'article**, modifiable, appliqué aux traductions du document | ✅ | `sidepanel.js`, `reader_api.py` (`generate_doc_glossary`, `_effective_glossary`), `assist.build_glossary` ; CLI `glossary`, `--glossary`, `--auto-glossary` |
| 9 | **Résumé par section** (∑ dans le sommaire) | ✅ | `sidepanel.js` (`summarize`), `assist.summarize_text` ; CLI `summarize --section` |
| 10 | **Questions sur l'article**, réponse + citations exactes vérifiées, clic → passage surligné | ✅ | `sidepanel.js` (`ask`), `assist.ask_document` ; CLI `ask` ; API `rocktranslate.ask` |
| 11 | **Recherche bilingue** (original + traduction, accents ignorés) | ✅ | `reader_api.py` (`search_document`), `sidepanel.js` |

## C. Devenir le lecteur PDF par défaut

| # | Fonction | État | Où |
|---|---|---|---|
| 12 | **« Ouvrir avec RockTranslate »**, case optionnelle « lecteur par défaut » dans l'installateur, **instance unique** | 🧪 | `dev_tools/installer.iss` ([Registry], tâche `pdfdefault`), `core/single_instance.py`, `web_gui.py` |
| 13 | **Reprise de lecture** (dernière page par document) | ✅ | `reader_api.py` (`get/save_reading_position`, fichier `library/<hash>.json` hors du cache) |
| 14 | **Onglets**, mode nuit qui n'inverse pas les figures | ✅ | `workspace.html` (`#rt-tabs`), `reader.js` (`switchTab`, `setNight`) |
| 15 | **Ouverture instantanée** (préparation de la mise en page en arrière-plan, sans IA) | ✅ (existant, conservé) | `core/api/translation_api.py` |

## D. Garder et partager

| # | Fonction | État | Où |
|---|---|---|---|
| 16 | **Copie propre** (sans retours à la ligne ni césures) et **copie avec citation** | ✅ | `reader.js` (`copy`, `cite`), `reader_api.py` (`get_doc_citation`) |
| 17 | **Export bilingue côte à côte** (page originale \| page traduite, vectoriel) | ✅ | `core/side_by_side.py` ; menu Outils ; CLI `--side-by-side` ; API `side_by_side=` |
| 18 | **Surlignages et notes**, export Markdown | ✅ | `reader.js` (`addHighlight`), onglet Notes de `sidepanel.js` |
| 19 | **Palette de commandes** `Ctrl+K` et raccourcis | ✅ | `reader.js` (`RT.palette`, `shortcutFor`) |

Plus, repris de Foxit : **Instantané** (zone ou page, original ou traduction → presse-papiers), menu **Outils**.

---

## Tests

- `dev_tools/test_v206_reader.py` : copie propre, glossaire, vérification des citations, côte à côte, bibliothèque par document, recherche, instance unique, liens PDF (sans appel LLM).
- `dev_tools/gui_harness.py` : l'interface réelle dans Chromium avec la vraie API Python (pont HTTP à la place de pywebview), pour piloter l'application avec Playwright.
- Testé en réel sur *U-FNO* (arXiv 2109.03697, 37 pages) : bulle 2,0 s / 0,0002 $, question 0,006 $, glossaire 0,006 $, résumé de section, aperçus de citations, instantané, traduction continue, onglets, export côte à côte (37 feuilles).

## À valider par l'auteur (Windows)

- Association .pdf et double-clic sur un PDF (installateur construit par la CI sur `second`).
- Presse-papiers d'images dans WebView2 (sinon l'image est proposée en fichier PNG).

## Idées pour la suite (2.0.7)

- Questions sur **plusieurs articles** (bibliothèque locale des PDF lus).
- Surlignages dans le volet traduit, et réécriture des surlignages dans le PDF.
- Rendu LaTeX des formules dans la bulle « Expliquer ».
