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
