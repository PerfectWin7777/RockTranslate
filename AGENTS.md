# AGENTS.md — Règles de collaboration pour agents IA (ZCode et autres)

Dernière mise à jour : 2026-09-05

## Workflow git (RÈGLE PRINCIPALE)

- **Toujours travailler sur la branche `second`** : c'est la branche de développement
  de l'auteur. Les commits et pushes y sont autorisés librement.
- **`main` = branche de production (stable)** : ne jamais committer directement sur
  `main`. L'auteur valide d'abord en prod depuis `second`, puis merge lui-même vers
  `main` quand tout est bon.
- `legacy-qt` : archive de l'ancienne interface PyQt6 (avant la migration pywebview).
  Ne pas supprimer.
- `archive/legacy-engines` : archive des anciens moteurs d'extraction
  (`old_pdfium/`, `old_pymupdf/` — ère PyMuPDF/pdfium avant le pipeline pdf2htmlEX).
  **Ne jamais supprimer ces dossiers** : ils documentent le cheminement du projet.
- Ne jamais forcer un push (`--force`) sans demande explicite de l'auteur.

## Contexte produit

- RockTranslate : traducteur de PDF académiques avec préservation exacte du layout
  (pdf2htmlEX → HTML instrumenté → LLM → ré-injection → impression navigateur headless).
- GUI : pywebview + SPA Alpine.js (`src/rocktranslate/assets/ui/`). La migration
  PyQt6 → pywebview est **terminée** : plus aucune trace de Qt dans le code actif.
- Le README et pyproject.toml doivent rester alignés avec cette réalité.

## Décisions produit actées (ne pas rouvrir sans l'auteur)

- **Réécriture Rust/C du moteur d'extraction : rejetée** (fausse bonne idée).
  pdf2htmlEX produit le modèle HTML+CSS matriciel précis que tout le pipeline
  consomme ; le remplacer déplacerait le problème au lieu de le résoudre.
- **pdf2htmlEX 0.18.8.rc1 n'existe PAS en build Windows** (vérifié via l'API
  GitHub et le miroir SourceForge : assets Linux uniquement). Windows reste sur
  le binaire 0.14.6 (bundlé), Linux utilise l'AppImage officielle 0.18.8.rc1.
  Le levier vitesse côté Windows = conversion par tranches de pages, pas un
  changement de binaire.
- Accélération "pages spécifiques" : approche choisie = **tranches** (découpe
  pypdf de la plage demandée, conversion de la tranche, remappage d'offset).
  Implémentation différée jusqu'à validation du feedback UI par l'auteur.

## Pièges connus (à ne pas casser)

- Le binaire pdf2htmlEX 0.14.6 (Windows) **n'accepte pas les chemins de sortie
  absolus** (il préfixe `./`) : toujours passer un nom de sortie relatif au cwd.
  Voir `convert_pdf_to_html` dans `core/html_transformer.py`.
- `convert_pdf_to_html` a un **watchdog d'inactivité** (30 s par défaut) : ne pas
  le remplacer par un timeout total (les gros PDFs convertissent pendant des minutes
  de façon légitime).
- L'ouverture d'un document est **lazy** : pas de pdf2htmlEX à l'ouverture, la
  préparation se fait à la première traduction et est mise en cache par hash
  SHA-256 du contenu dans `%LOCALAPPDATA%/RockTranslate/cache/<hash>/`.

## Tests

- Tests headless dans `dev_tools/` :
  - `test_convert_robustness.py` : progression + watchdog de conversion (P1).
  - `test_lazy_pipeline.py` : pipeline lazy de bout en bout avec LLM stubbé (P2).
  - `test_lazy_pipeline.py` utilise `Tankeu et al. 2026.pdf` (PDF complexe de
    référence, 40 pages / 88 Mo) — ne pas le supprimer.
- Ne jamais lancer de vrais appels LLM sans l'accord de l'auteur (coût API) :
  stubber `LLMClient` comme dans `test_lazy_pipeline.py`.

## Communication

- L'auteur parle français : répondre en français, code et commentaires en anglais.
- L'auteur est le décideur produit ; proposer, expliquer les arbitrages, puis
  exécuter. Les gros chantiers sont découpés en phases (P1…Pn) validées une à une.
