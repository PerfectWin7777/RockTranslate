/**
 * Returns the per-session token required by the local file server.
 * The token is passed once in the index.html query string and cached for reloads.
 */
window.rtSessionToken = function () {
    let tok = new URLSearchParams(window.location.search).get('t');
    try {
        if (tok) sessionStorage.setItem('rt-token', tok);
        else tok = sessionStorage.getItem('rt-token');
    } catch (e) { /* storage unavailable */ }
    return encodeURIComponent(tok || '');
};

/**
 * RockTranslate — Split-Pane Workspace Alpine.js Controller
 * Path: src/rocktranslate/assets/ui/js/workspace.js
 * 
 * Drives interactive splitter dragging, synchronous bidirectional scrolling coordinates,
 * layout pane switches, and dynamic zoom factor scaling.
 * 
 * Author: RockTranslate Contributors
 * License: MIT License
 * Version: 1.0.3
 */

// pdf2htmlEX converts at --zoom 1.3 px/pt; PDF.js shows 96/72 px/pt at 100%
const RT_HTML_ZOOM_CORRECTION = (96 / 72) / 1.3;

function workspaceController() {
    return {
        isDragging: false,
        isPDFLoaded: false,
        isSyncing: false,
        lastSyncedPage: 0,

        // Default initial zoom factor (80%)
        zoomFactor: 1.0,

        init() {
            // The workspace component is re-mounted on every document open: drop
            // the listeners of the previous instance, or every event is handled
            // twice (double progress counts, stale iframe handles).
            if (window.__rtWorkspaceListeners) window.__rtWorkspaceListeners.abort();
            const listeners = new AbortController();
            window.__rtWorkspaceListeners = listeners;
            const rtOn = (target, type, fn) => target.addEventListener(type, fn, { signal: listeners.signal });

            // Register zoom listeners from the bottom status bar slider
            rtOn(window, 'trigger-zoom-change', (e) => {
                if (e.detail && e.detail.factor) {
                    this.zoomFactor = e.detail.factor;
                    this.applyZoom(this.zoomFactor);
                }
            });

            // Register layout switch listeners from the dropdown menu bar options
            rtOn(window, 'trigger-layout-change', (e) => {
                if (e.detail && e.detail.mode) {
                    this.setPaneLayout(e.detail.mode);
                }
            });

            // ── TRANSLATION WORKER COMMUNICATION INTERCEPTORS ──
            rtOn(window, 'stream-translation', (e) => {
                if (e.detail && e.detail.id && e.detail.text) {
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.applyTranslation) {
                        htmlFrame.contentWindow.applyTranslation(e.detail.id, e.detail.text);
                    }
                }
            });

            // Batched stream: one bridge call per LLM batch instead of two per segment
            rtOn(window, 'stream-translations', (e) => {
                const items = (e.detail && e.detail.items) || [];
                const htmlFrame = document.getElementById('html-iframe');
                const win = htmlFrame && htmlFrame.contentWindow;
                if (win && win.applyTranslation) {
                    items.forEach(it => { if (it && it.id && it.text) win.applyTranslation(it.id, it.text); });
                }
                window.dispatchEvent(new CustomEvent('update-progress-segments', { detail: { count: items.length } }));
            });

            // Pages opened for translation in the current run. The right pane may be
            // (re)loaded AFTER 'prepare-page' was sent (first run: the document is
            // prepared, then the iframe reloads), so onload replays this set.
            this.preparingPages = new Set();
            rtOn(window, 'trigger-translation-finished', () => { this.preparingPages.clear(); });

            rtOn(window, 'prepare-page', (e) => {
                if (e.detail && e.detail.page !== undefined) {
                    this.preparingPages.add(e.detail.page);
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.preparePageForTranslation) {
                        htmlFrame.contentWindow.preparePageForTranslation(e.detail.page);
                    }
                }
            });

            rtOn(window, 'reset-page', (e) => {
                if (e.detail && e.detail.page !== undefined) {
                    this.preparingPages.delete(e.detail.page);
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.resetPageToWaiting) {
                        htmlFrame.contentWindow.resetPageToWaiting(e.detail.page);
                    }
                }
            });

            rtOn(window, 'hide-glass-overlays', (e) => {
                if (e.detail && e.detail.pages) {
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow) {
                        e.detail.pages.forEach(idx => {
                            const glass = htmlFrame.contentWindow.document.getElementById('glass-overlay-t-' + idx);
                            if (glass) {
                                glass.style.display = 'none';
                            }
                        });
                    }
                }
            });

            // ── CLEAR REMAINING SKELETON SHIMMERS ON COMPLETION ──
            rtOn(window, 'trigger-translation-finished', () => {
                const htmlFrame = document.getElementById('html-iframe');
                if (htmlFrame && htmlFrame.contentWindow) {
                    try {
                        htmlFrame.contentWindow.document.querySelectorAll('.shimmer-line').forEach(el => {
                            el.classList.remove('shimmer-line');
                        });
                    } catch (e) { }
                }
            });

            // ── TRANSLATION RESET LISTENER ──
            rtOn(window, 'trigger-translation-reset', (e) => {
                const htmlFrame = document.getElementById('html-iframe');
                if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.applyTranslation) {
                    try {
                        // Extract target pages from the event detail if provided
                        const targetPages = (e.detail && e.detail.pages) ? e.detail.pages : null;
                        this.reset_translation_state(targetPages);
                    } catch (err) {
                        console.error("[Workspace] Reset translation failed:", err);
                    }
                }
            });


            // Bind splitter drags globally to the document
            rtOn(document, 'mousemove', (e) => this.handleSplitterMove(e));
            rtOn(document, 'mouseup', () => this.stopSplitterDrag());

            // Load the iframes immediately on initialization if paths are already present
            if (this.$data.activeFilePath) {
                this.loadFrames();
            }

            // Re-sync iframe loads on active file paths changes
            this.$watch('$data.activeFilePath', () => this.loadFrames());

            // Lazy mode: load the right pane only when a prepared workspace becomes available
            this.$watch('$data.activeHtmlPath', () => this.loadHtmlFrame());
        },

        loadFrames() {
            this.isPDFLoaded = false;
            this.lastSyncedPage = 0;
            this.isSyncing = false;

            const pdfFrame = document.getElementById('pdf-iframe');
            const htmlFrame = document.getElementById('html-iframe');
            if (!pdfFrame || !htmlFrame) return;

            this.loadPdfFrame(pdfFrame);
            this.loadHtmlFrame();
        },

        loadPdfFrame(pdfFrame) {
            // Dynamically resolve "http://127.0.0.1:XXXXX" or "http://localhost:XXXXX"
            const origin = window.location.origin;
            const pdfjsViewer = `${origin}/pdfjs/web/viewer.html`;

            // Format served file URLs safely to maintain Same-Origin alignment (prevents CORS crashes)
            const fileUrl = `${origin}/local-file?t=${window.rtSessionToken()}&path=${encodeURIComponent(this.$data.activeFilePath)}`;

            // Load left iframe with PDF.js viewer and completely hide the top toolbar/navpanes
            pdfFrame.src = `${pdfjsViewer}?file=${encodeURIComponent(fileUrl)}#toolbar=0&navpanes=0&pagemode=none`;

            // Apply current active zoom factor immediately on load
            this.applyZoom(this.zoomFactor);

            this.setupSyncScrolls(pdfFrame, document.getElementById('html-iframe'));
        },

        loadHtmlFrame() {
            const htmlFrame = document.getElementById('html-iframe');
            const placeholder = document.getElementById('trans-placeholder');
            if (!htmlFrame) return;

            // Lazy mode: no prepared workspace yet, show the placeholder overlay
            if (!this.$data.activeHtmlPath) {
                htmlFrame.removeAttribute('src');
                if (placeholder) placeholder.style.display = 'flex';
                return;
            }

            // Keep the preparation card up until the (possibly large) layout has
            // actually loaded, so the pane never shows a stale or blank page.
            const store = Alpine.store('trans');
            if (store) store.layoutLoading = true;
            if (placeholder) placeholder.style.display = 'flex';
            htmlFrame.addEventListener('load', () => {
                if (store) store.layoutLoading = false;
                if (placeholder) placeholder.style.display = 'none';
            }, { once: true });

            // Folder-style URL: the page's relative resources (page images) resolve
            // next to it. Both separators are handled (Windows and POSIX paths).
            const fullPath = this.$data.activeHtmlPath;
            const cut = Math.max(fullPath.lastIndexOf('/'), fullPath.lastIndexOf('\\'));
            const folder = fullPath.slice(0, cut);
            const name = fullPath.slice(cut + 1);
            const htmlUrl = `${window.location.origin}/doc/${window.rtSessionToken()}/${encodeURIComponent(folder)}/${encodeURIComponent(name)}`;
            htmlFrame.src = htmlUrl;
        },

        /**
          * Initiates the drag-resize interaction on the splitter divider.
          * Temporarily disables pointer-events in both iFrames to prevent mouse capturing.
          * 
          * @param {MouseEvent} e - The native mousedown event.
          */
        startSplitterDrag(e) {
            this.isDragging = true;

            // Prevent native text selections and text dragging artifacts during movement
            if (e) {
                e.preventDefault();
            }

            const grid = document.getElementById('workspace-grid');
            if (grid) {
                grid.classList.add('dragging');
            }
            document.body.style.cursor = 'col-resize';

            // Disable pointer-events inside iframes to prevent them from swallowing mouse movements
            const pdfFrame = document.getElementById('pdf-iframe');
            const htmlFrame = document.getElementById('html-iframe');
            if (pdfFrame) pdfFrame.style.pointerEvents = 'none';
            if (htmlFrame) htmlFrame.style.pointerEvents = 'none';
        },

        handleSplitterMove(e) {
            if (!this.isDragging) return;
            const grid = document.getElementById('workspace-grid');
            if (!grid) return;

            // Use bounding rect calculations to automatically factor out global CSS Zooms and absolute container shifts
            const rect = grid.getBoundingClientRect();

            // Extract accurate pixel offset relative to workspace boundaries
            const relativeX = e.clientX - rect.left;

            // Compute percentage directly on rendering dimension profiles
            const percentage = (relativeX / rect.width) * 100;

            // Apply layout constraints with safety margins
            if (percentage > 15 && percentage < 85) {
                grid.style.gridTemplateColumns = `${percentage}% 6px 1fr`;
            }
        },

        stopSplitterDrag() {
            if (this.isDragging) {
                this.isDragging = false;

                const grid = document.getElementById('workspace-grid');
                if (grid) {
                    grid.classList.remove('dragging');
                }
                document.body.style.cursor = 'default';

                // Restore interactive pointer events on iframes
                document.getElementById('pdf-iframe').style.pointerEvents = 'auto';
                document.getElementById('html-iframe').style.pointerEvents = 'auto';

                // Force PDF.js to redraw its canvas configurations to adapt to the new viewport box rules
                const pdfFrame = document.getElementById('pdf-iframe');
                if (pdfFrame && pdfFrame.contentWindow) {
                    try {
                        pdfFrame.contentWindow.dispatchEvent(new Event('resize'));
                    } catch (e) { }
                }
            }
        },

        setPaneLayout(layout) {
            const leftPane = document.getElementById('left-pane');
            const rightPane = document.getElementById('right-pane');
            const splitter = document.getElementById('workspace-splitter');
            const grid = document.getElementById('workspace-grid');
            if (!grid || !leftPane || !rightPane || !splitter) return;

            if (layout === 'both') {
                leftPane.style.display = 'block';
                rightPane.style.display = 'block';
                splitter.style.display = 'block';
                grid.style.gridTemplateColumns = '50% 6px 1fr';
            } else if (layout === 'pdf_only') {
                leftPane.style.display = 'block';
                rightPane.style.display = 'none';
                splitter.style.display = 'none';
                grid.style.gridTemplateColumns = '1fr';
            } else if (layout === 'trans_only') {
                leftPane.style.display = 'none';
                rightPane.style.display = 'block';
                splitter.style.display = 'none';
                grid.style.gridTemplateColumns = '1fr';
            }
        },

        /**
         * One zoom factor for both panes, at the same visual size: PDF.js
         * draws 96/72 CSS px per point at 100%, pdf2htmlEX pages are converted
         * at 1.3 px per point, hence the HTML correction factor. Debounced:
         * zooming relayouts large documents, so slider drags apply once
         * movement pauses instead of on every pixel (the old full-workspace
         * zoom re-rendered both panes on every slider event).
         */
        applyZoom(factor) {
            clearTimeout(this._zoomTimer);
            this._zoomTimer = setTimeout(() => {
                try {
                    const doc = document.getElementById('html-iframe').contentWindow.document;
                    if (doc && doc.body) doc.body.style.zoom = factor * RT_HTML_ZOOM_CORRECTION;
                } catch (e) { /* frame not ready */ }
                try {
                    const app = document.getElementById('pdf-iframe').contentWindow.PDFViewerApplication;
                    if (app && app.pdfViewer && app.pdfDocument) app.pdfViewer.currentScaleValue = factor;
                } catch (e) { /* viewer not ready */ }
            }, 90);
        },

        /**
         * Synchronizes scrolling coordinates and interactive events bidirectionally.
         * 
         * @param {HTMLIFrameElement} pdfFrame - The left-side PDF.js rendering viewport.
         * @param {HTMLIFrameElement} htmlFrame - The right-side translated HTML workspace.
         */
        setupSyncScrolls(pdfFrame, htmlFrame) {
            const self = this;

            // Sync Phase 1: Left Document (Original PDF) -> Right Document (HTML)
            pdfFrame.onload = function () {
                const iframeWin = pdfFrame.contentWindow;
                const iframeDoc = iframeWin.document;
                if (window.rtApplyThemeToFrames) window.rtApplyThemeToFrames();

                // Forward physical keyboard shortcuts up to the main application context
                iframeDoc.addEventListener('keydown', (e) => {
                    const clonedEvent = new KeyboardEvent('keydown', {
                        key: e.key,
                        code: e.code,
                        ctrlKey: e.ctrlKey,
                        metaKey: e.metaKey,
                        shiftKey: e.shiftKey,
                        altKey: e.altKey,
                        bubbles: true
                    });
                    window.dispatchEvent(clonedEvent);
                });

                // Single unified click listener to handle menu closures and link intercepts
                iframeDoc.addEventListener('click', (e) => {
                    window.dispatchEvent(new CustomEvent('trigger-close-all-menus'));

                    const link = e.target.closest('a');
                    if (link && link.href) {
                        const href = link.href;
                        // Securely open external URLs in the host system's native browser
                        if (href.startsWith('http') && !href.includes(window.location.host)) {
                            e.preventDefault();
                            if (window.pywebview && window.pywebview.api) {
                                window.pywebview.api.open_external_link(href);
                            }
                        }
                    }
                });

                const checkInterval = setInterval(() => {
                    try {
                        if (iframeWin.PDFViewerApplication && iframeWin.PDFViewerApplication.eventBus) {
                            if (iframeWin.PDFViewerApplication.pdfDocument) {
                                clearInterval(checkInterval);
                                self.isPDFLoaded = true;
                                iframeWin.PDFViewerApplication.pdfViewer.currentScaleValue = self.zoomFactor;
                            }

                            iframeWin.PDFViewerApplication.eventBus.on('pagechanging', (evt) => {
                                const pageIndex = evt.pageNumber - 1; // 0-based index
                                if (pageIndex !== self.lastSyncedPage && !self.isSyncing && self.isPDFLoaded) {
                                    self.lastSyncedPage = pageIndex;
                                    self.syncPDFToHTML(htmlFrame, pageIndex);
                                }
                            });
                        }
                    } catch (e) {
                        // Suppress failures during early lifecycle loads
                    }
                }, 100);
            };

            // Sync Phase 2: Right Document (HTML Workspace) -> Left Document (PDF)
            htmlFrame.onload = function () {
                const rightDocWindow = htmlFrame.contentWindow;
                const rightDoc = rightDocWindow.document;
                if (window.rtApplyThemeToFrames) window.rtApplyThemeToFrames();

                // Localize the in-document waiting overlays
                try {
                    const waiting = Alpine.store('i18n').translate('waiting_for_translation');
                    rightDocWindow.RT_WAITING_TEXT = waiting;
                    rightDocWindow.RT_HOVER_ORIGINAL = window.rtHoverOriginal === true;
                    rightDocWindow.RT_ORIGINAL_LABEL = Alpine.store('i18n').translate('original_label');
                    rightDoc.querySelectorAll('[id^="glass-overlay-t-"] p').forEach(p => { p.textContent = waiting; });
                } catch (err) { }

                // Replay pages of a run that started before this document loaded
                try {
                    if (self.preparingPages && rightDocWindow.preparePageForTranslation) {
                        self.preparingPages.forEach(p => rightDocWindow.preparePageForTranslation(p));
                    }
                } catch (err) { }

                // Restore translations already known to the backend (previous session,
                // or a workspace reload) so the right pane never loses finished work.
                try {
                    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_session_translations) {
                        window.pywebview.api.get_session_translations().then((data) => {
                            if (!data || !rightDocWindow.applyTranslation) return;
                            (data.pages || []).forEach(p => {
                                const glass = rightDoc.getElementById('glass-overlay-t-' + p);
                                if (glass) glass.style.display = 'none';
                            });
                            Object.entries(data.items || {}).forEach(([id, text]) => rightDocWindow.applyTranslation(id, text));
                        }).catch(() => {});
                    }
                } catch (err) { console.warn('[Workspace] restore failed', err); }

                // Forward physical keyboard shortcuts up to the main application context
                rightDoc.addEventListener('keydown', (e) => {
                    const clonedEvent = new KeyboardEvent('keydown', {
                        key: e.key,
                        code: e.code,
                        ctrlKey: e.ctrlKey,
                        metaKey: e.metaKey,
                        shiftKey: e.shiftKey,
                        altKey: e.altKey,
                        bubbles: true
                    });
                    window.dispatchEvent(clonedEvent);
                });

                const scrollContainer = rightDoc.getElementById('page-container') || rightDocWindow;

                // Unified click handler for the translated layout (Fixed scope error)
                rightDoc.addEventListener('click', (e) => {
                    window.dispatchEvent(new CustomEvent('trigger-close-all-menus'));

                    const link = e.target.closest('a');
                    if (link && link.href) {
                        const href = link.href;
                        // Securely open external URLs in the host system's native browser
                        if (href.startsWith('http') && !href.includes(window.location.host)) {
                            e.preventDefault();
                            if (window.pywebview && window.pywebview.api) {
                                window.pywebview.api.open_external_link(href);
                            }
                        }
                    }
                });

                try {
                    const body = rightDoc.body;
                    if (body) {
                        body.style.zoom = self.zoomFactor * RT_HTML_ZOOM_CORRECTION;
                    }
                } catch (e) {
                    // Suppress failures if body zoom metrics are currently locked
                }

                try {
                    rightDoc.querySelectorAll('[id^="glass-overlay-t-"]').forEach(glass => {
                        const textElement = glass.querySelector('p');
                        if (textElement) {
                            textElement.textContent = Alpine.store('i18n').translate('waiting_translation');
                        }
                    });
                } catch (e) {
                    // Fail silently during initial asset builds
                }

                scrollContainer.addEventListener('scroll', () => {
                    if (self.isSyncing || !self.isPDFLoaded) return;

                    const pages = rightDoc.querySelectorAll('.pf');
                    let maxVisible = 0;
                    let currentIdx = 0;
                    const paneHeight = htmlFrame.clientHeight;

                    pages.forEach((page, index) => {
                        const rect = page.getBoundingClientRect();
                        const visibleHeight = Math.max(0, Math.min(rect.bottom, paneHeight) - Math.max(rect.top, 0));
                        if (visibleHeight > maxVisible) {
                            maxVisible = visibleHeight;
                            currentIdx = index;
                        }
                    });

                    if (currentIdx !== self.lastSyncedPage) {
                        self.lastSyncedPage = currentIdx;
                        self.isSyncing = true;

                        try {
                            const leftWin = pdfFrame.contentWindow;
                            if (leftWin.PDFViewerApplication &&
                                leftWin.PDFViewerApplication.pdfViewer &&
                                leftWin.PDFViewerApplication.pdfViewer.pagesCount > 0) {
                                leftWin.PDFViewerApplication.page = Number(currentIdx) + 1;
                            }
                        } catch (e) {
                            // Suppress failures if eventBus handles are busy
                        }

                        setTimeout(() => { self.isSyncing = false; }, 300);
                    }
                });
            };
        },

        syncPDFToHTML(htmlFrame, pageIndex) {
            if (this.isSyncing) return;
            this.isSyncing = true;

            try {
                const rightDoc = htmlFrame.contentWindow;
                const pageHex = (pageIndex + 1).toString(16);
                let targetPage = rightDoc.document.getElementById('pf' + pageHex);

                if (!targetPage) {
                    const pages = rightDoc.document.querySelectorAll('.pf');
                    if (pages[pageIndex]) {
                        targetPage = pages[pageIndex];
                    }
                }

                if (targetPage) {
                    targetPage.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            } catch (e) {
                console.error("Scroll Sync Error (Left->Right):", e);
            }

            setTimeout(() => { this.isSyncing = false; }, 300);
        },


        /**
         * Clears translation memories and restores the original styled HTML
         * and scale matrices in the browser without reloading the page.
         * Supports selective range resets.
         * 
         * @param {Array<number>|null} targetPages - Array of 0-based page indices to reset, or null for all.
         */
        reset_translation_state(targetPages = null) {
            const htmlFrame = document.getElementById('html-iframe');
            if (htmlFrame && htmlFrame.contentWindow) {
                const doc = htmlFrame.contentWindow.document;

                doc.querySelectorAll('span[data-trans-id]').forEach(span => {
                    const pageEl = span.closest('.pf');
                    if (pageEl) {
                        // Resolve page index (0-based) from hex ID
                        const idStr = pageEl.getAttribute('id') || '';
                        const match = idStr.match(/pf([0-9a-fA-F]+)/);
                        if (match) {
                            const pageIdx = parseInt(match[1], 16) - 1;

                            // If targeted pages are provided, skip reset if this page index is not in the targets
                            if (targetPages !== null && !targetPages.includes(pageIdx)) {
                                return;
                            }
                        }
                    }

                    const originalHtml = span.getAttribute('data-orig-html');

                    if (originalHtml !== null && originalHtml !== undefined) {
                        // 1. Restore the original styled HTML with correct font families
                        span.innerHTML = originalHtml;
                        if (span.hasAttribute('data-orig-class')) {
                            span.className = span.getAttribute('data-orig-class');
                            span.removeAttribute('data-orig-class');
                        }
                        span.classList.remove('shimmer-line', 'translated');
                        span.style.removeProperty('word-spacing');
                        span.style.removeProperty('letter-spacing');
                        // Table-row cells were fitted on their own (inline-block, width, scale)
                        ['width', 'transform', 'transform-origin', 'white-space'].forEach((p) => span.style.removeProperty(p));
                        span.style.display = 'inline';

                        // 2. Reset the scale matrices of the parent container div.t
                        const divT = span.closest('div.t');
                        if (divT) {
                            // Back to the pdf2htmlEX class matrix (keeps the rotation of sideways lines)
                            divT.style.removeProperty('transform');

                            // Remove temporary width metrics to force clean recalculations for the next language
                            divT.style.removeProperty('left');
                            divT.removeAttribute('data-orig-left');
                            divT.removeAttribute('data-orig-pleft');
                            divT.removeAttribute('data-fit');
                            divT.removeAttribute('data-orig-sw');
                            divT.removeAttribute('data-sx-orig');
                            divT.removeAttribute('data-sy-orig');
                        }
                    }
                });
            }
        },
    };

    
}   



