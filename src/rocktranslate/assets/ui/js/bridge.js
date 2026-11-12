/**
 * RockTranslate — Python bridge readiness
 * Path: src/rocktranslate/assets/ui/js/bridge.js
 *
 * pywebview creates `window.pywebview.api` before it has attached every
 * Python method to it, and `pywebviewready` may fire before or after a
 * component registers its listener. Components that tested
 * `window.pywebview && window.pywebview.api` and called a method right away
 * could therefore hit "not a function" at startup: the call failed silently
 * and the app opened with no saved API keys and no recent files.
 *
 * `rtBridge.whenReady(fn)` runs `fn` exactly once, as soon as the methods the
 * UI depends on are really callable (immediately if they already are).
 * Loaded before every component script.
 */
(function () {
    // Methods every screen reads at startup: when they exist, the bridge is complete.
    const REQUIRED = ['get_recent_files', 'get_api_status', 'get_api_config', 'get_preferences'];
    const POLL_MS = 100;
    const GIVE_UP_MS = 60000;

    function bridgeComplete() {
        const api = window.pywebview && window.pywebview.api;
        return !!api && REQUIRED.every((name) => typeof api[name] === 'function');
    }

    const ready = new Promise((resolve) => {
        if (bridgeComplete()) { resolve(window.pywebview.api); return; }
        const started = Date.now();
        let timer = null;
        const check = () => {
            if (bridgeComplete()) {
                clearInterval(timer);
                window.removeEventListener('pywebviewready', check);
                resolve(window.pywebview.api);
            } else if (Date.now() - started > GIVE_UP_MS) {
                clearInterval(timer);
                console.error('[Bridge] Python API still incomplete after 60 s');
            }
        };
        // The event is the fast path; polling covers an event fired before we
        // listened, or fired while methods were still being attached.
        window.addEventListener('pywebviewready', check);
        timer = setInterval(check, POLL_MS);
    });

    window.rtBridge = {
        ready,
        /** Run `fn(api)` once the Python API is complete. Errors are logged, not thrown. */
        whenReady(fn) {
            ready.then((api) => {
                try {
                    const r = fn(api);
                    if (r && typeof r.catch === 'function') r.catch((e) => console.error('[Bridge] startup load failed', e));
                } catch (e) { console.error('[Bridge] startup load failed', e); }
            });
        }
    };
})();
