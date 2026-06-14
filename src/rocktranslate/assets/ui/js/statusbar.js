/**
 * RockTranslate — Status Bar and Zoom Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/statusbar.js
 * 
 * Manages status bar messages and handles horizontal zoom scaling increments.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.0
 */

function statusbarController() {
    return {
        // Left-side active status message
        statusText: '',

        // ── INITIAL ZOOM FIX: Set comfortable default scale to 80% ──
        zoomPercent: 80,

        init() {
            const i18nStore = Alpine.store('i18n');
            this.statusText = i18nStore.translate('status_ready');

            window.addEventListener('update-status-text', (event) => {
                if (event.detail && event.detail.text) {
                    this.statusText = event.detail.text;
                }
            });

            // ── BIND MENU BAR ZOOM EVENTS TO THE SLIDER ──
            window.addEventListener('trigger-zoom-in', () => this.increment());
            window.addEventListener('trigger-zoom-out', () => this.decrement());
            window.addEventListener('trigger-zoom-reset', () => {
                this.zoomPercent = 100;
                this.updateZoom();
            });

            // Dispatch our initial 80% zoom on startup
            this.$nextTick(() => this.updateZoom());
        },

        updateZoom() {
            this.zoomPercent = Math.max(50, Math.min(250, parseInt(this.zoomPercent) || 80));

            // Dispatch active zoom factor to workspace iframe viewports
            const factor = this.zoomPercent / 100.0;
            this.$dispatch('trigger-zoom-change', { factor: factor });
        },

        decrement() {
            this.zoomPercent = Math.max(50, this.zoomPercent - 10);
            this.updateZoom();
        },

        increment() {
            this.zoomPercent = Math.min(250, this.zoomPercent + 10);
            this.updateZoom();
        }
    };
}