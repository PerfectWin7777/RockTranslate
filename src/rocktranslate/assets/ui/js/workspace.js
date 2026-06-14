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

        // Default initial zoom factor (70%)
        zoomFactor: 0.7,

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

        /**
         * ── 1. DRAG-RESIZE SPLITTER LOGIC ──
         */
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

        /**
         * ── 2. LAYOUT MODES CONSTRAINTS ──
         */
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
         * ── 3. REAL-TIME NATIVE ZOOM SCALING ──
         */
        applyZoom(factor) {
            const grid = document.getElementById('workspace-grid');
            if (grid) {
                grid.style.zoom = factor;
            }
        },

        /**
         * ── 4. BIDIRECTIONAL SCROLLING SYNCHRONIZATION & IFRAME CLICKS ──
         */
        setupSyncScrolls(pdfFrame, htmlFrame) {
            const self = this;

            // Sync: Left (PDF) -> Right (HTML)
            pdfFrame.onload = function () {
                const iframeWin = pdfFrame.contentWindow;
                const iframeDoc = iframeWin.document;

                // ── CLOSE MENUS ON LEFT IFRAME CLICK ──
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
                const scrollContainer = rightDoc.getElementById('page-container') || rightDocWindow;

                // ── CLOSE MENUS ON RIGHT IFRAME CLICK ──
                rightDoc.addEventListener('click', () => {
                    window.dispatchEvent(new CustomEvent('trigger-close-all-menus'));
                });

                // ── INITIAL ZOOM LOCK FOR HTML BODY ──
                try {
                    const body = rightDoc.body;
                    if (body) {
                        body.style.zoom = self.zoomFactor;
                    }
                } catch (e) { }

                // ── DYNAMIC LOCALES TRANSLATION FOR GLASS OVERLAYS ──
                try {
                    rightDoc.querySelectorAll('[id^="glass-overlay-t-"]').forEach(glass => {
                        const textElement = glass.querySelector('p');
                        if (textElement) {
                            // Translates the hardcoded wait overlay dynamically into French or English
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
        }
    };
}