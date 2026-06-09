# ui_pyqt/workspace_viewer.py

import os
import json
import tempfile
import shutil
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl

class WorkspaceViewer(QWebEngineView):
    """
    Composant d'affichage unifié et performant (moteur Chromium unique).
    
    Héberge deux panneaux synchronisés de manière bilatérale :
      - À gauche : Le PDF original rendu par PDF.js (Mozilla) [1.1.2].
      - À droite : La traduction HTML dynamique gérée par html_transformer [1.1.2].
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._temp_dir = tempfile.mkdtemp()
        self._temp_workspace_path = None
        self._zoom_factor = 1.0
        
        # Configuration stricte de sécurité pour autoriser la communication locale inter-iframes
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

    def load_document(self, pdf_path: str, instrumented_html_path: str, pdfjs_dir_path: str):
        """
        Génère la page maîtresse de l'espace de travail et la charge dans Chromium.
        """
        self.cleanup_temp_files()

        # Nettoyage et formatage des chemins pour Chromium
        pdfjs_viewer = os.path.abspath(os.path.join(pdfjs_dir_path, "web/viewer.html")).replace("\\", "/")
        safe_pdf = os.path.abspath(pdf_path).replace("\\", "/")
        safe_html = os.path.abspath(instrumented_html_path).replace("\\", "/")

        # CORRECTIF CHIRURGICAL : Ajout de #pagemode=none pour masquer le volet latéral PDF.js par défaut !
        left_iframe_src = f"file:///{pdfjs_viewer}?file=file:///{safe_pdf}#pagemode=none"
        right_iframe_src = f"file:///{safe_html}"

        # Construction du template HTML maître avec séparation de la grille et du scroll synchrone
        master_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body, html {{
            margin: 0; padding: 0; width: 100%; height: 100%;
            overflow: hidden; font-family: 'Segoe UI', sans-serif;
            background: #1e202c;
            user-select: none;
        }}
        #workspace {{
            display: grid;
            grid-template-columns: 50% 6px 1fr;
            width: 100%;
            height: 100%;
            position: relative;
        }}
        .pane {{
            height: 100%; overflow: hidden; position: relative;
        }}
        #splitter {{
            width: 8px; height: 100%; background: #fafafc; cursor: col-resize;
            border: 1px; border-radius: 4px; border-color: #15151a; border-style: solid;
            position: relative; z-index: 100; transition: background 0.15s;
        }}
        #splitter:hover, #splitter.active {{
            background: #4f8ef7;
        }}
        iframe {{
            width: 100%; height: 100%; border: none;
        }}
        #workspace.dragging iframe {{
            pointer-events: none !important;
        }}
    </style>
</head>
<body>
    <div id="workspace">
        <div id="left-pane" class="pane">
            <iframe id="pdf-iframe" src="{left_iframe_src}"></iframe>
        </div>
        
        <div id="splitter"></div>
        
        <div id="right-pane" class="pane">
            <iframe id="html-iframe" src="{right_iframe_src}"></iframe>
        </div>
    </div>

    <script>
        var leftIframe = document.getElementById('pdf-iframe');
        var rightIframe = document.getElementById('html-iframe');
        var isSyncing = false;
        var lastSyncedPage = 0;
        var isPDFLoaded = false;

        // ── 1. LOGIQUE DU SPLITTER INTERNE (SÉPARATEUR) ──
        var splitter = document.getElementById('splitter');
        var workspace = document.getElementById('workspace');
        var isDragging = false;

        splitter.addEventListener('mousedown', function(e) {{
            isDragging = true;
            workspace.classList.add('dragging');
            splitter.classList.add('active');
            document.body.style.cursor = 'col-resize';
        }});

        document.addEventListener('mousemove', function(e) {{
            if (!isDragging) return;
            var containerWidth = workspace.clientWidth;
            var percentage = (e.clientX / containerWidth) * 100;
            
            if (percentage > 15 && percentage < 85) {{
                workspace.style.gridTemplateColumns = percentage + '% 6px 1fr';
            }}
        }});

        document.addEventListener('mouseup', function() {{
            if (isDragging) {{
                isDragging = false;
                workspace.classList.remove('dragging');
                splitter.classList.remove('active');
                document.body.style.cursor = 'default';
            }}
        }});

        // ── 2. CORRECTIF DISPOSITION EXCLUSIVE : MASQUAGE PROPRE DES COLONNES ET RE-AJUSTEMENT GRID 1FR ──
        function setPaneLayout(layout) {{
            var leftPane = document.getElementById('left-pane');
            var rightPane = document.getElementById('right-pane');
            var splitter = document.getElementById('splitter');
            var workspace = document.getElementById('workspace');
            
            if (layout === 'both') {{
                leftPane.style.display = 'block';
                rightPane.style.display = 'block';
                splitter.style.display = 'block';
                workspace.style.gridTemplateColumns = '50% 6px 1fr';
            }} else if (layout === 'pdf_only') {{
                leftPane.style.display = 'block';
                rightPane.style.display = 'none';
                splitter.style.display = 'none';
                workspace.style.gridTemplateColumns = '1fr';
            }} else if (layout === 'trans_only') {{
                leftPane.style.display = 'none';
                rightPane.style.display = 'block';
                splitter.style.display = 'none';
                workspace.style.gridTemplateColumns = '1fr';
            }}
        }}

        // ── 3. SYNCHRONISATION : GAUCHE (PDF) VERS DROITE (HTML) ──
        function syncPDFToHTML(pageIndex) {{
            if (isSyncing || !isPDFLoaded) return;
            isSyncing = true;
            
            try {{
                var rightDoc = rightIframe.contentWindow;
                var pageHex = (pageIndex + 1).toString(16);
                var targetPage = rightDoc.document.getElementById('pf' + pageHex);
                
                if (!targetPage) {{
                    var pages = rightDoc.document.querySelectorAll('.pf');
                    if (pages[pageIndex]) {{
                        targetPage = pages[pageIndex];
                    }}
                }}
                
                if (targetPage) {{
                    targetPage.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                }}
            }} catch(e) {{
                console.error("Erreur synchro Gauche->Droite :", e);
            }}
            
            setTimeout(function() {{ isSyncing = false; }}, 450);
        }}

        leftIframe.onload = function() {{
            var iframeWin = leftIframe.contentWindow;
            
            var checkInterval = setInterval(function() {{
                try {{
                    if (iframeWin.PDFViewerApplication && iframeWin.PDFViewerApplication.eventBus) {{
                        if (iframeWin.PDFViewerApplication.pdfDocument) {{
                            clearInterval(checkInterval);
                            isPDFLoaded = true;
                            iframeWin.PDFViewerApplication.pdfViewer.currentScaleValue = "50%";
                        }}

                        iframeWin.PDFViewerApplication.eventBus.on('documentloaded', function() {{
                            clearInterval(checkInterval);
                            isPDFLoaded = true;
                        }});

                        iframeWin.PDFViewerApplication.eventBus.on('pagechanging', function(evt) {{
                            var pageIndex = evt.pageNumber - 1; // 0-based
                            if (pageIndex !== lastSyncedPage && !isSyncing && isPDFLoaded) {{
                                lastSyncedPage = pageIndex;
                                syncPDFToHTML(pageIndex);
                            }}
                        }});
                    }}
                }} catch(e) {{}}
            }}, 100);
        }};

        // ── 4. CORRECTIF SYNCHRONISATION : ÉCOUTE DU SCROLL SUR LE CONTAINER NATION-SCALE DE pdf2htmlEX ──
        rightIframe.onload = function() {{
            var rightDocWindow = rightIframe.contentWindow;
            
            // C'est l'élément #page-container de pdf2htmlEX qui scrolle réellement, pas rightDocWindow !
            var scrollContainer = rightDocWindow.document.getElementById('page-container') || rightDocWindow;
            
            scrollContainer.addEventListener('scroll', function() {{
                if (isSyncing || !isPDFLoaded) return;
                
                var pages = rightDocWindow.document.querySelectorAll('.pf');
                var maxVisible = 0;
                var currentIdx = 0;
                var paneHeight = rightIframe.clientHeight; // Hauteur visible du conteneur parent

                pages.forEach(function(page, index) {{
                    var rect = page.getBoundingClientRect();
                    // Intersection mathématique géométrique dans le viewport de l'iframe
                    var visibleHeight = Math.max(0, Math.min(rect.bottom, paneHeight) - Math.max(rect.top, 0));
                    
                    if (visibleHeight > maxVisible) {{
                        maxVisible = visibleHeight;
                        currentIdx = index;
                    }}
                }});

                if (currentIdx !== lastSyncedPage) {{
                    lastSyncedPage = currentIdx;
                    isSyncing = true;
                    
                    try {{
                        if (leftIframe.contentWindow.PDFViewerApplication) {{
                            leftIframe.contentWindow.PDFViewerApplication.page = currentIdx + 1; // 1-based
                        }}
                    }} catch(e) {{}}
                    
                    setTimeout(function() {{ isSyncing = false; }}, 450);
                }}
            }});
        }};
    </script>
</body>
</html>"""

        # Enregistrement du fichier d'espace de travail temporaire
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8", dir=self._temp_dir) as f:
            f.write(master_html)
            self._temp_workspace_path = f.name

        self.load(QUrl.fromLocalFile(self._temp_workspace_path))

    def stream_translation(self, trans_id: str, translated_text: str):
        """
        Injecte chirurgicalement une traduction en l'écrivant progressivement
        à l'intérieur de l'iframe de droite.
        """
        self._run_js_in_right_iframe({
            "action": "applyTranslation",
            "transId": trans_id,
            "translatedText": translated_text,
        })
    

    def prepare_page(self, page_idx: int):
        """
        Enlève le glass et active les skeletons sur une page spécifique.
        Appelé depuis main_window dès qu'on détecte un nouveau page_idx.
        """
        self._run_js_in_right_iframe({
            "action": "preparePage",
            "pageIdx": page_idx
        })
   

    def _run_js_in_right_iframe(self, js_code_as_msg_dict: str):
        """
        xécute du JS directement dans la page de l'iframe droite via Qt.
        Envoie un message structuré à l'iframe de droite de façon sécurisée.
        """
        # On convertit notre dictionnaire Python en JSON lisible par le JS du parent
        msg_json = json.dumps(js_code_as_msg_dict)
        
        # Le document parent cible l'iframe et lui envoie le message
        self.page().runJavaScript(f"""
            (function() {{
                var iframe = document.getElementById('html-iframe');
                if (iframe && iframe.contentWindow) {{
                    iframe.contentWindow.postMessage({msg_json}, '*');
                }}
            }})();
        """)


    def set_pane_layout(self, layout_mode: str):
        """Configure la disposition visuelle (both / pdf_only / trans_only)."""
        self.page().runJavaScript(f"setPaneLayout('{layout_mode}');")
    
    def set_zoom(self, zoom_factor: float):
        """Force le zoom de manière standard et via l'API interne du viewport de Chrome."""
        self._zoom_factor = zoom_factor
        self.setZoomFactor(zoom_factor)

    def cleanup_temp_files(self):
        """Nettoie les anciens fichiers de l'espace de travail temporaire."""
        if self._temp_workspace_path and os.path.exists(self._temp_workspace_path):
            try:
                os.unlink(self._temp_workspace_path)
            except Exception:
                pass
            self._temp_workspace_path = None

    def closeEvent(self, event):
        self.cleanup_temp_files()
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                pass
        super().closeEvent(event)