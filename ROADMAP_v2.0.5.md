# RockTranslate — Audit technique & plan de travail v2.0.5

_Rédigé le 2026-11-05 à partir de l'état du code au commit `2adfe77` (branche `second`)._

Ce document a deux buts :

1. **Lister tous les problèmes constatés** dans le code (bugs, sécurité, performance, packaging, UX), avec le fichier concerné et la correction proposée.
2. **Donner un plan de travail découpé en phases** (P0 → P6), à valider une par une par l'auteur, conformément à `AGENTS.md`.

Légende de gravité : 🔴 bloquant / sécurité · 🟠 bug visible par l'utilisateur · 🟡 dette technique / perf.

---

## 0. Réponses aux questions de l'auteur

### 0.1 « Si j'ouvre un PDF de 30 pages, que se passe-t-il concrètement ? »

Le flux actuel (`core/api/translation_api.py`) est **lazy** :

| Étape | Quand | Coût pour 30 pages |
|---|---|---|
| Lecture des métadonnées (pypdf) + hash SHA-256 du fichier | À l'ouverture | Quasi instantané (lecture du fichier une fois) |
| Affichage du PDF original à gauche (PDF.js) | À l'ouverture | Immédiat, PDF.js rend les pages à la demande |
| Panneau de droite | À l'ouverture | Simple placeholder, **aucun pdf2htmlEX** |
| Conversion pdf2htmlEX | Au **premier clic « Traduire »** | Convertit **les 30 pages**, même si on ne demande que la page 5 (les options `-f/-l` existent dans `convert_pdf_to_html` mais ne sont pas utilisées) |
| Instrumentation BeautifulSoup | Juste après | Tout le document, sur un seul thread |
| Mise en cache (`cache/<sha256>/workspace.html` + `maps.json`) | Juste après | La 2ᵉ ouverture du même fichier est instantanée |
| Traduction | Ensuite | Lots envoyés **strictement l'un après l'autre** |

Donc : **le document s'ouvre tout de suite**, on n'attend pas le calcul des pages. L'attente arrive au premier clic « Traduire », et elle porte sur tout le document. Autre point : **les traductions ne sont pas sauvegardées sur disque**. Si on ferme l'application, on perd les traductions déjà payées (seule la mise en page est en cache).

### 0.2 « Comment accélérer la traduction ? »

Par ordre de gain attendu :

1. **Envoyer plusieurs lots en parallèle** (4 par défaut, réglable). C'est le gain le plus important, il peut diviser le temps par 3 ou 4. Ce qui bloque aujourd'hui : le « sliding context » contient la **traduction** du lot précédent, donc chaque lot attend le précédent. Solution : utiliser comme contexte le **texte source** des segments précédents. Il est connu dès le départ, donc les lots deviennent indépendants et parallélisables.
2. **Convertir uniquement les pages demandées** (`-f/-l` sur le fichier original, déjà supporté par `convert_pdf_to_html`). Pour « traduire la page 5 », on ne convertit que la page 5.
3. **Brancher le merger de tranches** (`core/html_merger.py`) derrière un interrupteur : pdf2htmlEX tourne sur N tranches en parallèle, puis les tranches sont fusionnées. Voir §0.3 pour le faire sans risque.
4. **Enchaîner les étapes en pipeline** : traduire la tranche 1 pendant que la tranche 2 se convertit.
5. **Réduire le bavardage Python → JS** : aujourd'hui, chaque segment déclenche 2 appels `evaluate_js`, soit des milliers d'allers-retours sur le pont pywebview. Il faut les regrouper par lot.
6. **Des lots plus gros** pour les modèles à grand contexte (table `MODEL_TOKEN_LIMITS`) : moins de requêtes, donc moins de latence cumulée.

### 0.3 « J'ai le merger mais j'ai peur de casser ce qui marche »

La peur est justifiée, et c'est le bon réflexe. Voici comment le brancher sans risque :

- **Interrupteur** `TranslationConfig.experimental_sliced_conversion` (désactivé par défaut), affiché dans « Paramètres système → Expérimental ».
- **Repli automatique** : si une tranche échoue, si la fusion lève une exception, ou si le nombre de pages fusionnées ne correspond pas au nombre attendu, on relance la conversion monobloc actuelle. L'utilisateur ne voit jamais d'échec dû au merger.
- **Garde-fou de fidélité** : `dev_tools/verify_merge_fidelity.py` existe déjà. On l'exécute en CI sur 2 ou 3 PDF de référence, avec un seuil de différence pixel ; au-delà du seuil, le build échoue.
- **Cache séparé** : la sortie fusionnée va dans `cache/<hash>/sliced/`, pour ne jamais écraser un `workspace.html` qui fonctionne.
- Activation par défaut **seulement après** une version passée en « bêta » avec l'interrupteur.

