# src/ui_pyqt/widget/properties_dialog.py

from PyQt6.QtWidgets import QDialog, QTabWidget, QWidget, QFormLayout, QLabel, QVBoxLayout, QDialogButtonBox
from PyQt6.QtCore import Qt

class DocumentPropertiesDialog(QDialog):
    """
    Dialogue de propriétés complet contenant les propriétés physiques,
    les métadonnées standard et les statistiques uniques de RockTranslate.
    """
    def __init__(self, metadata: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Propriétés du document")
        self.resize(550, 420)
        self.setStyleSheet("""
            QDialog {
                background-color: #1e202c;
            }
            QTabWidget::pane {
                border: 1px solid #2d313f;
                background: #14151f;
                border-radius: 4px;
            }
            QTabBar::tab {
                background: #1e202c;
                color: #a0aec0;
                padding: 8px 16px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QTabBar::tab:selected {
                background: #14151f;
                color: #ffffff;
                border: 1px solid #2d313f;
                border-bottom-color: #14151f;
            }
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #ffffff;
            }
            QLabel[class="title"] {
                font-weight: bold;
                color: #a0aec0;
            }
        """)
        self.metadata = metadata
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)
        
        tab_widget = QTabWidget(self)
        
        # --- Onglet 1: Général ---
        tab_general = QWidget()
        layout_gen = QFormLayout(tab_general)
        layout_gen.setContentsMargins(15, 15, 15, 15)
        layout_gen.setSpacing(10)
        
        layout_gen.addRow(self._create_label("Fichier :", True), self._create_label(self.metadata["file_path"]))
        layout_gen.addRow(self._create_label("Taille du fichier :", True), self._create_label(self.metadata["file_size"]))
        layout_gen.addRow(self._create_label("Pages :", True), self._create_label(str(self.metadata["pages_count"])))
        layout_gen.addRow(self._create_label("Version PDF :", True), self._create_label(self.metadata["pdf_version"]))
        layout_gen.addRow(self._create_label("Vue Web rapide (Linearized) :", True), self._create_label(self.metadata["linearized"]))
        layout_gen.addRow(self._create_label("PDF étiqueté (Tagged) :", True), self._create_label(self.metadata["tagged"]))
        layout_gen.addRow(self._create_label("Taille de page :", True), self._create_label(self.metadata["page_size"]))
        
        tab_widget.addTab(tab_general, "Général")
        
        # --- Onglet 2: Description ---
        tab_meta = QWidget()
        layout_meta = QFormLayout(tab_meta)
        layout_meta.setContentsMargins(15, 15, 15, 15)
        layout_meta.setSpacing(10)
        
        layout_meta.addRow(self._create_label("Titre :", True), self._create_label(self.metadata["title"]))
        layout_meta.addRow(self._create_label("Sujet :", True), self._create_label(self.metadata["subject"]))
        layout_meta.addRow(self._create_label("Auteur :", True), self._create_label(self.metadata["author"]))
        layout_meta.addRow(self._create_label("Créateur :", True), self._create_label(self.metadata["creator"]))
        layout_meta.addRow(self._create_label("Émetteur (Producteur) :", True), self._create_label(self.metadata["producer"]))
        layout_meta.addRow(self._create_label("Mots-clés :", True), self._create_label(self.metadata["keywords"]))
        layout_meta.addRow(self._create_label("Créé le :", True), self._create_label(self.metadata["created_date"]))
        layout_meta.addRow(self._create_label("Dernière modification :", True), self._create_label(self.metadata["mod_date"]))
        
        tab_widget.addTab(tab_meta, "Description")
        
        # --- Onglet 3: Métadonnées uniques RockTranslate ---
        tab_custom = QWidget()
        layout_cust = QFormLayout(tab_custom)
        layout_cust.setContentsMargins(15, 15, 15, 15)
        layout_cust.setSpacing(10)
        
        layout_cust.addRow(self._create_label("Statut de traduction :", True), self._create_label(self.metadata.get("trans_status", "Non traduit")))
        layout_cust.addRow(self._create_label("Langue cible :", True), self._create_label(self.metadata.get("trans_lang", "Inconnue")))
        layout_cust.addRow(self._create_label("Modèle d'IA utilisé :", True), self._create_label(self.metadata.get("trans_model", "Aucun")))
        layout_cust.addRow(self._create_label("Blocs sémantiques traduits :", True), self._create_label(self.metadata.get("trans_segments", "0 / 0")))
        layout_cust.addRow(self._create_label("Ajustement moyen (scaleX) :", True), self._create_label(self.metadata.get("trans_scale_avg", "100.0%")))
        layout_cust.addRow(self._create_label("Date de traduction :", True), self._create_label(self.metadata.get("trans_date", "Inconnue")))
        
        tab_widget.addTab(tab_custom, "RockTranslate 💎")
        
        layout.addWidget(tab_widget)
        
        # Bouton OK standard
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok, self)
        buttons.setStyleSheet("""
            QPushButton {
                background-color: #2d313f;
                border: 1px solid #4a5568;
                border-radius: 4px;
                color: #ffffff;
                padding: 6px 16px;
                font-family: 'Segoe UI', sans-serif;
            }
            QPushButton:hover {
                background-color: #4f8ef7;
            }
        """)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _create_label(self, text: str, is_title: bool = False) -> QLabel:
        lbl = QLabel(text, self)
        if is_title:
            lbl.setProperty("class", "title")
            lbl.setFixedWidth(160)
        else:
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
        return lbl