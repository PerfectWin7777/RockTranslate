/** Pushes the "original text on hover" setting into the translated pane. */
window.rtHoverOriginal = false;
window.rtSetHoverOriginal = function (on) {
    window.rtHoverOriginal = !!on;
    window.dispatchEvent(new CustomEvent('hover-original-changed', { detail: { on: window.rtHoverOriginal } }));
    try {
        const w = document.getElementById('html-iframe').contentWindow;
        if (w) w.RT_HOVER_ORIGINAL = window.rtHoverOriginal;
    } catch (e) { /* frame not loaded */ }
};

/**
 * RockTranslate — Settings window controller + run statistics formatting
 * Path: src/rocktranslate/assets/ui/js/preferences.js
 *
 * License: MIT License
 */

window.rtFormat = {
    int(n) { return Number(n || 0).toLocaleString(); },
    tokens(n) {
        n = Number(n || 0);
        if (n >= 1e6) return (n / 1e6).toFixed(2) + ' M';
        if (n >= 1e4) return (n / 1e3).toFixed(1) + ' k';
        return n.toLocaleString();
    },
    cost(usd) {
        usd = Number(usd || 0);
        if (usd === 0) return '$0';
        // Real amount even when tiny (a page costs fractions of a cent)
        if (usd < 0.0001) return '< $0.0001';
        if (usd < 0.01) return '$' + usd.toFixed(4);
        return '$' + usd.toFixed(usd < 1 ? 3 : 2);
    },
    duration(sec) {
        sec = Math.max(0, Math.round(Number(sec || 0)));
        const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
        if (h) return `${h} h ${String(m).padStart(2, '0')} min`;
        if (m) return `${m} min ${String(s).padStart(2, '0')} s`;
        return `${s} s`;
    }
};

