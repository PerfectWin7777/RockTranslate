# test_split_viewer.py

import sys
import os
import zipfile
import tempfile
import shutil
import urllib.request
import fitz  # PyMuPDF
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog, QStatusBar
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl, QTimer
from PyQt6.QtGui import QKeySequence, QAction, QActionGroup

# ── 1. TÉLÉCHARGEMENT AUTOMATIQUE DE PDF.JS (Évite l'installation manuelle) ──
def check_and_download_pdfjs():
    pdfjs_dir = os.path.abspath("./pdfjs")
    if not os.path.exists(pdfjs_dir):
        print("📥 Dossier './pdfjs' introuvable.")
        print("📥 Téléchargement automatique de PDF.js (v3.11.174)...")
        
        url = "https://github.com/mozilla/pdf.js/releases/download/v3.11.174/pdfjs-3.11.174-dist.zip"
        zip_path = os.path.abspath("./pdfjs.zip")
        
        try:
            def progress(count, block_size, total_size):
                percent = int(count * block_size * 100 / total_size)
                sys.stdout.write(f"\rTéléchargement : {min(percent, 100)}%")
                sys.stdout.flush()
                
            urllib.request.urlretrieve(url, zip_path, reporthook=progress)
            print("\n📦 Extraction des fichiers de rendu...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(pdfjs_dir)
            os.remove(zip_path)
            print("✅ Configuration locale de PDF.js terminée avec succès !")
        except Exception as e:
            print(f"\n❌ Échec du téléchargement automatique : {e}")
            sys.exit(1)


class TestSplitViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockTranslate - Prototype Haute Fidélité")
        self.resize(1400, 950)
        
        self._zoom = 1.0
        self._temp_dir = None
        self._pdf_path = None
        self.temp_file = None
        self._extracted_pages = []
        
        # Initialisation du navigateur unique
        self.view = QWebEngineView(self)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)
        
        self.setCentralWidget(self.view)
        
        # Barre d'état
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        
        # Construction de la barre de menus identique à l'originale
        self._build_menu()
        
        # Chargement automatique du PDF spécifié
        target_pdf_name = "5_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf"
        initial_pdf = os.path.abspath(target_pdf_name)
        
        if os.path.exists(initial_pdf):
            self._load_document(initial_pdf)
        else:
            fallback_pdfs = [f for f in os.listdir(".") if f.lower().endswith(".pdf")]
            if fallback_pdfs:
                self._load_document(os.path.abspath(fallback_pdfs[0]))
                print(f"⚠️ Fichier spécifié introuvable. Sélection automatique de : {fallback_pdfs[0]}")
            else:
                self.status.showMessage("En attente de chargement. Allez dans Fichier -> Ouvrir PDF...")

    # ── 2. LOGIQUE DE GESTION DU MENU PYQT ──
    def _build_menu(self):
        mb = self.menuBar()

        # ── Fichier ──
        m_file = mb.addMenu("Fichier")

        a_open = QAction("Ouvrir PDF…", self)
        a_open.setShortcut(QKeySequence("Ctrl+O"))
        a_open.triggered.connect(self._open_pdf_dialog)
        m_file.addAction(a_open)

        self.a_close = QAction("Fermer le document", self)
        self.a_close.triggered.connect(self._close_document)
        m_file.addAction(self.a_close)

        m_file.addSeparator()

        a_quit = QAction("Quitter", self)
        a_quit.triggered.connect(self.close)
        m_file.addAction(a_quit)

        # ── Affichage ──
        m_view = mb.addMenu("Affichage")

        self.a_zoom_in = QAction("Zoom +", self)
        self.a_zoom_in.setShortcut(QKeySequence("Ctrl+="))
        self.a_zoom_in.triggered.connect(self.zoom_in)
        m_view.addAction(self.a_zoom_in)

        self.a_zoom_out = QAction("Zoom −", self)
        self.a_zoom_out.setShortcut(QKeySequence("Ctrl+-"))
        self.a_zoom_out.triggered.connect(self.zoom_out)
        m_view.addAction(self.a_zoom_out)

        self.a_zoom_reset = QAction("Zoom 100%", self)
        self.a_zoom_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.a_zoom_reset.triggered.connect(self.zoom_reset)
        m_view.addAction(self.a_zoom_reset)

        m_view.addSeparator()

        self.a_fullscreen = QAction("Plein écran", self, checkable=True)
        self.a_fullscreen.setShortcut(QKeySequence("F11"))
        self.a_fullscreen.triggered.connect(self.toggle_fullscreen)
        m_view.addAction(self.a_fullscreen)

        m_view.addSeparator()

        # Groupe d'actions mutuellement exclusives (Boutons radio) pour la disposition
        self.layout_group = QActionGroup(self)

        self.a_layout_both = QAction("Afficher les deux côte-à-côte", self, checkable=True)
        self.a_layout_both.setShortcut(QKeySequence("Ctrl+3"))
        self.a_layout_both.setChecked(True)
        self.a_layout_both.triggered.connect(self._apply_layout_both)
        self.layout_group.addAction(self.a_layout_both)
        m_view.addAction(self.a_layout_both)

        self.a_layout_pdf = QAction("Afficher uniquement l'original (PDF)", self, checkable=True)
        self.a_layout_pdf.setShortcut(QKeySequence("Ctrl+1"))
        self.a_layout_pdf.triggered.connect(self._apply_layout_pdf_only)
        self.layout_group.addAction(self.a_layout_pdf)
        m_view.addAction(self.a_layout_pdf)

        self.a_layout_trans = QAction("Afficher uniquement la traduction", self, checkable=True)
        self.a_layout_trans.setShortcut(QKeySequence("Ctrl+2"))
        self.a_layout_trans.triggered.connect(self._apply_layout_trans_only)
        self.layout_group.addAction(self.a_layout_trans)
        m_view.addAction(self.a_layout_trans)

    # ── 3. CHARGEMENT ET DOUBLE EXTRACTION DU DOCUMENT (ORIGINAL ET BLANCHI) ──
    def _load_document(self, pdf_path: str):
        self._close_document()
        
        self._pdf_path = pdf_path
        self._temp_dir = tempfile.mkdtemp()
        
        self.status.showMessage("⚙️ Extraction géométrique et masquage du PDF d'origine...")
        
        # Extraction géométrique du texte et génération des fonds blanchis (blanked)
        self._extracted_pages = self.extract_pdf_pages_and_blank()
        
        self.status.showMessage("Génération de l'espace de travail unifié...")
        self.load_workspace()
        self.status.showMessage(f"Document chargé : {os.path.basename(pdf_path)}")

    def extract_pdf_pages_and_blank(self) -> list:
        doc = fitz.open(self._pdf_path)
        pages_data = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            
            # Matrice de rotation pour s'assurer que les coordonnées s'adaptent aux pages Paysage
            rot_matrix = page.rotation_matrix
            
            # Étape 1 : Extraction géométrique du texte d'origine
            text_dict = page.get_text("dict")
            lines_data = []
            
            for b in text_dict.get("blocks", []):
                if b.get("type") != 0:
                    continue
                for l in b.get("lines", []):
                    # Application de la matrice de rotation sur le rectangle de la ligne
                    l_rect = fitz.Rect(l["bbox"]) * rot_matrix
                    lx0, ly0, lx1, ly1 = l_rect.x0, l_rect.y0, l_rect.x1, l_rect.y1
                    
                    spans_text = []
                    font_size = 9.0
                    color_css = "rgb(0,0,0)"
                    is_bold = False
                    is_italic = False
                    
                    for s in l.get("spans", []):
                        spans_text.append(s.get("text", ""))
                        font_size = s.get("size", 9.0)
                        font_name = s.get("font", "").lower()
                        flags = s.get("flags", 0)
                        
                        is_bold = bool(flags & 16) or any(x in font_name for x in ["bold", "black", "heavy", "-b"])
                        is_italic = bool(flags & 2) or any(x in font_name for x in ["italic", "oblique", "-i"])
                        
                        color_int = s.get("color", 0)
                        r = (color_int >> 16) & 0xFF
                        g = (color_int >> 8)  & 0xFF
                        b_val = color_int     & 0xFF
                        color_css = f"rgb({r},{g},{b_val})"
                        
                    line_text = " ".join(spans_text).strip()
                    if line_text:
                        lines_data.append({
                            "text": line_text,
                            "left": lx0,
                            "top": ly0,
                            "width": lx1 - lx0,
                            "height": ly1 - ly0,
                            "font_size": font_size,
                            "color": color_css,
                            "is_bold": is_bold,
                            "is_italic": is_italic
                        })
            
            # Étape 2 : Blanchiment des mots de la page d'origine
            for word in page.get_text("words"):
                word_rect = fitz.Rect(word[0], word[1], word[2], word[3])
                # Dessiner un rectangle blanc opaque par-dessus le mot d'origine
                page.draw_rect(word_rect, color=(1, 1, 1), fill=(1, 1, 1))
            
            # Étape 3 : Rendu de la page modifiée (blanchie) en image PNG
            pix = page.get_pixmap(dpi=150) # get_pixmap gère nativement l'orientation
            img_path = os.path.join(self._temp_dir, f"bg_blanked_{page_num:03d}.png").replace("\\", "/")
            pix.save(img_path)
            
            pages_data.append({
                "number": page_num,
                "width": page.rect.width,  # page.rect prend en compte le pivotement
                "height": page.rect.height,
                "bg_image": img_path,
                "lines": lines_data
            })
            
        doc.close()
        return pages_data

    def load_workspace(self):
        pdfjs_viewer_path = os.path.abspath("./pdfjs/web/viewer.html").replace("\\", "/")
        pdf_target_path = self._pdf_path.replace("\\", "/")
        
        iframe_src = f"file:///{pdfjs_viewer_path}?file=file:///{pdf_target_path}"

        right_pages_html = ""
        for page in self._extracted_pages:
            p_num = page["number"]
            w = page["width"]
            h = page["height"]
            bg = page["bg_image"]
            
            lines_html = ""
            for line in page["lines"]:
                safe_text = line["text"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                
                # Calque de texte positionné de manière absolue sur l'image d'origine
                lines_html += (
                    f'<div class="line-div" style="'
                    f'left: {line["left"]:.1f}px; '
                    f'top: {line["top"]:.1f}px; '
                    f'width: {line["width"]:.1f}px; '
                    f'height: {line["height"]:.1f}px; '
                    f'font-size: {line["font_size"]:.1f}px; '
                    f'color: {line["color"]}; '
                    f'font-weight: {"bold" if line["is_bold"] else "normal"}; '
                    f'font-style: {"italic" if line["is_italic"] else "normal"};'
                    f'">{safe_text}</div>\n'
                )
                
            right_pages_html += f"""
            <div class="page-box" id="page-{p_num}" style="
                width: {w:.1f}px;
                height: {h:.1f}px;
                background-image: url('file:///{bg}');
            ">
                {lines_html}
            </div>
            """

        html_content = f"""<!DOCTYPE html>
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
            width: 6px; height: 100%; background: #2b2e3c; cursor: col-resize;
            position: relative; z-index: 100; transition: background 0.15s;
        }}
        #splitter:hover, #splitter.active {{
            background: #4f8ef7;
        }}
        #right-pane {{
            overflow-y: auto; background: #2b2e3c;
            padding: 24px; box-sizing: border-box; scroll-behavior: smooth;
        }}
        iframe {{
            width: 100%; height: 100%; border: none;
        }}
        #workspace.dragging iframe {{
            pointer-events: none !important;
        }}
        .page-box {{
            background-color: white;
            background-repeat: no-repeat;
            background-size: 100% 100%;
            margin-bottom: 24px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            position: relative;
            user-select: text;
        }}
        .line-div {{
            position: absolute;
            white-space: nowrap;
            background: transparent;
            display: flex;
            align-items: center;
            transform-origin: left top;
        }}
    </style>
</head>
<body>
    <div id="workspace">
        <div id="left-pane" class="pane">
            <iframe id="pdf-iframe" src="{iframe_src}"></iframe>
        </div>
        
        <div id="splitter"></div>
        
        <div id="right-pane" class="pane">
            {right_pages_html}
        </div>
    </div>

    <script>
        var iframe = document.getElementById('pdf-iframe');
        var isSyncing = false;
        var lastSyncedPage = 0;
        var isPDFLoaded = false;

        // ── 1. LOGIQUE DU SPLITTER (SÉPARATEUR) ──
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

        // ── 2. LOGIQUE D'AFFICHAGE EXCLUSIF (SET LAYOUT VIA PYQT) ──
        function setPaneLayout(layout) {{
            var leftPane = document.getElementById('left-pane');
            var rightPane = document.getElementById('right-pane');
            var splitter = document.getElementById('splitter');
            var workspace = document.getElementById('workspace');
            
            if (layout === 'both') {{
                splitter.style.display = 'block';
                workspace.style.gridTemplateColumns = '50% 6px 1fr';
            }} else if (layout === 'pdf_only') {{
                splitter.style.display = 'none';
                workspace.style.gridTemplateColumns = '100% 0px 0px';
            }} else if (layout === 'trans_only') {{
                splitter.style.display = 'none';
                workspace.style.gridTemplateColumns = '0px 0px 100%';
            }}
        }}

        // ── 3. SYNCHRONISATION : GAUCHE (PDF) VERS DROITE (HTML) ──
        function syncPDFToHTML(pageIndex) {{
            if (isSyncing || !isPDFLoaded) return;
            isSyncing = true;
            
            var targetPage = document.getElementById('page-' + pageIndex);
            if (targetPage) {{
                targetPage.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
            }}
            
            setTimeout(function() {{ isSyncing = false; }}, 450);
        }}

        iframe.onload = function() {{
            var iframeWin = iframe.contentWindow;
            
            var checkInterval = setInterval(function() {{
                try {{
                    if (iframeWin.PDFViewerApplication && iframeWin.PDFViewerApplication.eventBus) {{
                        
                        // Sécurité : Vérification si le PDF d'origine est déjà chargé
                        if (iframeWin.PDFViewerApplication.pdfDocument) {{
                            clearInterval(checkInterval);
                            isPDFLoaded = true;
                            console.log("✅ PDF prêt au chargement !");
                        }}

                        // Sécurité : Attente de l'événement de fin d'initialisation
                        iframeWin.PDFViewerApplication.eventBus.on('documentloaded', function() {{
                            clearInterval(checkInterval);
                            isPDFLoaded = true;
                            console.log("✅ PDF chargé avec succès !");
                        }});

                        // Écoute de l'événement de changement de page
                        iframeWin.PDFViewerApplication.eventBus.on('pagechanging', function(evt) {{
                            var pageIndex = evt.pageNumber - 1; // 0-based
                            if (pageIndex !== lastSyncedPage && !isSyncing && isPDFLoaded) {{
                                lastSyncedPage = pageIndex;
                                syncPDFToHTML(pageIndex);
                            }}
                        }});
                    }}
                }} catch(e) {{
                    console.error("Attente de PDF.js : ", e);
                }}
            }}, 100);
        }};

        // ── 4. SYNCHRONISATION : DROITE (HTML) VERS GAUCHE (PDF) ──
        var rightPane = document.getElementById('right-pane');
        rightPane.addEventListener('scroll', function() {{
            if (isSyncing || !isPDFLoaded) return;
            
            var pages = document.querySelectorAll('.page-box');
            var maxVisible = 0;
            var currentIdx = 0;
            var paneHeight = rightPane.clientHeight;

            pages.forEach(function(page, index) {{
                var rect = page.getBoundingClientRect();
                
                // Intersection mathématique haute précision
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
                    if (iframe.contentWindow.PDFViewerApplication) {{
                        iframe.contentWindow.PDFViewerApplication.page = currentIdx + 1; // 1-based
                    }}
                }} catch(e) {{}}
                
                setTimeout(function() {{ isSyncing = false; }}, 450);
            }}
        }});
    </script>
</body>
</html>"""

        self.temp_file = tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8")
        self.temp_file.write(html_content)
        self.temp_file.close()
        
        self.view.load(QUrl.fromLocalFile(self.temp_file.name))

    # ── LOGIQUE DES ACTIONS DE MENU D'AFFICHAGE EXCLUSIF ──
    def _apply_layout_both(self):
        self.view.page().runJavaScript("setPaneLayout('both');")
        self.status.showMessage("Affichage : Vue partagée côte-à-côte.")

    def _apply_layout_pdf_only(self):
        self.view.page().runJavaScript("setPaneLayout('pdf_only');")
        self.status.showMessage("Affichage : Original (PDF) uniquement.")

    def _apply_layout_trans_only(self):
        self.view.page().runJavaScript("setPaneLayout('trans_only');")
        self.status.showMessage("Affichage : Traduction uniquement.")

    # ── LOGIQUE DES RACCOURCIS DE ZOOM ──
    def zoom_in(self):
        self._zoom = min(2.5, self._zoom + 0.1)
        self.view.setZoomFactor(self._zoom)

    def zoom_out(self):
        self._zoom = max(0.5, self._zoom - 0.1)
        self.view.setZoomFactor(self._zoom)

    def zoom_reset(self):
        self._zoom = 1.0
        self.view.setZoomFactor(self._zoom)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.a_fullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.a_fullscreen.setChecked(True)

    # ── LOGIQUE FICHIER ──
    def _open_pdf_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", "", "PDF (*.pdf)")
        if path:
            self._load_document(path)

    def _close_document(self):
        self.view.load(QUrl("about:blank"))
        self._pdf_path = None
        self._extracted_pages = []
        
        # Nettoyage des dossiers temporaires
        if self.temp_file and os.path.exists(self.temp_file.name):
            try:
                os.unlink(self.temp_file.name)
            except Exception:
                pass
            self.temp_file = None
            
        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir)
            except Exception:
                pass
            self._temp_dir = None
            
        self.status.showMessage("Document clos.")

    def closeEvent(self, event):
        self._close_document()
        super().closeEvent(event)


if __name__ == "__main__":
    # Étape 1 : Téléchargement et installation automatique transparente de PDF.js si absent
    check_and_download_pdfjs()
    
    # Étape 2 : Lancement de l'application PyQt6
    app = QApplication(sys.argv)
    window = TestSplitViewer()
    window.show()
    sys.exit(app.exec())