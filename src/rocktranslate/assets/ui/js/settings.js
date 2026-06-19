/**
 * RockTranslate — Settings Modals Alpine.js Controllers
 * Path: src/rocktranslate/assets/ui/js/settings.js
 * 
 * Drives loading, saving, and native directory browsing routines.
 * Refactored to standard ES6 to guarantee compatibility with all WebViews.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.3
 */

function systemSettingsController() {
    return {
        fields: {
            clear_cache_on_exit: false,
            pdf2htmlex_path_override: '',
            pdfjs_path_override: ''
        },

        init() {
            const load = () => this.loadSettings();
            if (window.pywebview && window.pywebview.api) {
                load();
            } else {
                window.addEventListener('pywebviewready', load);
                window.addEventListener('python-api-ready', load);
            }
        },

        async loadSettings() {
            try {
                const data = await window.pywebview.api.get_system_settings();
                if (data) {
                    this.fields = data;
                }
            } catch (error) {
                console.error("[Settings] Error loading system configs:", error);
            }
        },

        async save() {
            const i18n = Alpine.store('i18n');
            try {
                const response = await window.pywebview.api.save_system_settings(this.fields);
                if (response && response.status === 'success') {
                    window.showToast(i18n.translate('save_success_msg'), 'success');
                    Alpine.store('modals').close();
                } else {
                    const errMsg = (response && response.message) ? response.message : i18n.translate('save_error_msg');
                    window.showToast(errMsg, 'error');
                }
            } catch (error) {
                console.error("[Settings] Error saving system configs:", error);
                window.showToast(i18n.translate('save_error_msg'), 'error');
            }
        },

        async browsePdf2html() {
            try {
                const result = await window.pywebview.api.browse_binary_dialog();
                if (result && result.status === 'success') {
                    this.fields.pdf2htmlex_path_override = result.path;
                }
            } catch (error) {
                console.error("[Settings] Error browsing pdf2htmlEX binary:", error);
            }
        },

        async browsePdfjs() {
            try {
                const result = await window.pywebview.api.browse_folder_dialog();
                if (result && result.status === 'success') {
                    this.fields.pdfjs_path_override = result.path;
                }
            } catch (error) {
                console.error("[Settings] Error browsing PDF.js folder:", error);
            }
        }
    };
}

function translationSettingsController() {
    return {
        fields: {
            temperature: 1.0,
            sliding_context_size: 5,
            max_segments_per_batch: 60,
            threshold_px: 12.0,
            max_retries: 4,
            custom_glossary: ''
        },

        init() {
            const load = () => this.loadSettings();
            if (window.pywebview && window.pywebview.api) {
                load();
            } else {
                window.addEventListener('pywebviewready', load);
                window.addEventListener('python-api-ready', load);
            }
        },

        async loadSettings() {
            try {
                const data = await window.pywebview.api.get_translation_settings();
                if (data) {
                    this.fields = data;
                }
            } catch (error) {
                console.error("[Settings] Error loading translation configs:", error);
            }
        },

        async save() {
            const i18n = Alpine.store('i18n');
            try {
                const response = await window.pywebview.api.save_translation_settings(this.fields);
                if (response && response.status === 'success') {
                    window.showToast(i18n.translate('save_success_msg'), 'success');
                    Alpine.store('modals').close();
                } else {
                    const errMsg = (response && response.message) ? response.message : i18n.translate('save_error_msg');
                    window.showToast(errMsg, 'error');
                }
            } catch (error) {
                console.error("[Settings] Error saving translation configs:", error);
                window.showToast(i18n.translate('save_error_msg'), 'error');
            }
        }
    };
}
function apiConfigController() {
    return {
        // Exposes your raw constants.py DEFAULT_PROVIDERS mapping
        providersConfig: {},

        // Current active provider selection
        currentProvider: 'Google Gemini',

        // Structure holding configurations in isolation for each provider
        isolatedConfigs: {},

        // Toggle to show green checkmark success feedbacks
        showSuccessLabel: false,

        // ── TIMING FIX: State marker to prevent uninitialized rendering clashes ──
        loading: true,

        init() {
            const load = () => this.loadConfig();
            if (window.pywebview && window.pywebview.api) {
                load();
            } else {
                window.addEventListener('pywebviewready', load);
                window.addEventListener('python-api-ready', load);
            }
        },

        async loadConfig() {
            try {
                this.loading = true; // Start loading state

                // Fetch dynamic providers details from constants.py
                this.providersConfig = await window.pywebview.api.get_providers_config();

                // Fetch current user database keys
                const data = await window.pywebview.api.get_api_config();
                if (data) {
                    this.isolatedConfigs = data.isolated_configs;

                    // 1. Terminate loading state first to let Alpine write the option tags to the DOM
                    this.loading = false;

                    // 2. Pause execution until the browser has fully completed its DOM rendering tick
                    await this.$nextTick();

                    // 3. Now that the options are physically present, safely set the active provider
                    this.currentProvider = data.current_provider;
                } else {
                    this.loading = false;
                }
            } catch (error) {
                console.error("[API Config] Error loading profiles:", error);
                this.loading = false;
            }
        },

        /**
         * Resolves the list of suggested models for the active selection.
         */
        getSuggestedModels() {
            if (this.providersConfig && this.providersConfig[this.currentProvider]) {
                return this.providersConfig[this.currentProvider].models || [];
            }
            return [];
        },

        /**
        * Clears the API Key for the active provider with confirmation safety logic.
        */
        async deleteKey() {
            const i18n = Alpine.store('i18n');
            const confirmed = await Alpine.store('dialogs').confirm(i18n.translate('delete_key_confirm_msg'));
            if (confirmed) {
                if (this.isolatedConfigs[this.currentProvider]) {
                    this.isolatedConfigs[this.currentProvider].api_key = '';
                    this.showSuccessLabel = true;
                    setTimeout(() => this.showSuccessLabel = false, 3000);
                }
            }
        },

        /**
         * Saves credentials and variables to the persistent JSON database.
         */
        async save() {
            const i18n = Alpine.store('i18n');
            try {
                const payload = {
                    current_provider: this.currentProvider,
                    isolated_configs: this.isolatedConfigs
                };

                const response = await window.pywebview.api.save_api_config(payload);
                if (response && response.status === 'success') {
                    window.showToast(i18n.translate('save_success_msg'), 'success');

                    // Fire refresh to update main dashboard and menubar statuses immediately
                    window.dispatchEvent(new CustomEvent('refresh-menu-data'));
                    window.dispatchEvent(new CustomEvent('pywebviewready')); // Force dashboard status refresh

                    Alpine.store('modals').close();
                } else {
                    const errMsg = (response && response.message) ? response.message : i18n.translate('save_error_msg');
                    window.showToast(errMsg, 'error');
                }
            } catch (error) {
                console.error("[API Config] Save execution failure:", error);
                window.showToast(i18n.translate('save_error_msg'), 'error');
            }
        }
    };

}

