"""
RockTranslate v2.0.5 — headless regression suite (no GUI, no LLM cost).

Run:  python -m pytest dev_tools/test_v205_core.py -q

Covers the P0/P1 fixes: local server hardening, LLM output never parsed as
HTML, symbol-glyph fixes scoped to symbol fonts, page ranges, LLM client
retry/backoff/validation, translation run cancellation (Stop -> Start race),
per-page print sizes. The LLM is always stubbed.
"""
import http.client
import json
import os
import re
import sys
import tempfile
import threading
import time
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

# Isolate the user config: tests must never touch the real settings/cache
_REAL_HOME = os.path.expanduser("~")
_REAL_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
_TMP_HOME = tempfile.mkdtemp(prefix="rt_test_home_")
os.environ["HOME"] = _TMP_HOME
os.environ["LOCALAPPDATA"] = _TMP_HOME

FIXTURE_HTML = os.path.join(
    ROOT, "src", "rocktranslate", "assets", "pdf2htmlEX", "test",
    "browser_tests", "geneve_1564", "geneve_1564.html",
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Local server hardening (S1)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def server():
    from rocktranslate.core import local_server as ls
    port = ls.find_free_port()
    ready = threading.Event()
    assets = tempfile.mkdtemp(prefix="rt_assets_")
    with open(os.path.join(assets, "index.html"), "w") as f:
        f.write("<html>ui</html>")
    threading.Thread(target=ls.start_local_server, args=(port, assets, ready), daemon=True).start()
    assert ready.wait(5)
    return ls, port


def _get(port, path, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    body = resp.read()
    return resp.status, body, dict(resp.getheaders())


def test_server_requires_token_and_allowlist(server):
    ls, port = server
    secret_dir = tempfile.mkdtemp(prefix="rt_secret_")
    secret = os.path.join(secret_dir, "id_rsa")
    with open(secret, "w") as f:
        f.write("PRIVATE")
    allowed = os.path.join(tempfile.mkdtemp(prefix="rt_doc_"), "paper.pdf")
    with open(allowed, "wb") as f:
        f.write(b"%PDF-1.4 test")
    ls.allow_file(allowed)

    from urllib.parse import quote
    # no token
    assert _get(port, f"/local-file?path={quote(allowed)}")[0] == 403
    # bad token
    assert _get(port, f"/local-file?t=nope&path={quote(allowed)}")[0] == 403
    # good token, file outside allowlist
    assert _get(port, f"/local-file?t={ls.SESSION_TOKEN}&path={quote(secret)}")[0] == 403
    # good token, allowed file
    status, body, headers = _get(port, f"/local-file?t={ls.SESSION_TOKEN}&path={quote(allowed)}")
    assert status == 200 and body.startswith(b"%PDF")
    assert headers.get("Access-Control-Allow-Origin") is None


def test_server_rejects_foreign_host(server):
    _, port = server
    assert _get(port, "/index.html", host="evil.example:80")[0] == 403
    assert _get(port, "/index.html")[0] == 200


def test_allowlist_directory_and_traversal():
    from rocktranslate.core import local_server as ls
    root = tempfile.mkdtemp(prefix="rt_cache_")
    ls.allow_directory(root)
    inside = os.path.join(root, "a", "workspace.html")
    assert ls.is_path_allowed(inside)
    assert not ls.is_path_allowed(os.path.join(root, "..", "elsewhere.txt"))
    assert not ls.is_path_allowed(root + "_sibling/file.html")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Extraction helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_symbol_fix_is_scoped_to_symbol_fonts():
    from bs4 import BeautifulSoup
    from rocktranslate.core.html_transformer import detect_symbol_font_classes
    html = (
        '<div class="t ff1">The saga of Þór and ¼ of a cake is real Icelandic text here</div>'
        '<div class="t ff2">ð1Þ</div><div class="t ff2">x ¼ y þ 1</div>'
    )
    soup = BeautifulSoup(html, "lxml")
    assert detect_symbol_font_classes(soup) == {"ff2"}


def test_page_range_parsing_is_clamped():
    from rocktranslate.core.pipeline import parse_page_range
    assert parse_page_range("1-50", 30) == list(range(30))
    assert parse_page_range("3, 1-2, 99", 10) == [0, 1, 2]
    assert parse_page_range("", 10) is None
    assert parse_page_range("abc", 10) == []


def test_instrumented_fixture_has_single_font_per_segment(tmp_path):
    from rocktranslate.core.html_transformer import instrument_html
    out = tmp_path / "ws.html"
    texts, pages = instrument_html(FIXTURE_HTML, str(out))
    assert texts and pages
    html = out.read_text(encoding="utf-8")
    for classes in re.findall(r'<span class="(trans-span[^"]*)"', html):
        tokens = classes.split()
        assert sum(t.startswith("ff") for t in tokens) <= 1, classes
        assert sum(t.startswith("fs") for t in tokens) <= 1, classes


def test_page_size_css_uses_each_page_size():
    from rocktranslate.core.renderer import build_page_size_css
    html = (
        "@media print{.w0{width:816.000000pt;}.h0{height:1056.000000pt;}"
        ".w1{width:1056.000000pt;}.h1{height:816.000000pt;}}"
        '<div id="pf1" class="pf w0 h0"></div><div id="pf2" class="pf w1 h1"></div>'
    )
    css = build_page_size_css(html)
    assert "@page rt-w0-h0 { size: 612.000pt 792.500pt" in css
    assert "@page rt-w1-h1 { size: 792.000pt 612.500pt" in css


# ─────────────────────────────────────────────────────────────────────────────
# 3. LLM client (stubbed litellm)
# ─────────────────────────────────────────────────────────────────────────────

def _fake_response(payload):
    msg = types.SimpleNamespace(content=json.dumps(payload))
    usage = types.SimpleNamespace(prompt_tokens=10, completion_tokens=5)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)


@pytest.fixture
def client(monkeypatch):
    from rocktranslate.core import llm_client as lc
    monkeypatch.setattr(lc, "RETRY_DELAYS", [0.01, 0.01, 0.01])
    return lc.LLMClient(model="deepseek/deepseek-flash", api_key="sk-test", max_retries=4)


SEGS = [{"id": "g-1", "text": "Hello"}, {"id": "g-2", "text": "World"}]


def test_rate_limit_is_retried_with_backoff(monkeypatch, client):
    from rocktranslate.core import llm_client as lc
    calls = []

    def fake_completion(**kw):
        calls.append(time.monotonic())
        if len(calls) < 3:
            raise RuntimeError("RateLimitError: 429 Too Many Requests")
        return _fake_response([{"id": "g-1", "translated": "Bonjour"}, {"id": "g-2", "translated": "Monde"}])

    monkeypatch.setattr(lc.litellm, "completion", fake_completion)
    out = client.translate_batch(SEGS)
    assert out == [{"id": "g-1", "translated": "Bonjour"}, {"id": "g-2", "translated": "Monde"}]
    assert len(calls) == 3
    assert client.usage["requests"] == 1


def test_fatal_auth_error_stops_immediately(monkeypatch, client):
    from rocktranslate.core import llm_client as lc
    calls = []

    def fake_completion(**kw):
        calls.append(1)
        raise RuntimeError("AuthenticationError: invalid api key")

    monkeypatch.setattr(lc.litellm, "completion", fake_completion)
    assert client.translate_batch(SEGS) is None
    assert len(calls) == 1


def test_omitted_and_hallucinated_ids(monkeypatch, client):
    from rocktranslate.core import llm_client as lc
    calls = []

    def fake_completion(**kw):
        calls.append(kw["messages"][1]["content"])
        if len(calls) == 1:   # forgets g-2, invents g-99
            return _fake_response([{"id": "g-1", "translated": "Bonjour"}, {"id": "g-99", "translated": "X"}])
        return _fake_response([{"id": "g-2", "translated": "Monde"}])

    monkeypatch.setattr(lc.litellm, "completion", fake_completion)
    out = client.translate_batch(SEGS)
    assert out == [{"id": "g-1", "translated": "Bonjour"}, {"id": "g-2", "translated": "Monde"}]
    assert len(calls) == 2 and '"g-2"' in calls[1] and '"g-1"' not in calls[1]


def test_deepseek_thinking_disabled_and_fallback(monkeypatch, client):
    from rocktranslate.core import llm_client as lc
    seen = []

    def fake_completion(**kw):
        seen.append(dict(kw))
        if "extra_body" in kw:
            raise RuntimeError("BadRequest: unknown field thinking")
        return _fake_response([{"id": "g-1", "translated": "a"}, {"id": "g-2", "translated": "b"}])

    lc.LLMClient._thinking_flag_rejected.discard("deepseek/deepseek-flash")
    monkeypatch.setattr(lc.litellm, "completion", fake_completion)
    assert client.translate_batch(SEGS)
    assert seen[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "extra_body" not in seen[1]
    lc.LLMClient._thinking_flag_rejected.discard("deepseek/deepseek-flash")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Translation runs: Stop -> Start race (T1/T2) and persistence (T3)
# ─────────────────────────────────────────────────────────────────────────────

class FakeWindow:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def evaluate_js(self, js):
        m = re.search(r"CustomEvent\('([^']+)'", js)
        with self.lock:
            self.events.append((m.group(1) if m else "?", js))

    def count(self, name):
        with self.lock:
            return sum(1 for n, _ in self.events if n == name)


class SlowClient:
    """Stub LLMClient: each batch takes `delay` seconds, cancellable."""
    def __init__(self, delay, tag):
        self.delay, self.tag = delay, tag
        self.model, self.target_lang = "stub/model", "French"
        self.usage = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}
        self.calls = 0

    def translate_batch(self, segments, context=None, check_cancelled=None):
        self.calls += 1
        end = time.monotonic() + self.delay
        while time.monotonic() < end:
            if check_cancelled and check_cancelled():
                return None
            time.sleep(0.01)
        return [{"id": s["id"], "translated": f"{self.tag}:{s['text']}"} for s in segments]


def _prepared_api(tmp_path, n_pages=3, per_page=4):
    from rocktranslate.core.api.translation_api import TranslationApiMixin
    api = TranslationApiMixin()
    api._window = FakeWindow()
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    api._active_pdf_path = str(pdf)
    api._document_hash = "test-" + tmp_path.name
    api._is_prepared = True
    api._active_html_path = str(tmp_path / "ws.html")
    texts, pages = {}, {}
    i = 0
    for p in range(n_pages):
        for _ in range(per_page):
            texts[f"g-{i}"] = f"Sentence number {i} with real words"
            pages[f"g-{i}"] = p
            i += 1
    api._original_texts, api._tid_to_page = texts, pages
    api._metadata_total_pages = n_pages
    return api


def test_stop_then_start_never_resurrects_old_run(tmp_path, monkeypatch):
    from rocktranslate.core import config_manager
    config_manager.config_db.set("TranslationConfig", "parallel_requests", 1)
    config_manager.config_db.set("TranslationConfig", "max_segments_per_batch", 2)
    api = _prepared_api(tmp_path)

    first, second = SlowClient(0.5, "OLD"), SlowClient(0.05, "NEW")
    clients = iter([first, second])
    monkeypatch.setattr(api, "_resolve_llm_client", lambda: next(clients))

    api.start_range_translation(None)
    time.sleep(0.2)
    api.stop_translation(quiet=True)
    api.start_range_translation(None)   # immediately after Stop
    api._trans_thread.join(10)

    flat = {k: v for page in api._translated_pages.values() for k, v in page.items()}
    assert len(flat) == 12
    assert all(v.startswith("NEW:") for v in flat.values()), flat
    assert first.calls == 1                       # the old run never continued
    assert api._window.count("trigger-translation-finished") == 2
    assert api._thread_lock.acquire(blocking=False)  # lock released
    api._thread_lock.release()


def test_start_while_running_is_refused(tmp_path, monkeypatch):
    api = _prepared_api(tmp_path)
    monkeypatch.setattr(api, "_resolve_llm_client", lambda: SlowClient(0.3, "A"))
    api.start_range_translation(None)
    api.start_range_translation(None)   # refused with a toast, no second thread
    api._trans_thread.join(10)
    assert any("status_trans_is_running" in js for _, js in api._window.events)


def test_translations_are_persisted_and_restored(tmp_path, monkeypatch):
    api = _prepared_api(tmp_path)
    monkeypatch.setattr(api, "_resolve_llm_client", lambda: SlowClient(0.0, "P"))
    api.start_range_translation("2")
    api._trans_thread.join(10)
    assert set(api._translated_pages) == {1}

    api2 = _prepared_api(tmp_path)
    restored = api2._load_persisted_translations("stub/model", "French")
    assert restored == 4
    # A changed source text invalidates its cached translation
    api3 = _prepared_api(tmp_path)
    api3._original_texts["g-4"] = "Different source"
    assert api3._load_persisted_translations("stub/model", "French") == 3


# ─────────────────────────────────────────────────────────────────────────────
# 5. LLM output can never execute script in the workspace (S2) — real browser
# ─────────────────────────────────────────────────────────────────────────────

def test_applytranslation_is_xss_safe(tmp_path):
    """Loads the instrumented workspace in a real headless Chromium."""
    import subprocess
    from rocktranslate.core.html_transformer import instrument_html
    from rocktranslate.core.downloader import find_downloaded_headless_shell
    from rocktranslate.core.renderer import find_system_chromium_browser

    import glob
    real_shells = sorted(
        glob.glob(os.path.join(_REAL_HOME, ".config", "rocktranslate", "runtime", "chromium_headless", "*", "*", "chrome-headless-shell*"))
        + (glob.glob(os.path.join(_REAL_LOCALAPPDATA, "RockTranslate", "runtime", "chromium_headless", "*", "*", "chrome-headless-shell.exe"))
           if _REAL_LOCALAPPDATA else [])
    )
    browser = (os.environ.get("ROCKTRANSLATE_BROWSER") or find_downloaded_headless_shell()
               or (real_shells[0] if real_shells else None) or find_system_chromium_browser())
    if not browser:
        pytest.skip("no Chromium available")

    out = tmp_path / "ws.html"
    texts, _ = instrument_html(FIXTURE_HTML, str(out))
    seg = next(iter(texts))
    payload = '<img src=x onerror="window.__pwned=1"><color_ff0000>rouge</color_ff0000> & fin'
    probe = f"""<script>
    window.addEventListener('load', function () {{
        window.applyTranslation({json.dumps(seg)}, {json.dumps(payload)});
        setTimeout(function () {{
            var span = document.querySelector('[data-trans-id="{seg}"]');
            var colored = span.querySelector('span');
            var r = document.createElement('pre');
            r.id = 'rt-result';
            r.textContent = JSON.stringify({{
                pwned: window.__pwned === 1,
                text: span.textContent,
                color: colored ? getComputedStyle(colored).color : null,
                imgs: span.querySelectorAll('img').length
            }});
            document.body.appendChild(r);
        }}, 300);
    }});
    </script></body>"""
    html = out.read_text(encoding="utf-8")
    idx = html.rfind("</body>")
    test_page = tmp_path / "probe.html"
    test_page.write_text(html[:idx] + probe + html[idx + 7:], encoding="utf-8")

    cmd = [browser, "--headless", "--disable-gpu", "--virtual-time-budget=3000",
           f"--user-data-dir={tmp_path / 'profile'}", "--dump-dom", test_page.as_uri()]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        cmd.insert(1, "--no-sandbox")
    dom = subprocess.run(cmd, capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    m = re.search(r'<pre id="rt-result">(.*?)</pre>', dom, re.S)
    assert m, "probe did not run"
    import html as html_lib
    result = json.loads(html_lib.unescape(m.group(1)))
    assert result["pwned"] is False
    assert result["imgs"] == 0
    assert "<img" in result["text"] and "rouge" in result["text"]
    assert result["color"] == "rgb(255, 0, 0)"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Protected PDFs: password prompt flow (1.2)
# ─────────────────────────────────────────────────────────────────────────────

def _encrypted_pdf(path, user_password):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    w.encrypt(user_password=user_password, owner_password="owner", algorithm="AES-128")
    w.write(str(path))


def test_password_protected_pdf_asks_then_opens(tmp_path):
    pytest.importorskip("cryptography")
    from rocktranslate.core.api.translation_api import TranslationApiMixin
    from rocktranslate.core.pdf_metadata import get_pdf_metadata

    pdf = tmp_path / "locked.pdf"
    _encrypted_pdf(pdf, "lecture")
    assert get_pdf_metadata(str(pdf))["needs_password"] is True
    assert get_pdf_metadata(str(pdf), password="lecture")["needs_password"] is False

    nocopy = tmp_path / "nocopy.pdf"
    _encrypted_pdf(nocopy, "")
    meta = get_pdf_metadata(str(nocopy))
    assert meta["encrypted"] is True and meta["needs_password"] is False

    api = TranslationApiMixin()
    api._window = FakeWindow()
    api._run_extraction(str(pdf))
    assert api._window.count("request-pdf-password") == 1
    assert api._window.count("document-ready") == 0

    # wrong password -> asked again with the retry flag
    api._pdf_passwords[os.path.abspath(str(pdf))] = "nope"
    api._run_extraction(str(pdf))
    assert any("retry: true" in js for n, js in api._window.events if n == "request-pdf-password")

    api._pdf_passwords[os.path.abspath(str(pdf))] = "lecture"
    api._run_extraction(str(pdf))
    assert api._window.count("document-ready") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. Settings window backend & usage statistics
# ─────────────────────────────────────────────────────────────────────────────

def test_preferences_are_validated_and_clamped():
    from rocktranslate.core.api.preferences_api import PreferencesApiMixin
    api = PreferencesApiMixin()
    assert api.set_preference("parallel_requests", 99)["value"] == 16
    assert api.set_preference("temperature", "0.25")["value"] == 0.25
    assert api.set_preference("disable_reasoning", "false")["value"] is False
    assert api.set_preference("ui_theme", "neon")["status"] == "error"
    assert api.set_preference("unknown_key", 1)["status"] == "error"
    assert api.set_preference("browser_path_override", "/does/not/exist")["status"] == "error"
    prefs = api.get_preferences()
    assert prefs["parallel_requests"] == 16 and "French" in prefs["supported_languages"]
    api.reset_preferences()
    assert api.get_preferences()["parallel_requests"] == 4


def test_run_usage_is_recorded_and_streamed(tmp_path, monkeypatch):
    from rocktranslate.core.api.preferences_api import PreferencesApiMixin
    PreferencesApiMixin().reset_usage_stats()
    api = _prepared_api(tmp_path)

    class BilledClient(SlowClient):
        def translate_batch(self, segments, context=None, check_cancelled=None):
            out = super().translate_batch(segments, context, check_cancelled)
            self.usage["requests"] += 1
            self.usage["prompt_tokens"] += 100
            self.usage["completion_tokens"] += 50
            self.usage["cost_usd"] += 0.001
            return out

    monkeypatch.setattr(api, "_resolve_llm_client", lambda: BilledClient(0.0, "U"))
    api.start_range_translation(None)
    api._trans_thread.join(10)

    assert api._window.count("update-usage") >= 1
    assert api._window.count("translation-summary") == 1
    stats = PreferencesApiMixin().get_usage_stats()
    assert stats["totals"]["runs"] == 1
    assert stats["totals"]["segments"] == 12
    assert stats["totals"]["prompt_tokens"] > 0
    assert stats["last_run"]["model"] == "stub/model"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Paragraph reconstruction (DeepL-style reflow)
# ─────────────────────────────────────────────────────────────────────────────

def _line(gid, x, y, em=13.0, fs="fs2", sy=0.325):
    return {"spans": [(gid, None)], "x": x, "y": y, "fs": fs, "m": "m0", "sy": sy, "em": em}


def test_paragraph_grouping_two_columns_row_order():
    from rocktranslate.core.html_transformer import group_lines_into_paragraphs, join_paragraph_lines
    texts, lines = {}, []
    # Two columns emitted row by row (left, right, left, right...)
    for i in range(6):
        texts[f"L{i}"] = f"left column sentence number {i} with enough words to be prose"
        texts[f"R{i}"] = f"right column sentence number {i} with enough words to be prose"
        lines.append(_line(f"L{i}", 60.0, 800 - i * 15.5))
        lines.append(_line(f"R{i}", 400.0, 800 - i * 15.5))
    paras = group_lines_into_paragraphs(lines, texts)
    ids = [[l["spans"][0][0] for l in p] for p in paras]
    assert ids == [[f"L{i}" for i in range(6)], [f"R{i}" for i in range(6)]]
    assert join_paragraph_lines(["a long hyphen-", "ated word trans-", "lation"]) == "a long hyphenated word translation"


def test_paragraph_grouping_breaks_and_absorbs():
    from rocktranslate.core.html_transformer import group_lines_into_paragraphs
    texts = {
        "a": "First paragraph line one has plenty of words in it here",
        "b": "first paragraph line two keeps going with more words",
        "c": "first paragraph line three continues the very same idea",
        "sup": "1",
        "d": "short end.",
        "e": "Second paragraph starts after the short line above here",
        "f": "second paragraph continues with a second line of text",
        "g": "• a bullet item that must start a new block of text",
        "h": "and the bullet item continues on this following line",
    }
    lines = [_line("a", 60, 800), _line("b", 60, 784.5), _line("c", 60, 769), _line("sup", 300, 772, em=9.1),
             _line("d", 60, 753.5), _line("e", 60, 738), _line("f", 60, 722.5),
             _line("g", 60, 707), _line("h", 60, 691.5)]
    paras = group_lines_into_paragraphs(lines, texts)
    ids = [[l["spans"][0][0] for l in p] for p in paras]
    assert ["a", "b", "c", "d"] in ids          # the footnote marker does not break it
    assert ["e", "f"] in ids                    # new paragraph after the short line
    assert ["g", "h"] in ids                    # bullet starts a new block
    host = next(l for p in paras for l in p if l["spans"][0][0] == "c")
    assert host["pieces"][0]["sup"] is True
