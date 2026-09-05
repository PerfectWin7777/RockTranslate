"""
End-to-end verification of the P2 lazy pipeline (no GUI, no LLM cost).

Simulates the full pywebview lifecycle against the real Tankeu PDF:
  A. Lazy open: document-ready fires instantly with htmlPath=None.
  B. First translation: pdf2htmlEX runs inside the worker thread, the
     prepared workspace is served via 'workspace-html-ready' and every
     segment gets streamed back by the stubbed LLM.
  C. Reopen: hash-keyed cache hit restores the workspace instantly
     (no pdf2htmlEX run).
  D. Prepared workspace HTML sanity: translatable spans and .pf pages exist.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PDF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Tankeu et al. 2026.pdf"))


class FakeWindow:
    """Records every evaluate_js call so events can be asserted."""
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def evaluate_js(self, js):
        m = re.search(r"CustomEvent\('([^']+)'", js)
        name = m.group(1) if m else "?"
        with self.lock:
            self.events.append((name, js))

    def wait_for(self, event_name, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self.lock:
                if any(name == event_name for name, _ in self.events):
                    return True
            time.sleep(0.05)
        return False

    def has(self, event_name):
        with self.lock:
            return any(name == event_name for name, _ in self.events)

    def detail_of(self, event_name):
        """Extracts known detail keys from the JS event source (keys are unquoted)."""
        with self.lock:
            for name, js in self.events:
                if name != event_name:
                    continue
                detail = {}
                m = re.search(r"htmlPath: (null|\".*?\")", js, re.S)
                if m:
                    detail["htmlPath"] = None if m.group(1) == "null" else json.loads(m.group(1))
                for key in ("totalPages", "totalSegments"):
                    m = re.search(rf"{key}: (\d+)", js)
                    if m:
                        detail[key] = int(m.group(1))
                return detail
        return None

    def count(self, event_name):
        with self.lock:
            return sum(1 for name, _ in self.events if name == event_name)


def install_test_config():
    """Point config_db at a temp dir and seed a fake API key."""
    from rocktranslate.core.config_manager import ConfigManager
    import rocktranslate.core.api.translation_api as ta

    tmp = tempfile.mkdtemp(prefix="rt_cfg_")
    cm = ConfigManager.__new__(ConfigManager)
    cm.config_dir = Path(tmp)
    cm.filepath = cm.config_dir / "config.json"
    cm.data = {
        "APIConfig": {
            "provider": "Google Gemini",
            "api_keys_by_provider": {"Google Gemini": "FAKE-KEY-FOR-STUBBED-LLM"}
        }
    }
    ta.config_db = cm
    return cm


def install_fake_llm():
    """Replace LLMClient in the translation_api namespace with a deterministic stub."""
    import rocktranslate.core.api.translation_api as ta

    class FakeLLMClient:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def translate_batch(self, segments, context=None, check_cancelled=None):
            self.calls += 1
            time.sleep(0.01)
            return [{"id": s["id"], "translated": f"[FR] {s.get('original', '')[:60]}"} for s in segments]

    ta.LLMClient = FakeLLMClient


def wait_thread(thread, timeout):
    if thread:
        thread.join(timeout=timeout)
        return not thread.is_alive()
    return False


def main():
    assert os.path.exists(PDF_PATH), f"Missing test PDF: {PDF_PATH}"

    import rocktranslate.core.api.translation_api as ta
    config_cm = install_test_config()
    install_fake_llm()

    from rocktranslate.core.web_api import RockTranslateAPI

    # ── A. LAZY OPEN ──────────────────────────────────────────────
    api = RockTranslateAPI()
    win = FakeWindow()
    api._window = win

    t0 = time.time()
    api.extract_pdf(PDF_PATH)
    assert win.wait_for("document-ready", 30), "document-ready never fired"
    open_time = time.time() - t0

    detail = win.detail_of("document-ready")
    assert detail is not None, "document-ready detail unparsable"
    assert detail["htmlPath"] is None, f"expected lazy open (htmlPath=None), got {detail['htmlPath']}"
    assert detail["totalPages"] == 40, f"expected 40 pages from metadata, got {detail['totalPages']}"
    print(f"TEST A OK: lazy open in {open_time:.2f}s, 40 pages, htmlPath=None (no conversion)")

    # ── B. FIRST TRANSLATION TRIGGERS THE DEFERRED PIPELINE ───────
    t0 = time.time()
    api.start_full_translation()
    assert wait_thread(api._trans_thread, 900), "translation thread timed out"
    trans_time = time.time() - t0

    assert win.has("workspace-html-ready"), "workspace-html-ready never fired"
    html_detail = win.detail_of("workspace-html-ready")
    ws_path = html_detail["htmlPath"]
    assert ws_path and os.path.exists(ws_path), f"prepared workspace missing: {ws_path}"
    assert api._is_prepared, "document still not prepared after translation"
    assert api._original_texts, "no original texts mapped"
    assert len(api._translated_pages) > 0, "no translated pages committed"
    total_segments = len(api._original_texts)
    translated_count = sum(len(p) for p in api._translated_pages.values())
    assert win.count("stream-translation") >= int(total_segments * 0.95), \
        f"streamed {win.count('stream-translation')} / {total_segments} segments"
    assert win.has("trigger-translation-finished"), "trigger-translation-finished never fired"
    print(f"TEST B OK: translation pipeline in {trans_time:.1f}s "
          f"({total_segments} segments, {translated_count} committed, "
          f"workspace={os.path.getsize(ws_path)} bytes)")

    # ── D. PREPARED HTML SANITY ───────────────────────────────────
    with open(ws_path, "r", encoding="utf-8") as f:
        ws_html = f.read()
    trans_spans = ws_html.count("data-trans-id=")
    pf_pages = len(re.findall(r'class="[^"]*\bpf\b', ws_html))
    assert trans_spans > 0 and pf_pages >= 39, \
        f"insane workspace: {trans_spans} spans, {pf_pages} pages"
    print(f"TEST D OK: workspace HTML has {trans_spans} translatable spans across {pf_pages} pages")

    # ── C. REOPEN = INSTANT CACHE HIT ─────────────────────────────
    api.close_document()
    win.events.clear()

    t0 = time.time()
    api.extract_pdf(PDF_PATH)
    assert win.wait_for("document-ready", 30), "document-ready never fired on reopen"
    reopen_time = time.time() - t0

    detail2 = win.detail_of("document-ready")
    assert detail2["htmlPath"] is not None, f"cache miss on reopen: {detail2['htmlPath']}"
    assert detail2["totalSegments"] > 0, "segment maps not restored from cache"
    assert api._is_prepared, "_is_prepared not set on cache hit"
    reopen_new = time.time() - t0
    assert reopen_new < 5, f"cache hit too slow: {reopen_new:.1f}s"
    print(f"TEST C OK: reopen from cache in {reopen_time:.2f}s "
          f"({detail2['totalSegments']} segments restored, no pdf2htmlEX run)")

    api.close_document()
    print("ALL P2 TESTS PASSED")


if __name__ == "__main__":
    main()
