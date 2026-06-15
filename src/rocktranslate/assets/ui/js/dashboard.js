/**
 * RockTranslate — Welcome Dashboard Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/dashboard.js
 * 
 * Manages dragging states, fetches recent document histories, 
 * and handles secure bridge communications with the Python background API.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.0
 */

function dashboardController() {
    return {
        // Drop area active dragging highlight marker
        isDragging: false,

        // Array containing verified local history items: [{ name, path }]
        recentFiles: [],

        // Current translation API connection and key status map
        apiState: {
            active: false,
            provider: 'Google Gemini',
            model: 'gemini-3.1-flash-lite'
        },

        /**
         * Standard Alpine.js initialization hook.
         * Syncs with the pywebview host bridge safely when ready.
         */
        init() {
            if (window.pywebview && window.pywebview.api) {
                this.loadDashboardData();
            } else {
                window.addEventListener('pywebviewready', () => this.loadDashboardData());
            }

            // Real-time synchronization of recent documents list and API credential status
            window.addEventListener('refresh-menu-data', () => this.loadDashboardData());
        },

        /**
         * Fetches verified recent items and active model credentials from Python.
         */
        async loadDashboardData() {
            try {
                // Fetch recent files lists
                const files = await window.pywebview.api.get_recent_files();
                this.recentFiles = files || [];

                // Fetch current configuration credentials state
                const status = await window.pywebview.api.get_api_status();
                if (status) {
                    this.apiState = status;
                }
            } catch (error) {
                console.error("[Dashboard] Error syncing settings with backend:", error);
            }
        },

        /**
         * Resolves the localized API model status indicator text.
         */
        getApiStatusText() {
            const i18nStore = Alpine.store('i18n');
            if (!this.apiState.active) {
                return i18nStore.translate('api_setup_required', { provider: this.apiState.provider });
            }
            if (this.apiState.provider === "Ollama (Local)") {
                return i18nStore.translate('api_active_local', { model: this.apiState.model });
            }
            return i18nStore.translate('api_active_remote', { provider: this.apiState.provider, model: this.apiState.model });
        },

        /**
         * Triggers the native platform file selection dialog window.
         */
        async openFilePicker() {
            try {
                const result = await window.pywebview.api.open_file_dialog();
                if (result && result.status === 'success') {
                    // Start Python background extraction worker immediately
                    window.pywebview.api.extract_pdf(result.path);
                }
            } catch (error) {
                console.error("[Dashboard] Error triggering dialog window:", error);
            }
        },

        /**
         * Handles local filesystem drops safely on the dashed border panel.
         */
        handleFileDrop(event) {
            this.isDragging = false;
            // Native Python-side handler will automatically capture 'pywebviewFullPath' on drop
        },


        /**
         * Loads a file directly when clicked from the recent files panel list.
         */
        loadRecentFile(filePath) {
            window.pywebview.api.extract_pdf(filePath);
        }
    };
}