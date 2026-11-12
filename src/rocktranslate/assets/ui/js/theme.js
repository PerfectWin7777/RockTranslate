/**
 * RockTranslate — Theme manager (light / dark / system)
 * Path: src/rocktranslate/assets/ui/js/theme.js
 *
 * - The theme is resolved before first paint by an inline script in index.html.
 * - This store lets the user pick Light / Dark / System, persists the choice
 *   (localStorage + backend settings), follows OS changes in System mode, and
 *   themes the two embedded documents (PDF.js viewer and translated workspace).
 *   Document pages themselves stay white "paper" in both themes, like Preview
 *   or Acrobat: only the chrome around them changes.
 *
 * License: MIT License
 */

(function () {
    const STORAGE_KEY = 'rt-theme';
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function readMode() {
        try { return localStorage.getItem(STORAGE_KEY) || 'system'; } catch (e) { return 'system'; }
    }

    function resolve(mode) {
        if (mode === 'dark' || mode === 'light') return mode;
        return media && media.matches ? 'dark' : 'light';
    }

    // Variables of the PDF.js 3.x viewer, tuned to RockTranslate's palettes.
    const PDFJS_VARS = {
        light: {
            '--body-bg-color': '#e4e4e9', '--toolbar-bg-color': '#f8f8fa', '--toolbar-border-color': '#e2e2e7',
            '--sidebar-toolbar-bg-color': '#f2f2f5', '--sidebar-narrow-bg-color': 'rgba(242,242,245,0.9)',
            '--field-bg-color': '#ffffff', '--field-border-color': '#cfcfd6', '--field-color': '#1d1d1f',
            '--main-color': '#1d1d1f', '--button-hover-color': 'rgba(0,0,0,0.06)',
            '--doorhanger-bg-color': '#ffffff', '--dropdown-btn-bg-color': '#ffffff',
            '--scrollbar-color': '#b8b8c0', '--scrollbar-bg-color': '#e4e4e9',
            '--toolbar-icon-bg-color': '#4a4a50', '--toolbar-icon-hover-bg-color': '#1d1d1f'
        },
        dark: {
            '--body-bg-color': '#121214', '--toolbar-bg-color': '#242427', '--toolbar-border-color': '#37373b',
            '--sidebar-toolbar-bg-color': '#1f1f22', '--sidebar-narrow-bg-color': 'rgba(31,31,34,0.9)',
            '--field-bg-color': '#2b2b2f', '--field-border-color': '#4a4a50', '--field-color': '#f2f2f5',
            '--main-color': '#f2f2f5', '--button-hover-color': 'rgba(255,255,255,0.08)',
            '--doorhanger-bg-color': '#2b2b2f', '--doorhanger-border-color': '#37373b',
            '--doorhanger-hover-bg-color': '#3d8bff', '--doorhanger-hover-color': '#ffffff',
            '--dropdown-btn-bg-color': '#2b2b2f', '--separator-color': 'rgba(255,255,255,0.08)',
            '--scrollbar-color': '#4a4a50', '--scrollbar-bg-color': '#121214',
            '--toolbar-icon-bg-color': '#c6c6cc', '--toolbar-icon-hover-bg-color': '#ffffff',
            '--treeitem-color': 'rgba(255,255,255,0.8)', '--treeitem-hover-color': '#ffffff',
            '--thumbnail-hover-color': 'rgba(255,255,255,0.1)', '--thumbnail-selected-color': 'rgba(255,255,255,0.2)',
            '--loading-icon': 'url(images/loading-dark.svg)'
        }
    };

    function injectStyle(doc, id, css) {
        if (!doc || !doc.head) return;
        let tag = doc.getElementById(id);
        if (!tag) {
            tag = doc.createElement('style');
            tag.id = id;
            doc.head.appendChild(tag);
        }
        tag.textContent = css;
    }

    function themeFrames(resolved) {
        const pdfFrame = document.getElementById('pdf-iframe');
        try {
            const doc = pdfFrame && pdfFrame.contentDocument;
            if (doc && doc.documentElement) {
                const vars = PDFJS_VARS[resolved];
                const body = Object.keys(vars).map(k => `${k}: ${vars[k]} !important;`).join(' ');
                doc.documentElement.style.colorScheme = resolved;
                injectStyle(doc, 'rt-theme', `:root { ${body} }`);
            }
        } catch (e) { /* frame not ready or cross-origin */ }

        const htmlFrame = document.getElementById('html-iframe');
        try {
            const doc = htmlFrame && htmlFrame.contentDocument;
            if (doc && doc.documentElement) {
                const canvas = resolved === 'dark' ? '#121214' : '#e4e4e9';
                const glass = resolved === 'dark' ? 'rgba(36,36,39,0.96)' : 'rgba(250,250,252,0.98)';
                const card = resolved === 'dark' ? '#2b2b2f' : '#ffffff';
                const text = resolved === 'dark' ? '#f2f2f5' : '#1d1d1f';
                injectStyle(doc, 'rt-theme', `
                    html, body, #page-container { background: ${canvas} !important; background-image: none !important; }
                    .pf { box-shadow: 0 1px 3px rgba(0,0,0,.25), 0 8px 24px rgba(0,0,0,${resolved === 'dark' ? '.45' : '.12'}) !important; }
                    [id^="glass-overlay-t-"] { background: ${glass} !important; border-color: transparent !important; }
                    [id^="glass-overlay-t-"] > div { background: ${card} !important; }
                    [id^="glass-overlay-t-"] p { color: ${text} !important; }
                `);
            }
        } catch (e) { /* frame not ready */ }
    }

    function apply(mode, { persist = true } = {}) {
        const resolved = resolve(mode);
        const root = document.documentElement;
        root.classList.add('rt-theme-switching');
        root.setAttribute('data-theme', resolved);
        requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('rt-theme-switching')));
        if (persist) {
            try { localStorage.setItem(STORAGE_KEY, mode); } catch (e) { }
        }
        themeFrames(resolved);
        window.dispatchEvent(new CustomEvent('rt-theme-changed', { detail: { mode, resolved } }));
        return resolved;
    }

    window.rtApplyThemeToFrames = function () { themeFrames(resolve(readMode())); };

    document.addEventListener('alpine:init', () => {
        Alpine.store('theme', {
            mode: readMode(),
            resolved: resolve(readMode()),
            set(mode) {
                if (!['light', 'dark', 'system'].includes(mode)) return;
                this.mode = mode;
                this.resolved = apply(mode);
                try {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_ui_theme) {
                        window.pywebview.api.save_ui_theme(mode);
                    }
                } catch (e) { }
            },
            cycle() {
                const order = ['light', 'dark', 'system'];
                this.set(order[(order.indexOf(this.mode) + 1) % order.length]);
            }
        });
    });

    if (media && media.addEventListener) {
        media.addEventListener('change', () => {
            if (readMode() === 'system') {
                const resolved = apply('system', { persist: false });
                if (window.Alpine && Alpine.store('theme')) Alpine.store('theme').resolved = resolved;
            }
        });
    }

    // Backend is the source of truth across reinstalls: adopt its saved theme once.
    const adoptSavedTheme = () => {
        try {
            if (!window.pywebview.api.get_ui_theme) return;
            window.pywebview.api.get_ui_theme().then((mode) => {
                if (mode && mode !== readMode() && window.Alpine && Alpine.store('theme')) {
                    Alpine.store('theme').mode = mode;
                    Alpine.store('theme').resolved = apply(mode);
                }
            }).catch(() => { });
        } catch (e) { }
    };
    if (window.rtBridge) rtBridge.whenReady(adoptSavedTheme);
    else window.addEventListener('pywebviewready', adoptSavedTheme);
})();
