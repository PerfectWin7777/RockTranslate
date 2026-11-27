"""
RockTranslate v2.0.8 — opening PDFs from links, paths and the clipboard
(headless, no GUI, no network, no LLM).
"""

import os
import sys

import pytest

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
