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

function workspaceController() {
    return {
        isDragging: false,
        isPDFLoaded: false,
        isSyncing: false,
        lastSyncedPage: 0,

        // Default initial zoom factor (80%)
        zoomFactor: 0.8,

        init() {
            // Register zoom listeners from the bottom status bar slider
            window.addEventListener('trigger-zoom-change', (e) => {
                if (e.detail && e.detail.factor) {
                    this.zoomFactor = e.detail.factor;
                    this.applyZoom(this.zoomFactor);
                }
            });

            // Register layout switch listeners from the dropdown menu bar options
            window.addEventListener('trigger-layout-change', (e) => {
                if (e.detail && e.detail.mode) {
                    this.setPaneLayout(e.detail.mode);
                }
            });

            // ── TRANSLATION WORKER COMMUNICATION INTERCEPTORS ──
            window.addEventListener('stream-translation', (e) => {
                if (e.detail && e.detail.id && e.detail.text) {
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.applyTranslation) {
                        htmlFrame.contentWindow.applyTranslation(e.detail.id, e.detail.text);
                    }
                }
            });

            window.addEventListener('prepare-page', (e) => {
                if (e.detail && e.detail.page !== undefined) {
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.preparePageForTranslation) {
                        htmlFrame.contentWindow.preparePageForTranslation(e.detail.page);
                    }
                }
            });

            window.addEventListener('reset-page', (e) => {
                if (e.detail && e.detail.page !== undefined) {
                    const htmlFrame = document.getElementById('html-iframe');
                    if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.resetPageToWaiting) {
                        htmlFrame.contentWindow.resetPageToWaiting(e.detail.page);
                    }
                }
            });

            window.addEventListener('hide-glass-overlays', (e) => {
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
            window.addEventListener('trigger-translation-finished', () => {
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
            window.addEventListener('trigger-translation-reset', () => {
                const htmlFrame = document.getElementById('html-iframe');
                if (htmlFrame && htmlFrame.contentWindow && htmlFrame.contentWindow.applyTranslation) {
                    try {
                        // Triggers the standard, pristine DOM restoration logic
                        this.reset_translation_state();
                    } catch (e) {
                        console.error("[Workspace] Reset translation failed:", e);
                    }
                }
            });


            // Bind splitter drags globally to the document
            document.addEventListener('mousemove', (e) => this.handleSplitterMove(e));
            document.addEventListener('mouseup', () => this.stopSplitterDrag());

            // Load the iframes immediately on initialization if paths are already present
            if (this.$data.activeFilePath) {
                this.loadFrames();
            }

            // Re-sync iframe loads on active file paths changes
            this.$watch('$data.activeFilePath', () => this.loadFrames());
        },

        loadFrames() {
            this.isPDFLoaded = false;
            this.lastSyncedPage = 0;
            this.isSyncing = false;

            const pdfFrame = document.getElementById('pdf-iframe');
            const htmlFrame = document.getElementById('html-iframe');
            if (!pdfFrame || !htmlFrame) return;

            const port = window.location.port;
            const pdfjsViewer = `http://localhost:${port}/pdfjs/web/viewer.html`;

            // Format localhost served file URLs safely
            const fileUrl = `http://localhost:${port}/local-file?path=${encodeURIComponent(this.$data.activeFilePath)}`;
            const htmlUrl = `http://localhost:${port}/local-file?path=${encodeURIComponent(this.$data.activeHtmlPath)}`;

            // Load left iframe with PDF.js viewer and completely hide the top toolbar/navpanes
            pdfFrame.src = `${pdfjsViewer}?file=${encodeURIComponent(fileUrl)}#toolbar=0&navpanes=0&pagemode=none`;

            // Load right iframe with Instrumented HTML workspace
            htmlFrame.src = htmlUrl;

            // Apply current active zoom factor immediately on load
            this.applyZoom(this.zoomFactor);

            this.setupSyncScrolls(pdfFrame, htmlFrame);
        },

        startSplitterDrag() {
            this.isDragging = true;

            const grid = document.getElementById('workspace-grid');
            if (grid) {
                grid.classList.add('dragging');
            }
            document.body.style.cursor = 'col-resize';
        },

        handleSplitterMove(e) {
            if (!this.isDragging) return;
            const grid = document.getElementById('workspace-grid');
            if (!grid) return;

            const containerWidth = grid.clientWidth;
            const percentage = (e.clientX / containerWidth) * 100;

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

        applyZoom(factor) {
            const grid = document.getElementById('workspace-grid');
            if (grid) {
                grid.style.zoom = factor;
            }
        },

        setupSyncScrolls(pdfFrame, htmlFrame) {
            const self = this;

            // Sync: Left (PDF) -> Right (HTML)
            pdfFrame.onload = function () {
                const iframeWin = pdfFrame.contentWindow;
                const iframeDoc = iframeWin.document;

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

                iframeDoc.addEventListener('click', () => {
                    window.dispatchEvent(new CustomEvent('trigger-close-all-menus'));
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
                                const pageIndex = evt.pageNumber - 1; // 0-based
                                if (pageIndex !== self.lastSyncedPage && !self.isSyncing && self.isPDFLoaded) {
                                    self.lastSyncedPage = pageIndex;
                                    self.syncPDFToHTML(htmlFrame, pageIndex);
                                }
                            });
                        }
                    } catch (e) { }
                }, 100);
            };

            // Sync: Right (HTML) -> Left (PDF)
            htmlFrame.onload = function () {
                const rightDocWindow = htmlFrame.contentWindow;
                const rightDoc = rightDocWindow.document;

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

                rightDoc.addEventListener('click', () => {
                    window.dispatchEvent(new CustomEvent('trigger-close-all-menus'));
                });

                try {
                    const body = rightDoc.body;
                    if (body) {
                        body.style.zoom = self.zoomFactor;
                    }
                } catch (e) { }

                try {
                    rightDoc.querySelectorAll('[id^="glass-overlay-t-"]').forEach(glass => {
                        const textElement = glass.querySelector('p');
                        if (textElement) {
                            textElement.textContent = Alpine.store('i18n').translate('waiting_translation');
                        }
                    });
                } catch (e) { }

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
                        } catch (e) { }

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
         */
        reset_translation_state() {
            const htmlFrame = document.getElementById('html-iframe');
            if (htmlFrame && htmlFrame.contentWindow) {
                const doc = htmlFrame.contentWindow.document;

                doc.querySelectorAll('span[data-trans-id]').forEach(span => {
                    const originalHtml = span.getAttribute('data-orig-html');

                    if (originalHtml !== null && originalHtml !== undefined) {
                        // 1. Restore the original styled HTML with correct font families
                        span.innerHTML = originalHtml;
                        span.classList.remove('shimmer-line');

                        // 2. Reset the scale matrices of the parent container div.t
                        const divT = span.closest('div.t');
                        if (divT) {
                            const sxOrig = parseFloat(span.getAttribute('data-sx') || '1');
                            const syOrig = parseFloat(span.getAttribute('data-sy') || '1');
                            divT.style.transform = `matrix(${sxOrig},0,0,${syOrig},0,0)`;

                            // Remove temporary width metrics to force clean recalculations for the next language
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