function preferencesController() {
    return {
        section: 'general',
        version: '2.0.5',
        savedFlash: false,
        _flashTimer: null,
        p: {},
        api: {},
        cache: { documents: 0, size_mb: 0 },
        usage: { totals: { runs: 0, segments: 0, prompt_tokens: 0, completion_tokens: 0, cost_usd: 0, seconds: 0 }, by_model: {}, last_run: null },

        sections: [
            { id: 'general', icon: '⚙︎', label: 'prefs_general' },
            { id: 'model', icon: '✦', label: 'prefs_model' },
            { id: 'translation', icon: '⇄', label: 'prefs_translation' },
            { id: 'advanced', icon: '⌘', label: 'prefs_advanced' },
            { id: 'usage', icon: '∑', label: 'prefs_usage' },
        ],

        numericFields: [
            { key: 'parallel_requests', label: 'trans_parallel_lbl', hint: 'trans_parallel_tip', min: 1, max: 16, step: 1 },
            { key: 'max_segments_per_batch', label: 'prefs_batch_size', hint: 'prefs_batch_size_hint', min: 5, max: 200, step: 5, unit: 'prefs_unit_segments' },
            { key: 'sliding_context_size', label: 'prefs_context', hint: 'prefs_context_hint', min: 0, max: 20, step: 1, unit: 'prefs_unit_paragraphs' },
            { key: 'max_retries', label: 'trans_retries_lbl', hint: 'prefs_retries_hint', min: 1, max: 10, step: 1 },
            { key: 'request_timeout', label: 'prefs_timeout', hint: 'prefs_timeout_hint', min: 20, max: 900, step: 10, unit: 'prefs_unit_seconds' },
        ],

        pathFields: [
            { key: 'pdf2htmlex_path_override', label: 'system_pdf2html_lbl', hint: 'prefs_pdf2html_hint', kind: 'file' },
            { key: 'browser_path_override', label: 'prefs_browser', hint: 'prefs_browser_hint', kind: 'file' },
            { key: 'pdfjs_path_override', label: 'system_pdfjs_lbl', hint: 'prefs_pdfjs_hint', kind: 'folder' },
        ],

        t(key, vars) { return Alpine.store('i18n').translate(key, vars || {}); },
        fmtInt(n) { return rtFormat.int(n); },
        fmtTokens(n) { return rtFormat.tokens(n); },
        fmtCost(n) { return rtFormat.cost(n); },
        fmtDuration(n) { return rtFormat.duration(n); },

        init() {
            // Menu toggle and settings switch stay in sync
            window.addEventListener('hover-original-changed', (e) => { if (this.p) this.p.hover_original = !!(e.detail && e.detail.on); });
            const load = () => this.loadAll();
            rtBridge.whenReady(load);  // waits until every Python method is attached
            window.addEventListener('translation-summary', () => this.loadUsage());
            this.$watch('$store.modals.active', (v) => { if (v === 'preferences') this.loadAll(); });
        },

        openAt(section) {
            if (section && this.sections.some(s => s.id === section)) this.section = section;
            Alpine.store('modals').open('preferences');
        },

        async loadAll() {
            const api = window.pywebview && window.pywebview.api;
            if (!api || !api.get_preferences) return;
            try {
                this.p = await api.get_preferences() || {};
                window.rtShowCost = this.p.show_cost_estimates !== false;
                window.rtSetHoverOriginal(this.p.hover_original === true);
                this.api = await api.get_api_status() || {};
                this.cache = await api.get_cache_info() || this.cache;
                await this.loadUsage();
                if (api.get_app_version) this.version = await api.get_app_version();
            } catch (e) { console.error('[Prefs] load failed', e); }
        },

        async loadUsage() {
            try {
                const u = await window.pywebview.api.get_usage_stats();
                if (u) this.usage = u;
            } catch (e) { }
        },

        flash() {
            this.savedFlash = true;
            clearTimeout(this._flashTimer);
            this._flashTimer = setTimeout(() => { this.savedFlash = false; }, 1400);
        },

        async save(key) {
            try {
                const res = await window.pywebview.api.set_preference(key, this.p[key]);
                if (res && res.status === 'success') {
                    this.p[key] = res.value;
                    if (key === 'show_cost_estimates') window.rtShowCost = !!res.value;
                    if (key === 'hover_original') window.rtSetHoverOriginal(!!res.value);
                    this.flash();
                } else {
                    window.showToast((res && res.message) || this.t('save_error_msg'), 'error');
                    this.loadAll();
                }
            } catch (e) {
                window.showToast(this.t('save_error_msg'), 'error');
            }
        },

        step(f, dir) {
            const v = Number(this.p[f.key] || 0) + dir * f.step;
            this.p[f.key] = Math.min(f.max, Math.max(f.min, v));
            this.save(f.key);
        },

        setTargetLang() {
            window.pywebview.api.set_target_language(this.p.target_lang);
            window.dispatchEvent(new CustomEvent('refresh-menu-data'));
            this.flash();
        },

        setUiLang(code) {
            Alpine.store('i18n').setLocale(code);
            if (window.pywebview.api.set_system_locale) window.pywebview.api.set_system_locale(code);
            this.flash();
        },

        async browse(f) {
            const api = window.pywebview.api;
            const res = f.kind === 'folder' ? await api.browse_folder_dialog() : await api.browse_binary_dialog();
            if (res && res.status === 'success') {
                this.p[f.key] = res.path;
                this.save(f.key);
            }
        },

        async clearCache() {
            const ok = await Alpine.store('dialogs').confirm(this.t('prefs_clear_cache_confirm'), this.t('prefs_cache'));
            if (!ok) return;
            const res = await window.pywebview.api.clear_translation_cache();
            if (res) {
                this.cache = res;
                window.showToast(this.t('prefs_cache_cleared', { n: res.removed }), 'success');
            }
        },

        async resetDefaults() {
            const ok = await Alpine.store('dialogs').confirm(this.t('prefs_reset_confirm'), this.t('prefs_reset_defaults'));
            if (!ok) return;
            const res = await window.pywebview.api.reset_preferences();
            if (res && res.preferences) { this.p = res.preferences; this.flash(); }
        },

        async resetUsage() {
            const ok = await Alpine.store('dialogs').confirm(this.t('usage_reset_confirm'), this.t('prefs_usage'));
            if (!ok) return;
            await window.pywebview.api.reset_usage_stats();
            this.loadUsage();
        }
    };
}
