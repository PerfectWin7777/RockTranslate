"""
domain.py — Document Object Model (DOM) de RockTranslate
Hiérarchie : RawObject → Span → Line → Block → Paragraph → Page → Document
"""

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────
# Niveau 0 : objet brut issu de PDFium
# ─────────────────────────────────────────────

@dataclass
class RawObject:
    """
    Représente un objet texte atomique extrait directement de PDFium.
    Un 'objet' peut être une lettre, un accent, un exposant, un mot court.
    """
    text: str
    left: float
    bottom: float
    right: float
    top: float
    font_size: float
    color: tuple[int, int, int]  # (r, g, b)
    matrix: tuple[float, float, float, float, float, float]  # (a,b,c,d,e,f)
    font_name: str = "Serif"
    font_weight: int = 400
    is_italic: bool = False
    bg_color: tuple[int, int, int] = (255, 255, 255)

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2

    @property
    def y_center(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def width(self) -> float:
        return self.right - self.left

    @property
    def height(self) -> float:
        return abs(self.top - self.bottom)


# ─────────────────────────────────────────────
# Niveau 1 : Span — groupe de fragments proches
# ─────────────────────────────────────────────

@dataclass
class Span:
    """
    Groupe de RawObjects proches en X sur la même ligne Y.
    Représente généralement un mot ou un groupe de mots.
    """
    text: str
    left: float
    bottom: float
    right: float
    top: float
    font_size: float
    color: tuple = (0, 0, 0)
    raw_objects: list[RawObject] = field(default_factory=list)
    
    @property
    def height(self) -> float:
        return abs(self.top - self.bottom)

    @property
    def width(self) -> float:
        return abs(self.right - self.left)
    
    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2

    @property
    def y_center(self) -> float:
        return (self.bottom + self.top) / 2

    @classmethod
    def from_raw_objects(cls, objects: list[RawObject]) -> "Span":
        """Construit un Span à partir d'une liste de RawObjects triés par X."""
        text = " ".join(o.text for o in objects if o.text.strip())
        left   = min(o.left   for o in objects)
        bottom = min(o.bottom for o in objects)
        right  = max(o.right  for o in objects)
        top    = max(o.top    for o in objects)
        font_size = max(o.font_size for o in objects)
        color = objects[0].color if objects else (0, 0, 0) 
        return cls(
            text=text,
            left=left, bottom=bottom, right=right, top=top,
            font_size=font_size,
            color=color,
            raw_objects=objects
        )


# ─────────────────────────────────────────────
# Niveau 2 : Line — spans alignés sur même Y
# ─────────────────────────────────────────────

@dataclass
class Line:
    """
    Ensemble de Spans qui partagent la même position verticale (même ligne de texte).
    Les spans sont triés par X croissant (gauche → droite).
    """
    spans: list[Span]
    left: float
    bottom: float
    right: float
    top: float

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.spans if s.text.strip())

    @property
    def y_center(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def height(self) -> float:
        return abs(self.top - self.bottom)

    @property
    def font_size(self) -> float:
        if not self.spans:
            return 10.0
        return max(s.font_size for s in self.spans)

    @property
    def color(self) -> tuple:
        if not self.spans:
            return (0, 0, 0)
        return self.spans[0].color   


    @classmethod
    def from_spans(cls, spans: list[Span]) -> "Line":
        """Construit une Line à partir d'une liste de Spans (triés par X)."""
        sorted_spans = sorted(spans, key=lambda s: s.left)
        left   = min(s.left   for s in spans)
        bottom = min(s.bottom for s in spans)
        right  = max(s.right  for s in spans)
        top    = max(s.top    for s in spans)
        return cls(
            spans=sorted_spans,
            left=left, bottom=bottom, right=right, top=top
        )


# ─────────────────────────────────────────────
# Niveau 3 : Block — lignes consécutives
# ─────────────────────────────────────────────

@dataclass
class Block:
    """
    Groupe de Lines consécutives avec un faible gap vertical entre elles.
    Représente un paragraphe visuel ou un titre.
    """
    lines: list[Line]
    left: float
    bottom: float
    right: float
    top: float
    column: int = 0          # 0 = colonne unique, 1 = gauche, 2 = droite
    page_number: int = 0
    is_title: bool = False
    continues_on_next_page: bool = False   # ← phrase coupée cross-page
    continued_from_prev_page: bool = False
    
    line_height_ratio: float = 1.2  # Mesuré géométriquement
    bg_color: tuple[int, int, int] = (255, 255, 255) # Détecté via les Paths
    alignment: str = "left" # Détecté via la largeur et position

    @property
    def text(self) -> str:
        return " ".join(line.text for line in self.lines if line.text.strip())

    @property
    def x_center(self) -> float:
        return (self.left + self.right) / 2

    @property
    def y_center(self) -> float:
        return (self.bottom + self.top) / 2

    @property
    def color(self) -> tuple:
        if not self.lines:
            return (0, 0, 0)
        # Vote par nombre de caractères par couleur
        from collections import Counter
        char_counts: Counter = Counter()
        for line in self.lines:
            for span in line.spans:
                for obj in span.raw_objects:
                    char_counts[obj.color] += len(obj.text)
        if not char_counts:
            return (0, 0, 0)
        return char_counts.most_common(1)[0][0]


    @property
    def last_line_text(self) -> str:
        """Dernière ligne du bloc — pour détecter coupure cross-page."""
        if self.lines:
            return self.lines[-1].text
        return ""

    @property
    def first_line_text(self) -> str:
        """Première ligne du bloc — pour détecter suite cross-page."""
        if self.lines:
            return self.lines[0].text
        return ""

    @classmethod
    def from_lines(cls, lines: list[Line], page_number: int = 0) -> "Block":
        left   = min(l.left   for l in lines)
        bottom = min(l.bottom for l in lines)
        right  = max(l.right  for l in lines)
        top    = max(l.top    for l in lines)
        return cls(
            lines=lines,
            left=left, bottom=bottom, right=right, top=top,
            page_number=page_number
        )


# ─────────────────────────────────────────────
# Niveau 4 : Paragraph — unité envoyée au LLM
# ─────────────────────────────────────────────

@dataclass
class Paragraph:
    """
    Unité logique finale envoyée au LLM pour traduction.
    Peut regrouper plusieurs Blocks (ex: phrase cross-page).
    Contient aussi le texte traduit une fois la traduction reçue.
    """
    blocks: list[Block]
    text: str
    left: float
    bottom: float
    right: float
    top: float
    column: int = 0
    page_number: int = 0
    translated_text: Optional[str] = None     # ← rempli après LLM
    is_cross_page: bool = False               # ← vrai si span sur 2 pages
    skip_translation: bool = False

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return (self.left, self.bottom, self.right, self.top)

    @classmethod
    def from_blocks(cls, blocks: list[Block]) -> "Paragraph":
        """Fusionne plusieurs blocs en un seul paragraphe."""
        text   = " ".join(b.text for b in blocks if b.text.strip())
        left   = min(b.left   for b in blocks)
        bottom = min(b.bottom for b in blocks)
        right  = max(b.right  for b in blocks)
        top    = max(b.top    for b in blocks)
        column = blocks[0].column if blocks else 0
        page   = blocks[0].page_number if blocks else 0
        cross  = any(b.continues_on_next_page or b.continued_from_prev_page
                     for b in blocks)
        return cls(
            blocks=blocks,
            text=text,
            left=left, bottom=bottom, right=right, top=top,
            column=column,
            page_number=page,
            is_cross_page=cross
        )


# ─────────────────────────────────────────────
# Niveau 5 : Page et Document
# ─────────────────────────────────────────────

@dataclass
class Page:
    """Représente une page du document avec ses paragraphes dans l'ordre de lecture."""
    number: int
    width: float
    height: float
    paragraphs: list[Paragraph] = field(default_factory=list)
    raw_objects: list[RawObject] = field(default_factory=list)


@dataclass
class Document:
    """Document complet. Point d'entrée de tout le pipeline RockTranslate."""
    path: str
    pages: list[Page] = field(default_factory=list)

    @property
    def all_paragraphs(self) -> list[Paragraph]:
        """Tous les paragraphes de toutes les pages dans l'ordre."""
        return [p for page in self.pages for p in page.paragraphs]