/**
* Controller managing target page range translations.
*/
function rangeSettingsController() {
    return {
        // User typed page range string (e.g., "2-4, 7")
        pageRange: '',

        // Physical page boundaries count of the active PDF
        totalPages: 1,

        init() {
            const load = () => this.loadTotalPages();
            if (window.pywebview && window.pywebview.api) {
                load();
            } else {
                window.addEventListener('pywebviewready', load);
                window.addEventListener('python-api-ready', load);
            }
            window.addEventListener('refresh-menu-data', load);
        },

        async loadTotalPages() {
            try {
                if (window.pywebview.api && window.pywebview.api.get_total_pages) {
                    const count = await window.pywebview.api.get_total_pages();
                    if (count) {
                        this.totalPages = count;
                    }
                }
            } catch (error) {
                console.error("[Range Settings] Error loading pages count:", error);
            }
        },

        /**
         * Closes the modal and dispatches range values to the translation pipeline.
         */
        submit() {
            const i18n = Alpine.store('i18n');
            const rangeStr = this.pageRange.trim();
            if (!rangeStr) {
                window.showToast(i18n.translate('invalid_range_msg'), 'warning');
                return;
            }

            // Dispatch event to appShell to initiate worker thread ranges slicing
            this.$dispatch('trigger-translation-range-execute', { range: rangeStr });

            Alpine.store('modals').close();
            this.pageRange = ''; // Clean input
        }
    };
}



/**
 * Controller managing document properties and metadata sheets.
 */
function propertiesController() {
    return {
        // Formatted metadata object returned by python
        metadata: {},

        // Active tab viewport pane ('general', 'description', 'rocktranslate')
        activeTab: 'general',

        loading: true,

        init() {
            // Re-fetch fresh metadata every time the properties modal gets triggered
            window.addEventListener('trigger-show-properties', () => this.loadProperties());
        },

        async loadProperties() {
            try {
                this.loading = true;
                this.activeTab = 'general';

                // Grab active document file path from the parent appShell scope
                const filePath = this.$data.activeFilePath;
                if (filePath) {
                    const data = await window.pywebview.api.get_document_properties(filePath);
                    if (data) {
                        this.metadata = data;
                    }
                }
                this.loading = false;
            } catch (error) {
                console.error("[Properties] Error fetching metadata sheets:", error);
                this.loading = false;
            }
        }
    };
}

/**
 * Controller for the About modal's easter egg signature panel.
 *
 * Root cause of the original bug: this function used to live inside an
 * inline <script> tag inside about_modal.html. That fragment is injected
 * dynamically (fetch + innerHTML), and browsers never execute <script>
 * tags inserted that way — so aboutController() never registered in the
 * global scope, and Alpine threw "triggerEasterEgg is not defined" the
 * moment the name was clicked.
 *
 * Moved here, next to the other controllers in this file that are already
 * confirmed to load correctly (e.g. apiConfigController), so it registers
 * at startup before Alpine scans the DOM for x-data="aboutController()".
 */
function aboutController() {
    return {
        clickCount: 0,
        lastClickTime: 0,
        easterEggActive: false,

        // Triggers the secret verification panel after 5 rapid consecutive clicks
        triggerEasterEgg() {
            const now = Date.now();
            if (now - this.lastClickTime < 800) {
                this.clickCount++;
            } else {
                this.clickCount = 1;
            }
            this.lastClickTime = now;

            if (this.clickCount >= 5) {
                this.easterEggActive = true;
                this.clickCount = 0; // reset counter
            }
        }
    };
}