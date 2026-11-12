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
        zoomPercent: 100,
        // Long background work (PDF export...): animated dots after the message
        busy: false,

        // PDF export in progress: { stage, done, total } (null when idle)
        exportState: null,

        get exportPercent() {
            const st = this.exportState;
            if (!st) return 0;
            // Pages = 0-80 %, fonts = 85 %, printing = 92 % (Chrome gives no finer signal)
            if (st.stage === 'pages' && st.total > 0) return Math.round(80 * st.done / st.total);
            return { building: 3, loading: 5, fonts: 85, ready: 88, print: 92 }[st.stage] || 0;
        },

        get exportLabel() {
            const st = this.exportState;
            if (!st) return '';
            const i18n = Alpine.store('i18n');
            if (st.stage === 'pages') return i18n.translate('export_stage_pages', { done: st.done, total: st.total });
            if (st.stage === 'fonts' || st.stage === 'ready') return i18n.translate('export_stage_fonts');
            if (st.stage === 'print') return i18n.translate('export_stage_print');
            return i18n.translate('export_stage_building');
        },

        // Either an i18n key (re-translated live) or a literal text
        statusKey: 'status_ready',
        statusVars: {},

        get currentStatus() {
            return this.statusKey
                ? Alpine.store('i18n').translate(this.statusKey, this.statusVars)
                : this.statusText;
        },

        init() {
            window.addEventListener('app-busy', (e) => { this.busy = !!(e.detail && e.detail.on); });
            window.addEventListener('export-progress', (e) => {
                const d = e.detail || {};
                this.exportState = d.stage === 'end' ? null : d;
            });
            window.addEventListener('update-status-text', (event) => {
                const d = event.detail || {};
                if (d.key) {
                    this.statusKey = d.key;
                    this.statusVars = d.variables || {};
                } else if (d.text) {
                    this.statusKey = null;
                    this.statusText = d.text;
                }
            });

            // ── BIND MENU BAR ZOOM EVENTS TO THE SLIDER ──
            window.addEventListener('trigger-zoom-in', () => this.increment());
            window.addEventListener('trigger-zoom-out', () => this.decrement());
            window.addEventListener('trigger-zoom-reset', () => {
                this.zoomPercent = 100;
                this.updateZoom();
            });

            // Dispatch the initial zoom (100%: both panes at the PDF's natural size)
            this.$nextTick(() => this.updateZoom());
        },

        updateZoom() {
            this.zoomPercent = Math.max(50, Math.min(300, parseInt(this.zoomPercent) || 100));

            // Dispatch active zoom factor to workspace iframe viewports
            const factor = this.zoomPercent / 100.0;
            this.$dispatch('trigger-zoom-change', { factor: factor });
        },

        decrement() {
            this.zoomPercent = Math.max(50, this.zoomPercent - 10);
            this.updateZoom();
        },

        increment() {
            this.zoomPercent = Math.min(300, this.zoomPercent + 10);
            this.updateZoom();
        }
    };
}