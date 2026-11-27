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
            model: 'gemini-3.5-flash-lite'
        },

        // --- CHECKABLE STATES  ---
        targetLang: 'French',
        showProgressPanel: true,
        // "Original text on hover" (off by default; Ctrl + hover always works)
        hoverOriginal: window.rtHoverOriginal === true,
        isFullscreen: false,
        layoutMode: 'both', // 'both', 'pdf_only', 'trans_only'
        // NOTE: translation running state lives in the central Alpine store
        // 'trans' (registered in index.html) — never keep a local copy here,
        // sibling components desync silently.

        init() {
            window.addEventListener('hover-original-changed', (e) => { this.hoverOriginal = !!(e.detail && e.detail.on); });
            window.addEventListener('trigger-toggle-progress', (e) => { if (e.detail) this.showProgressPanel = !!e.detail.visible; });
            // Fetch initial recent files and API status
           const load = () => this.loadMenuData();

            // Bypass initialization delays if pywebview is already fully injected
            rtBridge.whenReady(load);  // waits until every Python method is attached
            window.addEventListener('python-api-ready', load);  // explicit refresh requests

            // Clean list when history gets updated
            window.addEventListener('refresh-menu-data', load);

            // ── CLOSE MENUS ON IFRAME CLICKS LISTENER ──
            window.addEventListener('trigger-close-all-menus', () => this.closeAll());

            // ── GLOBAL KEYBOARD SHORTCUTS EXECUTOR ──
            window.addEventListener('execute-menu-action', (e) => {
                if (e.detail && e.detail.action) {
                    const act = e.detail.action;

                    // Route directly to correct visual toggle or layout settings
                    if (act === 'layout-both') {
                        this.setLayoutMode('both');
                    } else if (act === 'layout-pdf') {
                        this.setLayoutMode('pdf_only');
                    } else if (act === 'layout-trans') {
                        this.setLayoutMode('trans_only');
                    } else if (act === 'toggle-progress') {
                        this.toggleProgressPanel();
                    } else if (act === 'toggle-fullscreen') {
                        this.toggleFullscreen();
                    } else {
                        // Guard check: Some actions require an active document loaded to execute
                        const docRequired = ['export-pdf', 'export-pdf-direct', 'show-properties', 'toggle-translation', 'toggle-translation-range'];
                        if (docRequired.includes(act) && !this.isDocumentLoaded()) {
                            return; // Abort quietly if no document is loaded
                        }
                        this.triggerAction(act);
                    }
                }
            });
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

                // Load persisted target language from Python config
                const savedLang = await window.pywebview.api.get_target_language();
                if (savedLang) {
                    this.targetLang = savedLang;
                }
            } catch (e) {
                console.error("[Menubar] Error reading menu values:", e);
            }
        },

        loadRecentFile(filePath) {
            this.closeAll();
            if (window.pywebview && window.pywebview.api && window.pywebview.api.extract_pdf) {
                window.pywebview.api.extract_pdf(filePath);
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
            if (window.pywebview && window.pywebview.api) {
                window.pywebview.api.set_target_language(lang);
            }
        },

        setAppLanguage(code) {
            Alpine.store('i18n').setLocale(code);
            this.closeAll();
            if (window.pywebview.api && window.pywebview.api.set_system_locale) {
                window.pywebview.api.set_system_locale(code);
            }
        },

        async toggleHoverOriginal() {
            const next = !this.hoverOriginal;
            try {
                const api = window.pywebview && window.pywebview.api;
                const res = api && api.set_preference ? await api.set_preference('hover_original', next) : null;
                window.rtSetHoverOriginal(res && res.status === 'success' ? !!res.value : next);
            } catch (e) {
                window.rtSetHoverOriginal(next);
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

        /**
         * Clears recent documents history with a localized safety confirmation check.
         */
        async clearHistory() {
            this.closeAll();
            const i18n = Alpine.store('i18n');
            const confirmed = await Alpine.store('dialogs').confirm(i18n.translate('clear_history_confirm_msg'));
            if (confirmed) {
                if (window.pywebview.api && window.pywebview.api.clear_recent_history) {
                    await window.pywebview.api.clear_recent_history();
                }
                this.loadMenuData();
            }
        },

        /**
         * Requests confirmation and gracefully shuts down the PyWebview environment.
         */
        async quitApplication() {
            this.closeAll();
            const i18n = Alpine.store('i18n');
            const confirmed = await Alpine.store('dialogs').confirm(i18n.translate('quit_confirm_msg'));
            if (confirmed) {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.quit_application) {
                    window.pywebview.api.quit_application();
                }
            }
        },


        triggerAction(actionName) {
            this.closeAll();

            if (actionName === 'clear-cache') {
                (async () => {
                    const i18n = Alpine.store('i18n');
                    const ok = await Alpine.store('dialogs').confirm(i18n.translate('clear_cache_confirm'), i18n.translate('item_clear_cache'));
                    if (!ok) return;
                    const res = await window.pywebview.api.clear_translation_cache(true);
                    if (res) window.showToast(i18n.translate('prefs_cache_cleared', { n: res.removed }), 'success');
                })();
                return;
            }
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
                // Default export: the machine's browser and its print dialog
                // (fast, GPU-accelerated); the headless export stays available
                if (window.pywebview && window.pywebview.api && window.pywebview.api.open_translated_in_browser) {
                    window.pywebview.api.open_translated_in_browser();
                }
            } else if (actionName === 'export-pdf-direct') {
                if (window.pywebview && window.pywebview.api && window.pywebview.api.export_translated_pdf) {
                    window.pywebview.api.export_translated_pdf();
                }
            } else if (actionName === 'zoom-in') {
                this.$dispatch('trigger-zoom-in');
                this.closeAll();
            } else if (actionName === 'zoom-out') {
                this.$dispatch('trigger-zoom-out');
                this.closeAll();
            } else if (actionName === 'zoom-reset') {
                this.$dispatch('trigger-zoom-reset');
                this.closeAll();
            } else {
                this.$dispatch(`trigger-${actionName}`);
                this.closeAll();
            }
        }
    };
}
/**
 * Menu icons: one table, i18n label key -> Lucide icon (js/icons.js).
 * Every menu entry whose label is translate('<key>') gets its icon before the
 * label, also for entries rendered later (templates, recent files).
 */
