/**
 * RockTranslate — Top Menu Bar Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/menubar.js
 * 
 * Controls dropdown visibility states, click-outside closures,
 * and handles professional desktop hover-to-switch menu active behaviors.
 * Refactored to standard ES6 to guarantee compatibility with all WebViews.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.2
 */

function menubarController() {
    return {
        // Track the active open menu category name (e.g. 'file', 'trans', 'view', etc.)
        activeMenu: null,

        // Recent history files list loaded dynamically
        recentFiles: [],

        // Active AI Model and provider info for the top-right indicator
        apiState: {
            active: false,
            provider: 'Google Gemini',
            model: 'gemini-3.1-flash-lite'
        },

        // --- CHECKABLE STATES (PyQt Default States) ---
        targetLang: 'French',
        showProgressPanel: true,
        isFullscreen: false,
        layoutMode: 'both', // 'both', 'pdf_only', 'trans_only'

        init() {
            // Fetch initial recent files and API status
            if (window.pywebview && window.pywebview.api) {
                this.loadMenuData();
            } else {
                window.addEventListener('pywebviewready', () => this.loadMenuData());
            }

            // Clean list when history gets updated
            window.addEventListener('refresh-menu-data', () => this.loadMenuData());

            // ── CLOSE MENUS ON IFRAME CLICKS LISTENER ──
            window.addEventListener('trigger-close-all-menus', () => this.closeAll());
        },


        async loadMenuData() {
            try {
                // Read recent files
                const files = await window.pywebview.api.get_recent_files();
                this.recentFiles = files || [];

                // Read API status
                const status = await window.pywebview.api.get_api_status();
                if (status) {
                    this.apiState = status;
                }
            } catch (e) {
                console.error("[Menubar] Error reading menu values:", e);
            }
        },

        /**
         * First click opens the target menu and activates menu hover-switching mode.
         */
        toggleMenu(menuName) {
            this.activeMenu = this.activeMenu === menuName ? null : menuName;
        },

        /**
         * ── NATIVE DESKTOP UX HOVER-TO-SWITCH ──
         * If a menu dropdown is already active on the screen, hovering over 
         * another top-level item switches the open dropdown instantly.
         */
        hoverMenu(menuName) {
            if (this.activeMenu !== null) {
                this.activeMenu = menuName;
            }
        },

        closeAll() {
            this.activeMenu = null;
        },

        isDocumentLoaded() {
            return this.$data.activeFilePath !== null;
        },

        getModelIndicatorText() {
            return Alpine.store('i18n').translate('model_indicator_prefix', {
                provider: this.apiState.provider,
                model: this.apiState.model
            });
        },

        // --- OPTION SELECTORS ---
        setTargetLanguage(lang) {
            this.targetLang = lang;
            this.closeAll();
            this.$dispatch('trigger-target-lang-change', { language: lang });
        },

        setAppLanguage(code) {
            Alpine.store('i18n').setLocale(code);
            this.closeAll();
            if (window.pywebview.api && window.pywebview.api.set_system_locale) {
                window.pywebview.api.set_system_locale(code);
            }
        },

        toggleProgressPanel() {
            this.showProgressPanel = !this.showProgressPanel;
            this.closeAll();
            this.$dispatch('trigger-toggle-progress', { visible: this.showProgressPanel });
        },

        toggleFullscreen() {
            this.isFullscreen = !this.isFullscreen;
            this.closeAll();
            if (window.pywebview && window.pywebview.api && window.pywebview.api.toggle_fullscreen) {
                window.pywebview.api.toggle_fullscreen();
            }
        },

        setLayoutMode(mode) {
            this.layoutMode = mode;
            this.closeAll();
            this.$dispatch('trigger-layout-change', { mode: mode });
        },

        async clearHistory() {
            this.closeAll();
            if (confirm("Are you sure you want to clear the recent files list?")) {
                if (window.pywebview.api && window.pywebview.api.clear_recent_history) {
                    await window.pywebview.api.clear_recent_history();
                }
                this.loadMenuData();
            }
        },

        triggerAction(actionName) {
            this.closeAll();

            if (actionName === 'show-about') {
                Alpine.store('modals').open('about');
            } else if (actionName === 'show-api-config') {
                Alpine.store('modals').open('api_config');
            } else if (actionName === 'show-trans-settings') {
                Alpine.store('modals').open('trans_settings');
            } else if (actionName === 'show-system-settings') {
                Alpine.store('modals').open('system_settings');
            } else if (actionName === 'toggle-translation-range') {
                // Directly open the range settings modal
                Alpine.store('modals').open('range_settings');
            } else if (actionName === 'open-pdf') {
                this.$dispatch('trigger-file-picker');
            } else if (actionName === 'close-doc') {
                this.$dispatch('trigger-close-document');
            } else if (actionName === 'export-pdf') {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.export_translated_pdf) {
                    window.pywebview.api.export_translated_pdf();
                }
            } else if (actionName === 'zoom-in') {
                this.$dispatch('trigger-zoom-in');
            } else if (actionName === 'zoom-out') {
                this.$dispatch('trigger-zoom-out');
            } else if (actionName === 'zoom-reset') {
                this.$dispatch('trigger-zoom-reset');
            } else {
                this.$dispatch(`trigger-${actionName}`);
            }
        }
    };
}