### 0.4 À propos du mail du contributeur (commit `2adfe77`, « classifier Python 3.13 »)

L'explication du mail est **techniquement fausse** : les *classifiers* PyPI sont de simples métadonnées d'affichage. **pip ne s'en sert pas pour choisir un wheel.** pip choisit un wheel selon ses *tags* (`py3-none-any`, `cp313-…`). RockTranslate est du Python pur : son wheel est déjà `py3-none-any` et s'installe sur 3.13. Ajouter le classifier ne change donc rien à l'installation.

Déclarer les versions supportées reste une bonne pratique. On le fera en phase P6, **une fois qu'une CI teste réellement 3.9 → 3.13**, pour que les classifiers disent la vérité. Pas besoin de répondre au mail ni de cliquer sur ses liens. L'expéditeur est inconnu et le message est typique des mails automatisés qui ciblent les commits publics.

---

## 1. Problèmes constatés

### 1.1 Sécurité 🔴

| # | Problème | Où | Correction |
|---|---|---|---|
| S1 | **Le serveur local sert n'importe quel fichier du disque** : `GET /local-file?path=<n'importe quoi>` avec `Access-Control-Allow-Origin: *`. Un site web ouvert dans le navigateur habituel peut scanner les ports de `127.0.0.1` et lire `~/.ssh/id_rsa`, la config contenant les clés API, etc. | `web_gui.py` `start_local_server` | Jeton aléatoire par session obligatoire dans l'URL. Liste blanche : seulement le PDF actif et `cache/<hash>/`. Suppression de `CORS *`. Vérification de l'en-tête `Host` (protection DNS-rebinding). |
| S2 | **Injection HTML depuis la sortie du LLM** : `span.innerHTML = translatedText` (après remplacement des balises `<color_…>`). Un PDF piégé (« traduis ceci par `<img src=x onerror=…>` ») ou un modèle qui dérape peut exécuter du JS dans l'iframe, qui est same-origin avec l'UI qui expose `window.pywebview.api`. | `html_transformer.py` `applyTranslation` | Échapper tout le texte, puis ne reconstruire **que** les balises `<color_XXXXXX>` via le DOM (`createElement` + `textContent`). |
| S3 | **Clés API en clair** dans le JSON de config (lisibles via S1). | `config_manager.py` | Utiliser `keyring` (trousseau de l'OS), avec repli JSON et un avertissement. |

### 1.2 « Certains PDF ne s'ouvrent pas » 🔴

Cause la plus probable : **pdf2htmlEX respecte les restrictions DRM** des PDF « protégés » (copie interdite via le mot de passe propriétaire). Il refuse alors de convertir, alors que le PDF s'affiche normalement dans PDF.js. Aucune option `--no-drm`, `--owner-password` ou `--user-password` n'est passée (`convert_pdf_to_html`). En plus, `pdf_metadata.py` ne détecte pas le chiffrement.

Correction proposée :

- Détecter le chiffrement avec pypdf (`reader.is_encrypted`, essai de `decrypt("")`). Distinguer :
  - **permissions seulement** (le PDF s'ouvre sans mot de passe) : on passe `--no-drm 1` à pdf2htmlEX. L'utilisateur traduit un document qu'il peut déjà lire ; c'est un réglage documenté de pdf2htmlEX, à mentionner dans le README.
  - **mot de passe d'ouverture** : boîte de dialogue « Ce PDF est protégé par mot de passe », puis `--user-password`.
- Les autres échecs (polices LaTeX exotiques, etc.) : remplacer le toast générique par un **message clair** qui contient les dernières lignes de stderr déjà capturées (`stderr_tail`). Il y a deux `TODO` à ce sujet dans le code.
- Ajouter un PDF protégé de test dans `dev_tools/`.

### 1.3 Traduction : threads, Stop, plages de pages 🟠

| # | Problème | Où |
|---|---|---|
| T1 | **Course Stop → Traduire** : `stop_translation` n'attend le thread qu'1 s. Or un appel LLM dure souvent 10 à 60 s. Si l'utilisateur relance tout de suite, `start_range_translation` remet `_stop_translation = False`. L'**ancien thread repart** sur l'ancienne plage, et le nouveau thread échoue à prendre le verrou puis **sort silencieusement, sans émettre `trigger-translation-finished`**. Résultat : UI bloquée en « traduction en cours ». | `translation_api.py` l. 358-409, 453-455 |
| T2 | Le contrôle du verrou (`acquire` puis `release` immédiat) ne protège rien. | idem |
| T3 | **Les traductions ne sont pas persistées** : `_translated_pages` vit en mémoire seulement. | idem |
| T4 | Les segments que le LLM « oublie » (id absent de la réponse) ne sont **jamais relancés** : la page reste à moitié traduite, avec du shimmer sur certaines lignes, mais elle est comptée comme traduite. Les ids hallucinés ne sont pas filtrés. | `_run_translation` |
| T5 | Une plage partiellement hors bornes (« 1-50 » sur 30 pages) est **ignorée en entier** au lieu d'être tronquée. | `_parse_page_range` |
| T6 | Une page demandée oblige à convertir le document entier (voir §0.1). | `_prepare_document_for_translation` |

Correction prévue : un **jeton d'annulation par exécution** (`run_id` + `threading.Event`) au lieu d'un booléen partagé. L'ancien thread vérifie son propre jeton et ne peut pas être « ressuscité ». Le verrou est pris **dans** `start_*`, et le signal `finished` part de **tous** les chemins de sortie. Les traductions sont sauvegardées dans `cache/<hash>/translations.<lang>.<model>.json` après chaque lot, ce qui permet la reprise après fermeture. Les ids manquants sont relancés une fois en mini-lot.

### 1.4 Client LLM 🟠

| # | Problème | Où |
|---|---|---|
| L1 | **Backoff et gestion du 429 inopérants** : `_call_llm` attrape *toutes* les exceptions et renvoie `None`. Le bloc `except` de `translate_batch` (attente progressive, détection rate-limit) **n'est donc jamais exécuté**, et les tentatives s'enchaînent sans pause, ce qui aggrave le rate-limit. | `llm_client.py` |
| L2 | Pas de `timeout` sur `litellm.completion` : un appel peut rester bloqué indéfiniment, ce qui bloque aussi le Stop. | idem |
| L3 | `max_tokens: 16384` fixe : certains modèles plafonnent plus bas, la requête est rejetée et l'échec est silencieux. | idem |
| L4 | Température par défaut `1.0` : trop élevée pour de la traduction (0.2–0.3 recommandé). | idem / config |
| L5 | Le repli de modèle au 3ᵉ essai change de modèle **sans le dire clairement** et prend le premier candidat sans vérifier qu'il est différent. | `_get_fallback_model_and_key` |
| L6 | Le log annonce `MAX_RETRIES` alors que la boucle utilise `max_retries` (config). | idem |

### 1.5 Fidélité / extraction 🟠

| # | Problème | Où |
|---|---|---|
| E1 | Remplacements de glyphes **globaux** `ð→(`, `Þ→)`, `¼→=`, `þ→+`, appliqués à **tout** le texte. Ils corrompent l'islandais (« Þór »), les fractions (« ¼ »), etc. Ils devraient ne s'appliquer qu'aux polices symboles fautives (détection par classe `ff`). | `instrument_html` |
| E2 | `convert_pdf_to_html` réutilise un `_raw.html` existant **sur la seule base du nom**. En mode librairie, le fichier est écrit **à côté du PDF de l'utilisateur** (échec si le dossier est en lecture seule). Deux PDF homonymes partagent le même résultat périmé. Si le processus est tué, un fichier partiel peut être réutilisé. | `html_transformer.py`, `api.py` |
| E3 | Export : le format de page vient de la **1ʳᵉ page seulement**, donc les documents mixtes portrait/paysage sont mal imprimés. | `export_translated_pdf`, `api.py` |
| E4 | Export GUI : le HTML traduit complet (des dizaines de Mo de polices base64) passe par `evaluate_js(outerHTML)`, ce qui est lent et risque de planter sur les gros documents. Python possède déjà toutes les traductions : il suffit de réutiliser `apply_translations_offline`. | `export_translated_pdf` |
| E5 | La librairie et la CLI lisent **silencieusement la config de la GUI** (`config_db` : seuil, taille des lots, température, retries). Un même script donne des résultats différents selon la machine. | `chunker.py`, `llm_client.py`, `html_transformer.py` |

### 1.6 Rendu PDF / dépendance au navigateur 🟠

| # | Problème |
|---|---|
| B1 | `find_system_chromium_browser` : sur Linux, `chromium` est souvent un **snap**, qui ne peut pas lire `/tmp` ni écrire hors de `$HOME`, ce qui fait échouer l'impression. Sur macOS, Chromium, Brave et `~/Applications` sont ignorés. Sur Windows, la recherche passe par `StartMenuInternet`, alors qu'Edge est toujours présent à un chemin connu. |
| B2 | `subprocess.run` d'impression **sans timeout** : un Chrome bloqué fige l'export pour toujours. |
| B3 | Pas de `--user-data-dir` temporaire : conflit possible avec le Chrome déjà ouvert de l'utilisateur. Pas de `--no-sandbox` quand on tourne en root (Docker/CI). |
| B4 | Le téléchargement de `chrome-headless-shell` (~100 Mo) et de l'AppImage pdf2htmlEX va dans `site-packages/rocktranslate/assets`, souvent **non inscriptible** (Python système, venv partagé). |

Stratégie proposée (phase P3) :

1. Ordre de résolution : variable `ROCKTRANSLATE_BROWSER` ou réglage → **`chrome-headless-shell` déjà en cache** (version épinglée, comportement reproductible) → navigateurs système, avec une liste de chemins par OS complétée (Edge garanti sur Windows 10/11) et les snap/flatpak écartés → téléchargement automatique dans le **dossier cache utilisateur** (`platformdirs`), pas dans `site-packages`.
2. Lancement robuste : `--headless`, `--user-data-dir` temporaire, `--no-sandbox` si root, `timeout`, journal de stderr.
3. Nouvelle commande **`rocktranslate doctor`** (vérifie pdf2htmlEX, navigateur, droits du cache, clés) et **`rocktranslate install-browser`** (téléchargement explicite, utile en CI/Docker).
4. Côté GUI Windows, en option ultérieure : imprimer via la **WebView2 de pywebview** (`CoreWebView2.PrintToPdfAsync`), sans aucun navigateur externe. Sous macOS (WKWebView) et Linux (WebKitGTK), l'API d'impression vers PDF existe, mais elle est spécifique à chaque OS et ne gère pas aussi bien la pagination. À évaluer après P3, et sans en faire la voie principale. **La CLI et la librairie n'ont de toute façon pas de webview** (serveurs, CI), donc `chrome-headless-shell` reste la base commune.

### 1.7 Packaging / release 🔴

| # | Problème |
|---|---|
| K1 | **Le wheel construit depuis le dépôt ne contient AUCUN asset** : ni `assets/ui` (HTML/JS/CSS de l'interface), ni `pdfjs`, ni les polices, ni le logo. Vérifié en construisant le wheel (`pip wheel .`) : 32 fichiers, ~0 Mo. `include_package_data=True` ne suffit pas sans `MANIFEST.in` ou `[tool.setuptools.package-data]`. Conséquence probable : `pip install "rocktranslate[gui]"` puis `rocktranslate-gui` démarre **sans interface**. _À confirmer sur le wheel 2.0.2 publié sur PyPI._ |
| K2 | À l'inverse, les **fichiers de test de pdf2htmlEX** (`assets/pdf2htmlEX/test/*.py`) sont embarqués, et le binaire Windows (21 Mo) serait embarqué pour tous les OS une fois les assets inclus. Il faut l'exclure du wheel et le télécharger à la demande (c'est déjà ce que fait `downloader.py`). |
| K3 | **`setup.py` et `pyproject.toml` divergent** : `tinycss2` est absent de `setup.py`, l'email de l'auteur diffère, les contraintes de version aussi. Il faut supprimer `setup.py` et ne garder que `pyproject.toml`. |
| K4 | Version écrite en 3 endroits (`pyproject`, `setup.py`, `__init__.py`), plus des en-têtes de modules incohérents (« Version: 1.1.0 »). Il faut une source unique : `__version__` lue dynamiquement par setuptools. |
| K5 | **Aucune CI** (`.github/` absent) : pas de tests automatiques, pas de vérification du contenu du wheel, pas de publication reproductible. |

### 1.8 Interface graphique 🟠

| # | Problème |
|---|---|
| U1 | Aucun système de thème : couleurs codées en dur. La **barre d'état est `#14151f` (noire) alors que l'interface est claire**. |
| U2 | L'overlay de l'iframe (« Waiting for translation... », verre dépoli, shimmer) a des couleurs claires codées en dur dans `html_transformer.py`, et le texte est **en anglais en dur** (non traduit par i18n). |
| U3 | Menus, modales et dialogues : styles disparates répartis dans 8 fichiers CSS. Il manque des variables communes (rayons, ombres, espacements, focus clavier). |

---

## 2. Plan de travail (phases à valider une par une)

> Numéro de version : tu as écrit à la fois « 2.05 » et « 2.5 ». **Je propose `2.0.5`** (après `2.0.2`). Si tu préfères marquer le saut fonctionnel (thèmes + extraction structurée), `2.1.0` est plus conforme au versionnage sémantique. La décision t'appartient ; elle se change en une ligne.

### P0 — Correctifs critiques (sécurité + packaging) · _petit, prioritaire_
- [ ] S1 serveur local : jeton, liste blanche, suppression de CORS `*`, contrôle de `Host`.
- [ ] S2 `applyTranslation` sans `innerHTML` sur du texte non fiable.
- [ ] K1/K2/K3 : `package-data` explicite, exclusion des binaires et des tests pdf2htmlEX, suppression de `setup.py`, test automatique « le wheel contient `assets/ui/index.html` ».
- [ ] E1 : remplacements de glyphes limités aux polices symboles.
- **Validation** : `rocktranslate-gui` fonctionne depuis un wheel installé dans un venv vierge, et un test vérifie que `/local-file` refuse un chemin hors liste blanche.

### P1 — Fiabilité de la traduction
- [ ] T1/T2 jeton d'annulation par exécution, verrou correct, `finished` toujours émis.
- [ ] L1/L2/L3/L5/L6 client LLM : exceptions remontées, vrai backoff, timeout, `max_tokens` par modèle, repli explicite.
- [ ] T4 validation des ids + relance des segments manquants.
- [ ] T3 persistance des traductions et reprise après fermeture.
- [ ] T5 plages tronquées au lieu d'être ignorées.
- [ ] 1.2 PDF protégés : détection, `--no-drm`, dialogue mot de passe, messages d'erreur clairs.
- **Validation** : `dev_tools/test_lazy_pipeline.py` étendu (LLM stubbé, aucun vrai appel), avec les scénarios Stop→Start rapide, LLM qui oublie des ids, 429 simulé et PDF protégé.

### P2 — Vitesse
- [ ] Lots parallèles (concurrence réglable, 4 par défaut), contexte = texte source.
- [ ] Conversion limitée aux pages demandées (`-f/-l`).
- [ ] Événements JS regroupés par lot.
- [ ] Merger branché derrière l'interrupteur + repli + CI de fidélité (§0.3).
- **Validation** : mesure avant/après sur `Tankeu et al. 2026.pdf` (40 p.), avec un LLM stubbé à latence fixe pour isoler le gain d'orchestration.

### P3 — Rendu PDF sans dépendance fragile au navigateur
- [ ] Résolveur réécrit (§1.6), cache utilisateur, timeout, `--user-data-dir`.
- [ ] `rocktranslate doctor` et `rocktranslate install-browser`.
- [ ] E3/E4 : format de page par page, export à partir de l'état Python.
- **Validation** : export testé sur Windows, Linux (y compris snap) et macOS, et en CI Linux sans navigateur installé.

### P4 — Interface v2.0.5 : thèmes clair/sombre
- [ ] Jetons de design (`--rt-bg`, `--rt-surface`, `--rt-text`, `--rt-accent`, `--rt-border`, rayons, ombres) dans `global.css`, déclinés en clair et sombre, avec un mode « Système » (`prefers-color-scheme`) et un choix mémorisé.
- [ ] Barre d'état et barre de progression refaites aux couleurs du thème.
- [ ] Barre de menus et menus déroulants, modales et dialogues harmonisés (même en-tête, même pied à boutons, focus clavier, Échap pour fermer).
- [ ] Overlay de l'iframe thématisé et traduit (i18n).
- [ ] Sélecteur de thème dans « Paramètres système ».
- **Validation** : captures avant/après des 2 thèmes sur chaque écran (dashboard, workspace, chaque modale).

### P5 — RockTranslate Structure : « l'ADN d'un PDF » (équivalent Unstructured)
Objectif : à partir d'un PDF, produire une **représentation structurée** utilisable pour le RAG, l'analyse ou l'indexation, en plus de la traduction.

API visée :

```python
from rocktranslate import partition_pdf

doc = partition_pdf("article.pdf", pages="1-5")
doc.to_json()        # éléments typés + coordonnées
doc.to_markdown()    # titres, paragraphes, listes, tableaux en Markdown
doc.to_html()
doc.chunks(max_tokens=800)   # découpage prêt pour le RAG, par section
```

```bash
rocktranslate extract article.pdf --format json|markdown|html -o out/
```

Modèle de données : `Document → Page → Element`, avec pour chaque élément : `type` (`Title`, `Heading(level)`, `Paragraph`, `ListItem`, `Table`, `Caption`, `Formula`, `Header`, `Footer`, `PageNumber`, `Footnote`, `Reference`, `Figure`), `text`, `bbox`, `page`, `font` (famille, taille, gras), `reading_order`, `parent_id` (section).

Pourquoi c'est faisable avec ce qui existe : le pipeline sait déjà, pour chaque ligne, sa **position exacte, sa police, sa taille, sa couleur et sa page** (matrices pdf2htmlEX, classes `ff`/`fs`/`x`/`y`). Les heuristiques à ajouter sont :

- **Titres et niveaux** : taille et graisse de police par rapport à la taille dominante du document.
- **En-têtes et pieds de page** : lignes qui se répètent à la même position sur plusieurs pages.
- **Ordre de lecture multi-colonnes** : regroupement par colonnes selon les coordonnées `x`.
- **Tableaux** : les coupures « structurelles » (`THRESHOLD_PX`) déjà détectées alignent des cellules en colonnes.
- **Formules, références et légendes** : motifs (`Fig.`, `Table`, `[12]`) plus la densité de symboles, en partie déjà présents dans `chunker.should_translate`.

Limites assumées, à écrire dans le README : Unstructured utilise des modèles de vision et de l'OCR. RockTranslate Structure visera les **PDF nés numériques** (articles, rapports), avec une géométrie exacte, sans GPU et sans service distant. Les PDF scannés nécessiteraient un OCR (option future, par exemple via `ocrmypdf`).

Découpage interne : P5a modèle de données + JSON · P5b Markdown + chunks · P5c tableaux · P5d CLI et documentation.
- **Validation** : jeu de 3 à 5 PDF de référence avec une sortie JSON « attendue » relue à la main, et des tests de non-régression.

### P6 — Publication v2.0.5
- [ ] CI GitHub Actions : tests sur Python 3.9 → 3.13 (Linux et Windows), contrôle du contenu du wheel, **classifiers** mis à jour en conséquence.
- [ ] Publication PyPI via **Trusted Publishing** (OIDC, sans jeton à stocker), déclenchée par un tag `v2.0.5`.
- [ ] Release GitHub : installeur Windows (`dev_tools/build_app.py` + `installer.iss`) + notes de version.
- [ ] README : nouvelles fonctions (thèmes, `extract`, `doctor`), section sur les PDF protégés, badges de version à jour.
- [ ] Landing page (`docs/`) refaite, avec les thèmes clair et sombre et une section « Structure ».
- [ ] **Nom de domaine** : idées à vérifier chez un registrar (prix coûtant chez Cloudflare Registrar ou Porkbun) : `rocktranslate.app`, `rocktranslate.dev`, `rocktranslate.org`. Ensuite, fichier `docs/CNAME` + configuration DNS GitHub Pages + HTTPS forcé.

---

## 3. Ordre recommandé et règles de travail

1. **P0 d'abord** : ce sont des failles et un paquet PyPI probablement cassé. C'est court, et tout le reste en dépend.
2. Puis P1 → P2 (le cœur), P3, P4 (visible), P5 (la grande nouveauté), P6 (release).
3. Chaque phase = une série de commits sur `second`, testée avec le LLM **stubbé** (aucun appel API payant sans accord), puis validée par l'auteur avant la phase suivante.
4. Décisions déjà actées et non remises en cause : pas de réécriture Rust/C, pdf2htmlEX 0.14.6 sous Windows, dossiers d'archives conservés.
