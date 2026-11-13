"""
RockTranslate v2.0.6 — reader features, headless (no GUI, no LLM cost).

Run:  python -m pytest dev_tools/test_v206_reader.py -q

The LLM is stubbed: these tests check the plumbing (clean copy, glossary
rules, quote verification, side-by-side PDF, per-document library, bilingual
search, single instance, references detection, PDF links).
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# Isolate the user config BEFORE importing rocktranslate (its settings object
# is created at import): tests never read nor write the real settings/cache,
# whatever the order the test files run in.
import tempfile  # noqa: E402
if "rocktranslate" not in sys.modules:
    # The real locations stay known to other suites (downloaded browser...)
    os.environ.setdefault("RT_REAL_HOME", os.path.expanduser("~"))
    os.environ.setdefault("RT_REAL_LOCALAPPDATA", os.environ.get("LOCALAPPDATA", ""))
    _TMP_HOME = tempfile.mkdtemp(prefix="rt_test_home_")
    os.environ["HOME"] = _TMP_HOME
    os.environ["LOCALAPPDATA"] = _TMP_HOME

from rocktranslate.core import assist  # noqa: E402
from rocktranslate.core.chunker import reference_segment_ids, should_translate  # noqa: E402


class StubClient:
    """Answers like an LLM would, records nothing."""
    model = "stub/model"
    api_key = "x"
    custom_base_url = None
    custom_glossary = ""
    target_lang = "French"

    def __init__(self, answer):
        self.answer = answer
        self.usage = {"cost_usd": 0.0}

    def _record_usage(self, *a):
        pass


@pytest.fixture
def stub_chat(monkeypatch):
    def install(answer):
        monkeypatch.setattr(assist, "chat", lambda client, system, user, **kw: answer)
        return StubClient(answer)
    return install


def test_clean_selection_rejoins_hyphens_and_lines():
    raw = "The encoder is com-\nposed of a stack\nof layers.\n\nSecond para-\ngraph."
    assert assist.clean_selection(raw) == "The encoder is composed of a stack of layers.\n\nSecond paragraph."


def test_glossary_rules_round_trip():
    items = [{"term": "porous media", "translation": "milieux poreux", "note": ""},
             {"term": "FNO", "translation": "FNO", "note": ""}]
    rules = assist.glossary_to_rules(items)
    assert rules == "porous media -> milieux poreux\nFNO -> FNO"
    assert [i["term"] for i in assist.rules_to_glossary(rules)] == ["porous media", "FNO"]


def test_ask_keeps_only_quotes_present_in_the_paper(stub_chat):
    pages = ["Intro text.", "The trained U-FNO model generates predictions 6 x 10^4 times faster than a solver."]
    client = stub_chat(json.dumps({"answer": "60 000 fois.", "quotes": [
        {"page": 2, "quote": "The trained U-FNO model generates predictions"},
        {"page": 1, "quote": "an invented sentence that the paper never contains"},
        {"page": 1, "quote": "times faster than a solver"}]}))   # wrong page: relocated to page 2
    out = assist.ask_document(client, pages, "Combien ?")
    assert out["answer"] == "60 000 fois."
    assert out["quotes"] == [{"page": 2, "quote": "The trained U-FNO model generates predictions"},
                             {"page": 2, "quote": "times faster than a solver"}]


def test_build_glossary_parses_json(stub_chat):
    client = stub_chat('```json\n[{"term": "gas saturation", "translation": "saturation en gaz", "note": "x"}]\n```')
    assert assist.build_glossary(client, "text")[0]["translation"] == "saturation en gaz"


def test_math_operator_words_are_not_translated():
    assert not should_translate("max") and not should_translate("log")
    assert should_translate("maximum value")


def test_reference_detection_with_glued_heading_and_page_order():
    texts = {"a": "Conclusion of the study.", "b": "[2] B. Doe, 2020.", "c": "References [1] A. Smith, 2019.",
             "d": "[3] C. Roe.", "e": "App endix", "f": "Appendix text."}
    pages = {"a": 9, "b": 10, "c": 10, "d": 10, "e": 11, "f": 11}
    assert reference_segment_ids(texts, pages) == ["b", "c", "d"]


def _pdf(path, pages=2):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    with open(path, "wb") as f:
        w.write(f)
    return path


def test_side_by_side_sheets(tmp_path):
    from pypdf import PdfReader
    from rocktranslate.core.side_by_side import make_side_by_side
    original = _pdf(str(tmp_path / "o.pdf"), 3)
    translated = _pdf(str(tmp_path / "t.pdf"), 2)          # pages 2-3 of the original
    out = str(tmp_path / "sbs.pdf")
    assert make_side_by_side(original, translated, out, first_page=2) == 2
    page = PdfReader(out).pages[0]
    assert float(page.mediabox.width) > 1100 and float(page.mediabox.height) == 842


def test_library_position_highlights_and_search(tmp_path, monkeypatch):
    from rocktranslate.core.api.reader_api import ReaderApiMixin
    from rocktranslate.core.config_manager import config_db
    monkeypatch.setattr(config_db, "config_dir", tmp_path)

    class Api(ReaderApiMixin):
        _document_hash = "h1"
        _active_pdf_path = str(tmp_path / "paper.pdf")
        _original_texts = {"g-1": "The permeability field is <color_0000ff>heterogeneous</color_0000ff>.",
                           "g-2": "Another sentence."}
        _tid_to_page = {"g-1": 0, "g-2": 3}
        _translated_pages = {3: {"g-2": "Une autre phrase sur la perméabilité."}}

    api = Api()
    assert api.save_reading_position(7)
    assert api.save_reading_position(9, path=str(tmp_path / "other.pdf")) is False   # late save of another tab
    assert api.get_reading_position()["page"] == 7
    api.save_highlights([{"id": "h", "page": 2, "text": "x", "rects": [[0, 0, 1, 1]]}])
    assert api.get_highlights()[0]["id"] == "h"
    hits = api.search_document("PERMÉABILIT")           # case and accent insensitive, both languages
    assert [(h["page"], h["side"]) for h in hits] == [(1, "original"), (4, "translation")]


def test_single_instance_hand_off(tmp_path, monkeypatch):
    from rocktranslate.core import single_instance
    from rocktranslate.core.config_manager import config_db
    monkeypatch.setattr(config_db, "config_dir", tmp_path)
    assert single_instance.hand_off(["a.pdf"]) is False   # nothing running
    received = []
    single_instance.serve(received.append)
    assert single_instance.hand_off(["/x/a.pdf"]) is True
    time.sleep(0.2)
    assert received == [["/x/a.pdf"]]


def test_pdf_links_are_normalized():
    from rocktranslate.core.sources import is_url, normalize_pdf_url
    assert normalize_pdf_url("https://arxiv.org/abs/2109.03697v3") == "https://arxiv.org/pdf/2109.03697v3"
    assert normalize_pdf_url("https://openreview.net/forum?id=abc") == "https://openreview.net/pdf?id=abc"
    assert is_url("HTTPS://x.org/a.pdf") and not is_url("C:/papers/a.pdf")


def _doc(elements, size=(612.0, 792.0)):
    from rocktranslate.document import Document
    return Document(elements, "paper.pdf", {1: size})


def test_figure_regions_above_and_beside_the_caption():
    from rocktranslate.core.figures import locate_figures
    from rocktranslate.document import Element
    para = Element(type="NarrativeText", text="Body text above.", page=1, bbox=(72, 72, 540, 150))
    cap = Element(type="FigureCaption", text="Figure 1: A plot.", page=1, bbox=(72, 420, 540, 440))
    regions = locate_figures(_doc([para, cap]))
    assert len(regions) == 1
    _, page, (x0, y0, x1, y1), above = regions[0]
    assert page == 1 and above and y0 >= 150 and y1 <= 420 and x0 <= 72 and x1 >= 540

    # Side caption (narrow, left column): the figure is the empty area on its right
    side_cap = Element(type="FigureCaption", text="Figure 2. Map of the area.", page=1, bbox=(40, 80, 180, 300))
    text_below = Element(type="NarrativeText", text="Body text.", page=1, bbox=(40, 650, 560, 760))
    _, _, (x0, y0, x1, y1), _ = locate_figures(_doc([side_cap, text_below], (595.0, 842.0)))[0]
    assert x0 > 180 and x1 >= 550 and y1 <= 650 and (y1 - y0) > 400


def test_images_saved_next_to_markdown_and_json(tmp_path):
    from rocktranslate.document import Element
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    doc = _doc([Element(type="Image", text="Figure 1", page=1, bbox=(0, 0, 10, 10), image_png=png),
                Element(type="FigureCaption", text="Figure 1: A plot.", page=1, bbox=(0, 12, 10, 20))])
    md = doc.to_markdown(str(tmp_path / "paper.md"))
    assert md.startswith("![Figure 1](paper_images/page001_figure1.png)")
    assert (tmp_path / "paper_images" / "page001_figure1.png").read_bytes() == png
    data = json.loads(doc.to_json(str(tmp_path / "paper.json")))
    assert data[0]["type"] == "Image" and data[0]["metadata"]["image_path"].endswith("page001_figure1.png")
    # Without a file: the PNG travels inline (Unstructured's image_base64)
    doc.elements[0].image_path = None
    assert "image_base64" in json.loads(doc.to_json())[0]["metadata"]
    assert doc.chunks() and all("Figure 1](" not in c.text for c in doc.chunks())


def test_sideways_text_is_translated_in_its_own_frame(tmp_path):
    """Rotated lines (sideways tables) are segmented with their rotation kept (data-rot), never mixed with horizontal text."""
    from rocktranslate.core.html_transformer import instrument_html, parse_rotated_matrix_classes, to_line_frame
    from bs4 import BeautifulSoup
    raw = """<html><head><style>
    .m0{transform:matrix(0.325000,0.000000,0.000000,0.325000,0,0);}
    .m1{transform:matrix(0.000000,-0.325000,0.325000,0.000000,0,0);}
    </style></head><body><div id="page-container"><div class="pf" id="pf1"><div class="pc">
    <div class="t m0 x1 h1 y1 ff1 fs1 fc0 sc0 ls0 ws0">The diversity of water accumulation matches the classes.</div>
    <div class="t m1 x2 h1 y2 ff1 fs1 fc0 sc0 ls0 ws0">Table 3 Values and classes of CTA</div>
    </div></div></div></body></html>"""
    rot = parse_rotated_matrix_classes(BeautifulSoup(raw, "html.parser"))
    assert set(rot) == {"m1"}
    sx, sy, ux, uy, vx, vy = rot["m1"]
    assert abs(sx - 0.325) < 1e-6 and abs(sy - 0.325) < 1e-6 and (ux, uy, vx, vy) == (0.0, -1.0, 1.0, 0.0)
    # Text going up: along-text extent comes from the vertical extent of the page box
    assert to_line_frame((10, 20, 100, 300), (0.0, -1.0, 1.0, 0.0)) == (-300, -100, 10, 20)
    src, out = tmp_path / "raw.html", tmp_path / "inst.html"
    src.write_text(raw, encoding="utf-8")
    texts, _ = instrument_html(str(src), str(out))
    assert any("Table 3 Values" in t for t in texts.values())
    assert any("water accumulation" in t and "Table 3" not in t for t in texts.values())
    soup = BeautifulSoup(out.read_text(encoding="utf-8"), "html.parser")
    rotated = [d for d in soup.select("div.t") if "m1" in d.get("class", [])]
    assert rotated[0].get("data-rot") == "0.000000,-1.000000,1.000000,0.000000"
    span = rotated[0].select_one("span[data-trans-id]")
    assert span is not None and abs(float(span["data-sx"]) - 0.325) < 1e-6


def test_hyphen_split_is_joined_through_color_tags():
    """A word split at a line end inside a colored run ("behav-</color>" + "<color>ioral") is joined."""
    from rocktranslate.core.html_transformer import join_paragraph_lines, merge_color_runs
    joined = merge_color_runs(join_paragraph_lines(["<color_0296d3>combined behav-</color_0296d3>",
                                                    "<color_0296d3>ioral approaches</color_0296d3>"]))
    assert joined == "<color_0296d3>combined behavioral approaches</color_0296d3>"
    # Real compounds keep their hyphen
    assert join_paragraph_lines(["a state-", "of-the-art model"]) == "a state-of-the-art model"