(function () {
    const MENU_ICONS = {
        item_open: 'folder-open', item_close: 'circle-x', item_export: 'file-down', item_export_direct: 'printer',
        item_properties: 'info', item_recent: 'history', item_clear_history: 'trash-2', item_quit: 'log-out',
        item_start_trans: 'languages', item_stop_trans: 'languages', item_trans_range: 'files',
        rd_translate_refs_menu: 'book-open', item_api_config: 'key-round', item_target_lang: 'globe',
        item_zoom_in: 'zoom-in', item_zoom_out: 'zoom-out', item_zoom_reset: 'scan', rd_panel: 'panel-right',
        item_show_progress: 'activity', item_hover_original: 'mouse-pointer-2', item_fullscreen: 'expand',
        item_theme_toggle: 'sun-moon', item_layout_both: 'columns-2', item_layout_pdf: 'file', item_layout_trans: 'type',
        rd_palette: 'command', rd_search_doc: 'search', rd_ask_doc: 'message-circle-question', rd_tab_glossary: 'book-a',
        rd_continuous: 'repeat', rd_night: 'moon', rd_snapshot: 'scan', rd_page_image: 'image',
        rd_trans_page_image: 'image-plus', rd_sbs: 'columns-2', rd_export_notes: 'notebook-pen', rd_open_link: 'link',
        rd_shortcuts: 'keyboard', prefs_menu_item: 'settings', item_trans_engine: 'sliders-horizontal',
        item_system_settings: 'monitor-cog', item_app_lang: 'languages', item_clear_cache: 'eraser',
        item_reset_settings: 'rotate-ccw', item_about: 'info', item_website: 'globe', item_github: 'git-branch',
        item_issues: 'bug', rd_export_tmx: 'file-output', rd_export_highlights: 'highlighter',
    };
    window.RT_MENU_ICONS = MENU_ICONS;

    function decorate(root) {
        (root.querySelectorAll ? root.querySelectorAll('.dropdown-item .dropdown-label') : []).forEach((label) => {
            if (label.querySelector('.dropdown-icon')) return;
            // The label is the element translated by key (toggles also have an x-text checkmark)
            const text = label.querySelector('[x-text*="translate(\'"]');
            const m = text && /translate\('([a-z_0-9]+)'\)/.exec(text.getAttribute('x-text') || '');
            const icon = m && MENU_ICONS[m[1]];
            if (!icon) return;
            const span = document.createElement('span');
            span.className = 'dropdown-icon';
            span.dataset.icon = icon;
            label.insertBefore(span, text);
        });
    }
    const start = () => {
        const bar = document.getElementById('menubar-container') || document.body;
        decorate(bar);
        let queued = false;          // at most one pass per frame, whatever the number of mutations
        new MutationObserver(() => {
            if (queued) return;
            queued = true;
            requestAnimationFrame(() => { queued = false; decorate(document.getElementById('menubar-container') || bar); });
        }).observe(bar, { childList: true, subtree: true });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else setTimeout(start, 0);
})();
