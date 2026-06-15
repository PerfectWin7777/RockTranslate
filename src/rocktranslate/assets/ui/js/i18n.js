/**
 * RockTranslate — Reactive UI Internationalization Store
 * Path: src/rocktranslate/assets/ui/js/i18n.js
 * 
 * Manages translation dictionaries and reactive locale switching using Alpine.js.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.0
 */

document.addEventListener('alpine:init', () => {
    Alpine.store('i18n', {
        locale: 'en',

        translations: {
            en: {
                // Top-level menu headers
                menu_file: "File",
                menu_translation: "Translation",
                menu_view: "View",
                menu_settings: "Settings",
                menu_help: "Help",

                // File Menu items
                item_open: "Open PDF...",
                item_close: "Close Document",
                item_export: "Export Translated PDF...",
                item_properties: "Document Properties...",
                item_recent: "Recent Files",
                item_clear_history: "Clear History",
                item_no_recent: "No recent documents found",
                item_quit: "Quit",

                // Translation Menu items
                item_start_trans: "Start Translation",
                item_stop_trans: 'Stop Translation',
                item_trans_range: "Translate Specific Pages...",
                item_api_config: "API & Model Configuration...",
                item_target_lang: "Target Language",

                // View Menu items
                item_zoom_in: "Zoom In",
                item_zoom_out: "Zoom Out",
                item_zoom_reset: "Zoom 100%",
                item_show_progress: "Show Progress Panel",
                item_fullscreen: "Full Screen",
                item_layout_both: "Show Dual Split View",
                item_layout_pdf: "Show Original PDF Only",
                item_layout_trans: "Show Translation Only",

                // Settings Menu items
                item_trans_engine: "Translation Engine...",
                item_system_settings: "System & Cache...",
                item_app_lang: "Application Language",
                item_reset_settings: "Reset Settings to Default",

                // Help Menu items
                item_about: "About RockTranslate...",
                item_website: "Official Website",
                item_github: "Source Code (GitHub)",
                item_issues: "Report an Issue",

                // Active Model Indicator
                model_indicator_prefix: "AI MODEL ACTIVE   |   🤖 {provider}: {model}",

                // Common Dashboard components
                drag_drop_title: "Drag & Drop your scientific PDF here",
                open_file_btn: "Open File...",
                recent_docs_title: "Recent Documents",
                no_recent_docs: "No recent documents found.",
                api_active_local: "● Local Mode Active (Ollama: {model})",
                api_active_remote: "● AI Active: {provider} ({model})",
                api_setup_required: "○ Setup Required: Missing API key for {provider}",
                waiting_translation: "Waiting for translation...",

                // 
                about_title: "About RockTranslate",
                about_version: "RockTranslate v1.0.0",
                about_tagline: "Scientific PDF Translation Engine",
                about_motto: "Preserving Layout. Translating Knowledge.",
                about_desc_1: "RockTranslate is a desktop application designed for translating scientific, technical, and academic PDF documents while preserving their original structure, formatting, figures, tables, and visual layout.",
                about_desc_2: "Built with a local-first architecture, RockTranslate prioritizes performance, reliability, and user control. The application combines advanced document analysis, intelligent translation workflows, and high-fidelity PDF reconstruction to deliver professional-quality results.",
                about_feature_1: "Layout-Preserved PDF Translation",
                about_feature_2: "Scientific and Technical Document Support",
                about_feature_3: "High-Fidelity PDF Reconstruction",
                about_feature_4: "Fast Desktop Performance",
                about_feature_5: "Lightweight and Responsive User Experience",
                about_feature_6: "Privacy-Conscious Workflow",
                about_feature_7: "Open-Source and Community-Driven",
                about_license: "License",
                about_authors: "Authors",
                close_btn: "Close",

                status_ready: "Ready. Open or drag a PDF document to begin.",


                system_settings_title: "System & Cache Settings",
                system_cache_lifecycle: "Cache Lifecycle",
                system_clear_cache_chk: "Automatically clear temporary workspace files on exit",
                system_clear_cache_tip: "If checked, generated HTML workspace files will be deleted when closing documents.",
                system_pdf2html_lbl: "pdf2htmlEX Binary Override",
                system_pdf2html_tip: "Leave empty to use the auto-detected standard precompiled binaries.",
                system_pdfjs_lbl: "PDF.js Folder Override",
                system_browse_btn: "Browse...",
                system_info_disclosure: "Leave the executable paths empty to allow RockTranslate to automatically use default precompiled system binaries.",

                trans_settings_title: "Translation Engine Settings",
                trans_temp_lbl: "Model Temperature",
                trans_temp_tip: "Controls the randomness of the translation output (lower is more deterministic and consistent).",
                trans_context_lbl: "Sliding Context Depth",
                trans_context_tip: "Number of previous paragraphs kept in memory for contextual consistency.",
                trans_batch_lbl: "Max Segments Per Batch",
                trans_batch_tip: "Maximum number of text elements processed in a single API concurrent request.",
                trans_threshold_lbl: "Table Column Split Threshold (px)",
                trans_threshold_tip: "Horizontal distance (pixels) beyond which adjacent text nodes are split into separate columns.",
                trans_retries_lbl: "Max Connection Retries",
                trans_retries_tip: "Maximum number of reconnection attempts before marking a batch request as failed.",
                trans_info_disclosure: "These settings directly impact translation visual grouping and API context costs. Tweak with care.",

                save_btn: "Save",
                cancel_btn: "Cancel",
                reset_confirm_msg: "Are you sure you want to reset all configurations to their defaults?",
                reset_success_msg: "All workflow configurations have been reset successfully.",
                save_success_msg: "Settings saved successfully.",


                api_info_disclosure: "This key is stored locally and only used to make secure, direct API requests from this application.",

                api_config_provider_lbl: "API Provider",
                lbl_key: "API Key",
                chk_custom_base: "Use custom base URL",
                system_pdf2html_lbl_url: "Custom Base URL",
                system_model_lbl: "Model",

                range_title: "Translate Specific Pages",
                range_subtitle_total: "Translate Specific Pages (Total Pages: {total})",
                range_syntax_guide: "Syntax Guide",
                range_guide_1: "Enter a single page number (e.g., '4') to translate only that page.",
                range_guide_2: "Use '-' for a sequential range of pages (e.g., '2-5' translates pages 2, 3, 4, and 5).",
                range_guide_3: "Use ',' to separate distinct pages or ranges (e.g., '1, 3, 5' translates pages 1, 3, and 5).",
                range_guide_4: "Combine both formats (e.g., '2-4, 7, 9' translates pages 2, 3, 4, 7, and 9).",
                range_warning: "Pages out-of-bounds (e.g., page 12 on a 10-page document) will be skipped.",
                range_input_placeholder: "e.g., 2-4, 7, 9",
                translate_btn: "Translate",


                prop_tab_general: "General",
                prop_tab_description: "Description",
                prop_tab_custom: "RockTranslate 💎",
                prop_file: "File:",
                prop_size: "File Size:",
                prop_pages: "Pages:",
                prop_version: "PDF Version:",
                prop_linearized: "Fast Web View (Linearized):",
                prop_tagged: "Tagged PDF:",
                prop_page_size: "Page Size:",
                prop_title: "Title:",
                prop_subject: "Subject:",
                prop_author: "Author:",
                prop_creator: "Creator:",
                prop_producer: "Producer:",
                prop_keywords: "Keywords:",
                prop_created: "Created on:",
                prop_modified: "Modified on:",
                prop_status: "Translation Status:",
                prop_ai_model: "AI Model Used:",
                prop_blocks: "Semantic Blocks Translated:",
                prop_avg_scale: "Average Layout Scale (scaleX):",
                prop_date: "Translation Date:",

                doc_loaded_msg: "Document loaded: {filename} ({pages} pages, {segments} text segments mapped)",

                prop_pages_progress: "Document progress: {done} / {total} pages translated",
                prop_segments_progress: "Local progress: {done} / {total} segments translated",
                batch_info_msg: "Batch {done}/{total}",
                speed_info_msg: "{speed} seg/sec",
                range_duration_mins_secs: "~{mins}m {secs}s",
                range_duration_secs: "~{secs}s",
                finished_status: "Finished ✓",
                calc_status: "Calculating...",

                delete_key_confirm_msg: "Are you sure you want to delete this API key?",
                quit_confirm_msg: "Are you sure you want to quit RockTranslate?",
                close_doc_confirm_msg: "Are you sure you want to close the active document?",
                invalid_range_msg: "Please enter a valid page range.",
                clear_history_confirm_msg: "Are you sure you want to clear the recent files list?",
                save_error_msg: "An error occurred while saving settings.",


                status_extraction_start: "High-fidelity PDF conversion in progress...",
                status_extraction_pages: "Analyzing Document layout: Page {current}/{total}...",
                status_extraction_failed: "Geometric conversion by pdf2htmlEX failed.",
                status_extraction_instrumenting: "Analyzing and instrumenting document...",
                status_extraction_success: "Workspace configured successfully.",
                status_extraction_error: "Extraction Error: {error}",
                toast_extraction_error: "Could not parse target document: {error}",

                status_trans_init: "Initializing AI Translator...",
                toast_trans_missing_key: "Missing API Key for {provider}. Please configure it in API Settings.",
                status_trans_building_batches: "Building translation batches...",
                status_trans_no_text: "No text to translate was found.",
                status_trans_batch_progress: "Translating batch {current}/{total}...",
                status_trans_completed: "Document translation completed successfully.",
                toast_trans_success: "Document translation succeeded!",
                status_trans_error: "Translation Error: {error}",
                toast_trans_error: "Translation failed: {error}",

                toast_export_no_doc: "No active document loaded to export.",
                status_export_requesting_layout: "Requesting document layout from workspace...",
                toast_export_failed_extract: "Failed to extract active layout from the viewport.",
                status_export_waiting_path: "Waiting for file destination path...",
                status_export_cancelled: "Export cancelled by user.",
                status_export_generating_pdf: "Generating final vector PDF...",
                toast_export_no_chromium: "No compatible Chromium engine found. Export aborted.",
                status_export_success: "File exported successfully: {filename}",
                toast_export_success: "Document exported successfully!",
                toast_export_failed: "PDF generation failed.",
                status_export_failed: "Export failed.",
                toast_export_error: "Export failed: {error}",




            },
            fr: {
                // Top-level menu headers
                menu_file: "Fichier",
                menu_translation: "Traduction",
                menu_view: "Affichage",
                menu_settings: "Paramètres",
                menu_help: "Aide",

                // File Menu items
                item_open: "Ouvrir un PDF...",
                item_close: "Fermer le document",
                item_export: "Exporter le PDF traduit...",
                item_properties: "Propriétés du document...",
                item_recent: "Fichiers récents",
                item_clear_history: "Effacer l'historique",
                item_no_recent: "Aucun document récent",
                item_quit: "Quitter",

                // Translation Menu items
                item_start_trans: "Démarrer la traduction",
                item_stop_trans: "Arreter la traduction",
                item_trans_range: "Traduire des pages spécifiques...",
                item_api_config: "Configuration de l'API & des modèles...",
                item_target_lang: "Langue cible",

                // View Menu items
                item_zoom_in: "Zoom avant",
                item_zoom_out: "Zoom arrière",
                item_zoom_reset: "Zoom 100%",
                item_show_progress: "Afficher le panneau de progression",
                item_fullscreen: "Plein écran",
                item_layout_both: "Afficher la vue double divisée",
                item_layout_pdf: "Afficher le PDF original uniquement",
                item_layout_trans: "Afficher la traduction uniquement",

                // Settings Menu items
                item_trans_engine: "Moteur de traduction...",
                item_system_settings: "Système & Cache...",
                item_app_lang: "Langue de l'application",
                item_reset_settings: "Réinitialiser les paramètres par défaut",

                // Help Menu items
                item_about: "À propos de RockTranslate...",
                item_website: "Site officiel",
                item_github: "Code source (GitHub)",
                item_issues: "Signaler un problème",

                // Active Model Indicator
                model_indicator_prefix: "MODÈLE D'IA ACTIF   |   🤖 {provider} : {model}",

                // Common Dashboard components
                drag_drop_title: "Glissez & Déposez votre PDF scientifique ici",
                open_file_btn: "Ouvrir un fichier...",
                recent_docs_title: "Documents Récents",
                no_recent_docs: "Aucun document récent trouvé.",
                api_active_local: "● Mode local actif (Ollama : {model})",
                api_active_remote: "● IA active : {provider} ({model})",
                api_setup_required: "○ Configuration requise : Clé API manquante pour {provider}",
                waiting_translation: "En attente de traduction...",

                about_title: "À propos de RockTranslate",
                about_version: "RockTranslate v1.0.0",
                about_tagline: "Moteur de traduction de PDF scientifiques",
                about_motto: "Préserver la mise en page. Traduire le savoir.",
                about_desc_1: "RockTranslate est une application de bureau conçue pour traduire des documents PDF scientifiques, techniques et académiques tout en préservant leur structure d'origine, leur formatage, leurs figures, leurs tableaux et leur mise en page visuelle.",
                about_desc_2: "Conçu avec une architecture locale-first, RockTranslate donne la priorité aux performances, à la fiabilité et au contrôle de l'utilisateur. L'application combine une analyse avancée des documents, des flux de traduction intelligents et une reconstruction PDF haute fidélité pour fournir des résultats de qualité professionnelle.",
                about_feature_1: "Traduction de PDF avec préservation de la mise en page",
                about_feature_2: "Prise en charge des documents scientifiques et techniques",
                about_feature_3: "Reconstruction PDF haute fidélité",
                about_feature_4: "Performances de bureau rapides",
                about_feature_5: "Expérience utilisateur légère et réactive",
                about_feature_6: "Flux de travail respectueux de la vie privée",
                about_feature_7: "Open-Source et orienté communauté",
                about_license: "Licence",
                about_authors: "Auteurs",
                close_btn: "Fermer",

                status_ready: "Prêt. Ouvrez ou glissez un document PDF pour commencer.",


                system_settings_title: "Paramètres Système & Cache",
                system_cache_lifecycle: "Cycle de vie du cache",
                system_clear_cache_chk: "Nettoyer automatiquement les fichiers temporaires à la fermeture",
                system_clear_cache_tip: "Si coché, les fichiers HTML de l'espace de travail générés seront supprimés à la fermeture du document.",
                system_pdf2html_lbl: "Surcharge du binaire pdf2htmlEX",
                system_pdf2html_tip: "Laissez vide pour utiliser les binaires précompilés détectés automatiquement.",
                system_pdfjs_lbl: "Surcharge du dossier PDF.js",
                system_browse_btn: "Parcourir...",
                system_info_disclosure: "Laissez ces champs vides pour permettre à RockTranslate d'utiliser automatiquement ses binaires intégrés par défaut.",

                trans_settings_title: "Paramètres du Moteur de Traduction",
                trans_temp_lbl: "Température du Modèle",
                trans_temp_tip: "Contrôle la créativité du modèle d'IA (une valeur basse rend les traductions plus cohérentes et précises).",
                trans_context_lbl: "Profondeur du Contexte Glissant",
                trans_context_tip: "Nombre de paragraphes précédents conservés en mémoire pour garantir la cohérence stylistique.",
                trans_batch_lbl: "Segments Max par Lot",
                trans_batch_tip: "Nombre maximum d'éléments de texte envoyés simultanément dans une seule requête d'API.",
                trans_threshold_lbl: "Seuil de Séparation des Colonnes (px)",
                trans_threshold_tip: "Distance horizontale (en pixels) au-delà de laquelle deux blocs de texte adjacents sont séparés en colonnes distinctes.",
                trans_retries_lbl: "Tentatives de Connexion Max",
                trans_retries_tip: "Nombre maximal de tentatives de reconnexion au réseau avant de marquer un lot de requêtes comme échoué.",
                trans_info_disclosure: "Ces paramètres impactent directement le groupement visuel de la traduction et les coûts de jetons API. Modifiez-les avec prudence.",

                save_btn: "Enregistrer",
                cancel_btn: "Annuler",
                reset_confirm_msg: "Êtes-vous sûr de vouloir réinitialiser toutes les configurations par défaut ?",
                reset_success_msg: "Toutes les configurations de traitement ont été réinitialisées avec succès.",
                save_success_msg: "Paramètres enregistrés avec succès.",

                api_info_disclosure: "Cette clé est stockée localement et uniquement utilisée pour effectuer des requêtes API sécurisées et directes depuis cette application.",
                
                api_config_provider_lbl: "Fournisseur d'API",
                lbl_key: "Clé API",
                chk_custom_base: "Utiliser une URL de base personnalisée",
                system_pdf2html_lbl_url: "URL de base personnalisée",
                system_model_lbl: "Modèle",

                range_title: "Traduire des Pages Spécifiques",
                range_subtitle_total: "Traduire des Pages Spécifiques (Total Pages : {total})",
                range_syntax_guide: "Guide de Syntaxe",
                range_guide_1: "Entrez un seul numéro de page (ex. '4') pour traduire uniquement cette page.",
                range_guide_2: "Utilisez '-' pour une plage de pages séquentielle (ex. '2-5' traduit les pages 2, 3, 4 et 5).",
                range_guide_3: "Utilisez ',' pour séparer des pages ou plages distinctes (ex. '1, 3, 5' traduit les pages 1, 3 et 5).",
                range_guide_4: "Combinez les deux formats (ex. '2-4, 7, 9' traduit les pages 2, 3, 4, 7 et 9).",
                range_warning: "Les pages hors limites (ex. page 12 sur un document de 10 pages) seront ignorées.",
                range_input_placeholder: "ex. 2-4, 7, 9",
                translate_btn: "Traduire",

                prop_tab_general: "Général",
                prop_tab_description: "Description",
                prop_tab_custom: "RockTranslate 💎",
                prop_file: "Fichier :",
                prop_size: "Taille du fichier :",
                prop_pages: "Pages :",
                prop_version: "Version PDF :",
                prop_linearized: "Affichage Web rapide (Linéarisé) :",
                prop_tagged: "PDF balisé :",
                prop_page_size: "Taille de page :",
                prop_title: "Titre :",
                prop_subject: "Sujet :",
                prop_author: "Auteur :",
                prop_creator: "Créateur :",
                prop_producer: "Producteur :",
                prop_keywords: "Mots-clés :",
                prop_created: "Créé le :",
                prop_modified: "Modifié le :",
                prop_status: "Statut de traduction :",
                prop_ai_model: "Modèle d'IA utilisé :",
                prop_blocks: "Blocs sémantiques traduits :",
                prop_avg_scale: "Échelle moyenne de mise en page (scaleX) :",
                prop_date: "Date de traduction :",

                doc_loaded_msg: "Document chargé : {filename} ({pages} pages, {segments} segments de texte mappés)",

                prop_pages_progress: "Progression du document : {done} / {total} pages traduites",
                prop_segments_progress: "Progression locale : {done} / {total} segments traduits",
                batch_info_msg: "Lot {done}/{total}",
                speed_info_msg: "{speed} seg/sec",
                range_duration_mins_secs: "~{mins}m {secs}s",
                range_duration_secs: "~{secs}s",
                finished_status: "Terminé ✓",
                calc_status: "Calcul en cours...",


                delete_key_confirm_msg: "Êtes-vous sûr de vouloir supprimer cette clé API ?",
                quit_confirm_msg: "Êtes-vous sûr de vouloir quitter RockTranslate ?",
                close_doc_confirm_msg: "Êtes-vous sûr de vouloir fermer le document actif ?",
                invalid_range_msg: "Veuillez saisir une plage de pages valide.",
                clear_history_confirm_msg: "Êtes-vous sûr de vouloir effacer la liste des fichiers récents ?",
                save_error_msg: "Une erreur est survenue lors de l'enregistrement des paramètres.",

                status_extraction_start: "Conversion haute fidélité du PDF en cours...",
                status_extraction_pages: "Analyse de la mise en page : Page {current}/{total}...",
                status_extraction_failed: "La conversion géométrique par pdf2htmlEX a échoué.",
                status_extraction_instrumenting: "Analyse et balisage du document en cours...",
                status_extraction_success: "Espace de travail configuré avec succès.",
                status_extraction_error: "Erreur d'extraction : {error}",
                toast_extraction_error: "Impossible d'analyser le document cible : {error}",

                status_trans_init: "Initialisation du traducteur IA...",
                toast_trans_missing_key: "Clé API manquante pour {provider}. Veuillez la configurer dans les paramètres API.",
                status_trans_building_batches: "Consolidation des lots de traduction...",
                status_trans_no_text: "Aucun texte à traduire n'a été trouvé.",
                status_trans_batch_progress: "Traduction du lot {current}/{total}...",
                status_trans_completed: "Traduction du document terminée avec succès.",
                toast_trans_success: "Traduction du document réussie !",
                status_trans_error: "Erreur de traduction : {error}",
                toast_trans_error: "La traduction a échoué : {error}",

                toast_export_no_doc: "Aucun document actif chargé à exporter.",
                status_export_requesting_layout: "Récupération de la mise en page depuis l'espace de travail...",
                toast_export_failed_extract: "Échec de l'extraction de la mise en page depuis la vue active.",
                status_export_waiting_path: "En attente du dossier d'enregistrement...",
                status_export_cancelled: "Exportation annulée par l'utilisateur.",
                status_export_generating_pdf: "Génération du PDF vectoriel final...",
                toast_export_no_chromium: "Aucun moteur Chromium compatible trouvé. Exportation abandonnée.",
                status_export_success: "Fichier exporté avec succès : {filename}",
                toast_export_success: "Document exporté avec succès !",
                toast_export_failed: "Échec de la génération du PDF.",
                status_export_failed: "Échec de l'exportation.",
                toast_export_error: "L'exportation a échoué : {error}",
             

            }
        },

        translate(key, variables = {}) {
            let text = this.translations[this.locale]?.[key] || this.translations['en']?.[key] || key;
            for (const [vKey, vVal] of Object.entries(variables)) {
                text = text.replace(`{${vKey}}`, vVal);
            }
            return text;
        },

        setLocale(localeCode) {
            if (this.translations[localeCode]) {
                this.locale = localeCode;
                console.log(`[i18n] Language switched to: ${localeCode}`);
            }
        }
    });
});