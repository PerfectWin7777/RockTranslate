"""
RockTranslate v2.0.8 — opening PDFs from links, paths and the clipboard
(headless, no GUI, no network, no LLM).
"""

import os
import sys
import tempfile

import pytest

# Isolated HOME (like the other suites): config, caches and saved translations
# of this run never touch the user's. The real HOME is kept for the next suite.
os.environ.setdefault("RT_REAL_HOME", os.path.expanduser("~"))
_TMP_HOME = tempfile.mkdtemp(prefix="rt_test_home_")
os.environ["HOME"] = _TMP_HOME
os.environ["LOCALAPPDATA"] = _TMP_HOME

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from rocktranslate.core.sources import parse_pdf_source  # noqa: E402


@pytest.fixture()
def pdf(tmp_path):
    path = tmp_path / "my paper.pdf"
    path.write_bytes(b"%PDF-1.4\n%test\n")
    return path


def test_links(pdf):
    assert parse_pdf_source("  https://arxiv.org/pdf/1706.03762 ") == ("url", "https://arxiv.org/pdf/1706.03762")
    assert parse_pdf_source("http://example.org/a.pdf") == ("url", "http://example.org/a.pdf")
    assert parse_pdf_source("arxiv.org/abs/2109.03697") == ("url", "https://arxiv.org/abs/2109.03697")
    assert parse_pdf_source("www.example.org/x.pdf") == ("url", "https://www.example.org/x.pdf")
    assert parse_pdf_source("1706.03762") == ("url", "https://arxiv.org/abs/1706.03762")
    assert parse_pdf_source("arXiv:2109.03697v3") == ("url", "https://arxiv.org/abs/2109.03697v3")


def test_local_paths(pdf, tmp_path):
    expected = ("path", str(pdf))
    assert parse_pdf_source(str(pdf)) == expected
    assert parse_pdf_source(f'"{pdf}"') == expected                 # Explorer's "Copy as path"
    assert parse_pdf_source(f"'{pdf}'") == expected
    assert parse_pdf_source(pdf.as_uri()) == expected               # file:// URI, %20 decoded
    assert parse_pdf_source(f"{pdf}\n/other/file.pdf") == expected  # a copied list: the first one


def test_errors(tmp_path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert parse_pdf_source("") == ("error", "empty")
    assert parse_pdf_source("   \n ") == ("error", "empty")
    assert parse_pdf_source(str(tmp_path)) == ("error", "is_folder")
    assert parse_pdf_source(str(tmp_path / "missing.pdf")) == ("error", "not_found")
    assert parse_pdf_source(str(text)) == ("error", "not_pdf")


def test_open_from_clipboard(monkeypatch, pdf):
    """A PDF file copied in the Explorer is opened; a copied link is downloaded; text without a PDF is reported."""
    import rocktranslate.core.api.translation_api as ta

    class Stub:
        def __init__(self):
            self.opened, self.urls = [], []

        def extract_pdf(self, path):
            self.opened.append(path)

        def open_pdf_url(self, url):
            self.urls.append(url)
            return {"status": "started"}

    cls = next(v for v in vars(ta).values() if isinstance(v, type) and hasattr(v, "open_from_clipboard"))
    api = Stub()
    monkeypatch.setattr(ta, "read_clipboard", lambda: ["some words", str(pdf)])
    assert cls.open_from_clipboard(api)["status"] == "opened" and api.opened == [str(pdf)]
    monkeypatch.setattr(ta, "read_clipboard", lambda: ["arxiv.org/abs/1706.03762"])
    assert cls.open_from_clipboard(api)["status"] == "started" and api.urls == ["https://arxiv.org/abs/1706.03762"]
    monkeypatch.setattr(ta, "read_clipboard", lambda: ["just a sentence"])
    assert cls.open_from_clipboard(api) == {"status": "error", "message": "clipboard_nothing"}


class _FakeClient:
    target_lang = "French"
    custom_glossary = ""
    model = "stub/model"


def test_structured_translation_keeps_the_passage(monkeypatch):
    """The layout-rebuilt passage is sent as is (not flattened), with the 'keep the structure' instruction."""
    import rocktranslate.core.assist as assist
    seen = {}
    monkeypatch.setattr(assist, "converse", lambda client, messages, **kw: seen.update(messages=messages) or "ok")
    passage = "First paragraph.\n\n- item with b<sub>perf</sub>\n- second item"
    assist.translate_text(_FakeClient(), passage, "French", structured=True)
    assert seen["messages"][1]["content"] == passage
    assert "EXACTLY the same structure" in seen["messages"][0]["content"]
    assist.translate_text(_FakeClient(), "a line\ncut in two", "French")
    assert seen["messages"][1]["content"] == "a line cut in two"          # plain mode still cleans the copy


def test_discuss_builds_the_conversation(monkeypatch):
    import rocktranslate.core.assist as assist
    seen = {}
    monkeypatch.setattr(assist, "converse", lambda client, messages, **kw: seen.update(messages=messages) or "answer")
    history = [{"role": "user", "content": "What is phi?"}, {"role": "assistant", "content": "The porosity."}]
    out = assist.discuss_selection(_FakeClient(), "phi: porosity ...", history, "And sigma?", "French",
                                   title="U-FNO", page_text="Full page text")
    msgs = seen["messages"]
    assert out == "answer"
    assert msgs[0]["role"] == "system" and "language of the user's last message" in msgs[0]["content"]
    assert "U-FNO" in msgs[1]["content"] and "Full page text" in msgs[1]["content"] and "phi: porosity" in msgs[1]["content"]
    assert [m["role"] for m in msgs[3:]] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "And sigma?"
