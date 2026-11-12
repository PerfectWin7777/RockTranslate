"""
RockTranslate — Reader features of the desktop app (pywebview bridge)
Path: src/rocktranslate/core/api/reader_api.py

Everything that makes RockTranslate a daily PDF reader, on top of the
translation pipeline:

- reading assistant: a selection translated / explained with streaming, a
  section summarized, a question answered with verbatim quotes (core.assist);
- per-document library record, kept OUTSIDE the cache (clearing the cache never
  deletes notes): reading position, highlights and notes, paper glossary;
- bilingual search in the original text and its translation;
- continuous reading: the pages being read are translated in the background;
- translated page as an image (clipboard snapshot), bilingual side-by-side PDF.

Answers stream to the UI through window.rtAssistDelta / window.rtAssistDone
(see assets/ui/js/reader.js).

Author: RockTranslate Contributors
License: MIT License
"""

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional

from loguru import logger

from ..assist import (ask_document, build_glossary, clean_selection, explain_text, glossary_to_rules,
                      page_texts, summarize_text, translate_text)
from ..config_manager import config_db

try:
    import webview
except ImportError:  # headless tests
    webview = None


def _fold(text: str) -> str:
    """Search form: no accents, lowercase, single spaces, tags removed."""
    text = re.sub(r"</?[a-z_0-9]+[^>]*>", "", text or "")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


class ReaderApiMixin:
    """Reader endpoints exposed to the UI (mixed into RockTranslateAPI)."""

    # ── Per-document library record (outside the cache) ──────────────────────

    def _library_path(self) -> Optional[str]:
        doc_hash = getattr(self, "_document_hash", None)
        if not doc_hash:
            return None
        folder = config_db.config_dir / "library"
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / f"{doc_hash}.json")

    def _library_read(self) -> Dict[str, Any]:
        path = self._library_path()
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _library_update(self, **fields: Any) -> None:
        path = self._library_path()
        if not path:
            return
        lock = getattr(self, "_library_lock", None)
        if lock is None:
            lock = self._library_lock = threading.Lock()
        with lock:
            data = self._library_read()
            data.update(fields)
            data["path"] = getattr(self, "_active_pdf_path", None)
            data["updated"] = time.time()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)

    def get_reading_position(self) -> Dict[str, Any]:
        """Last page and zoom of the active document (resume reading)."""
        return self._library_read().get("position") or {}

    def save_reading_position(self, page: int, zoom: Optional[float] = None, path: Optional[str] = None) -> bool:
        """
        Remembers the page being read. `path` is the document the page belongs
        to: a save that arrives after a tab switch must not land on the newly
        opened document.
        """
        try:
            active = getattr(self, "_active_pdf_path", None)
            if path and active and os.path.abspath(path) != os.path.abspath(active):
                return False
            self._library_update(position={"page": int(page), "zoom": zoom})
            return True
        except Exception as e:
            logger.debug(f"Reading position not saved: {e}")
            return False

    def get_highlights(self) -> List[Dict[str, Any]]:
        """Highlights and notes of the active document."""
        items = self._library_read().get("highlights")
        return items if isinstance(items, list) else []

    def save_highlights(self, items: List[Dict[str, Any]]) -> bool:
        try:
            self._library_update(highlights=list(items or []))
            return True
        except Exception as e:
            logger.error(f"Highlights not saved: {e}")
            return False

    def get_doc_citation(self) -> Dict[str, str]:
        """
        Short citation of the active document for "copy with citation":
        first author + et al., year, title, DOI (PDF metadata, then page 1).
        """
        pdf = getattr(self, "_active_pdf_path", None)
        if not pdf:
            return {}
        cached = getattr(self, "_citation_cache", None)
        if cached and cached.get("_pdf") == pdf:
            return cached
        info: Dict[str, str] = {"_pdf": pdf, "title": "", "authors": "", "year": "", "doi": ""}
        try:
            from pypdf import PdfReader
            reader = PdfReader(pdf)
            meta = reader.metadata or {}
            info["title"] = str(meta.get("/Title") or "").strip()
            info["authors"] = str(meta.get("/Author") or "").strip()
            first = (reader.pages[0].extract_text() or "") if reader.pages else ""
            m = re.search(r"\b(10\.\d{4,9}/[^\s\"<>]+[\w/])", first)
            if m:
                info["doi"] = m.group(1)
            m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b", str(meta.get("/CreationDate") or "") + " " + first[:3000])
            if m:
                info["year"] = m.group(1)
            if not info["title"]:
                lines = [l.strip() for l in first.splitlines() if len(l.strip()) > 20]
                info["title"] = lines[0] if lines else os.path.splitext(os.path.basename(pdf))[0]
        except Exception as e:
            logger.debug(f"Citation metadata unavailable: {e}")
        first_author = re.split(r"[,;&]| and ", info["authors"])[0].strip() if info["authors"] else ""
        surname = first_author.split()[-1] if first_author else ""
        several = bool(re.search(r"[,;&]| and ", info["authors"] or ""))
        info["short"] = (f"{surname}{' et al.' if several else ''}, {info['year']}".strip(", ")
                         if surname else info["title"][:80])
        self._citation_cache = info
        return info

    # ── Document text (page by page, cached for the session) ─────────────────

    def _doc_pages(self) -> List[str]:
        pdf = getattr(self, "_active_pdf_path", None)
        cached = getattr(self, "_page_text_cache", None)
        if cached and cached[0] == pdf:
            return cached[1]
        password = getattr(self, "_pdf_passwords", {}).get(os.path.abspath(pdf)) if pdf else None
        pages = page_texts(pdf, password) if pdf else []
        self._page_text_cache = (pdf, pages)
        return pages

    # ── Reading assistant (streamed to the UI) ───────────────────────────────

    def _assistant_client(self):
        client = self._resolve_llm_client()       # toasts "missing key" itself
        if client is not None:
            client.custom_glossary = self._effective_glossary()
        return client

    def _stream_to_ui(self, req_id: str):
        """Delta callback batching pieces (one bridge call every ~60 ms)."""
        buffer: List[str] = []
        last = [0.0]

        def flush() -> None:
            if buffer:
                text = "".join(buffer)
                buffer.clear()
                self._send_js(f"window.rtAssistDelta && window.rtAssistDelta({json.dumps(req_id)}, {json.dumps(text)})")
            last[0] = time.monotonic()

        def on_delta(piece: str) -> None:
            buffer.append(piece)
            if time.monotonic() - last[0] > 0.06:
                flush()

        on_delta.flush = flush  # type: ignore[attr-defined]
        return on_delta

    def _assist_done(self, req_id: str, payload: Dict[str, Any]) -> None:
        self._send_js(f"window.rtAssistDone && window.rtAssistDone({json.dumps(req_id)}, {json.dumps(payload)})")

    def assist_start(self, mode: str, text: str, req_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """
        Starts a reading-assistant request. mode: 'translate' | 'explain' |
        'summarize' (text = section text, extra.title) | 'ask' (text = question).
        The answer streams to window.rtAssistDelta, then window.rtAssistDone.
        """
        text = (text or "").strip()
        if not text:
            return {"status": "error", "message": "empty"}
        extra = extra or {}

        def worker() -> None:
            client = self._assistant_client()
            if client is None:
                self._assist_done(req_id, {"ok": False, "error": "no_key"})
                return
            lang = config_db.get("SystemConfig", "target_lang", "French")
            started = time.monotonic()
            try:
                on_delta = self._stream_to_ui(req_id)
                if mode == "translate":
                    out = translate_text(client, text, lang, on_delta=on_delta)
                elif mode == "explain":
                    title = self.get_doc_citation().get("title") if getattr(self, "_active_pdf_path", None) else None
                    out = explain_text(client, text, lang, on_delta=on_delta, context=title)
                elif mode == "summarize":
                    out = summarize_text(client, text, lang, title=extra.get("title"), on_delta=on_delta)
                elif mode == "ask":
                    result = ask_document(client, self._doc_pages(), text, lang)
                    self._assist_done(req_id, {"ok": True, "text": result["answer"], "quotes": result["quotes"],
                                               "seconds": time.monotonic() - started,
                                               "cost": client.usage.get("cost_usd", 0.0)})
                    return
                else:
                    raise ValueError(f"unknown mode {mode}")
                on_delta.flush()  # type: ignore[attr-defined]
                self._assist_done(req_id, {"ok": True, "text": out, "seconds": time.monotonic() - started,
                                           "cost": client.usage.get("cost_usd", 0.0), "model": client.model})
            except Exception as e:
                logger.warning(f"Assistant request failed ({mode}): {e}")
                self._assist_done(req_id, {"ok": False, "error": str(e)[:300]})

        threading.Thread(target=worker, name=f"rocktranslate-assist-{mode}", daemon=True).start()
        return {"status": "started"}

    def clean_text(self, text: str) -> str:
        """Selection without line breaks nor end-of-line hyphenation (clean copy)."""
        return clean_selection(text)

    # ── Paper glossary (consistent terminology) ──────────────────────────────

    def get_doc_glossary(self) -> Dict[str, Any]:
        data = self._library_read().get("glossary") or {}
        return {"items": data.get("items") or [], "use": bool(data.get("use", True)),
                "lang": data.get("lang") or ""}

    def save_doc_glossary(self, items: List[Dict[str, str]], use: bool = True) -> bool:
        clean = [{"term": str(i.get("term", "")).strip(), "translation": str(i.get("translation", "")).strip(),
                  "note": str(i.get("note", "")).strip()} for i in (items or []) if str(i.get("term", "")).strip()]
        self._library_update(glossary={"items": clean, "use": bool(use),
                                       "lang": config_db.get("SystemConfig", "target_lang", "French")})
        return True

    def generate_doc_glossary(self, req_id: str) -> Dict[str, str]:
        """Builds the glossary of the active paper (one short LLM request)."""
        def worker() -> None:
            client = self._resolve_llm_client()
            if client is None:
                self._assist_done(req_id, {"ok": False, "error": "no_key"})
                return
            lang = config_db.get("SystemConfig", "target_lang", "French")
            try:
                items = build_glossary(client, "\n\n".join(self._doc_pages()), lang)
                self.save_doc_glossary(items, True)
                self._assist_done(req_id, {"ok": True, "items": items, "cost": client.usage.get("cost_usd", 0.0)})
            except Exception as e:
                logger.warning(f"Glossary generation failed: {e}")
                self._assist_done(req_id, {"ok": False, "error": str(e)[:300]})

        threading.Thread(target=worker, name="rocktranslate-glossary", daemon=True).start()
        return {"status": "started"}

    def _effective_glossary(self) -> str:
        """Global glossary (settings) + this paper's glossary when enabled."""
        rules = [config_db.get("TranslationConfig", "custom_glossary", "") or ""]
        try:
            g = self.get_doc_glossary()
            if g["use"] and g["items"]:
                rules.append(glossary_to_rules(g["items"]))
        except Exception:
            pass
        return "\n".join(r.strip() for r in rules if r and r.strip())

    # ── Bilingual search ─────────────────────────────────────────────────────

    def search_document(self, query: str, limit: int = 60) -> List[Dict[str, Any]]:
        """
        Searches the original text AND its translation (accent and case
        insensitive). Returns [{page (1-based), side: 'original'|'translation',
        snippet, original}] where `original` is the source text to highlight.
        """
        q = _fold(query)
        if len(q) < 2:
            return []
        hits: List[Dict[str, Any]] = []
        originals: Dict[str, str] = getattr(self, "_original_texts", {}) or {}
        tid_to_page: Dict[str, int] = getattr(self, "_tid_to_page", {}) or {}
        translations = {k: v for page in (getattr(self, "_translated_pages", {}) or {}).values()
                        for k, v in page.items()}

        def snippet(text: str) -> str:
            plain = re.sub(r"</?[a-z_0-9]+[^>]*>", "", text)
            i = _fold(plain).find(q)
            start = max(0, i - 60)
            return ("…" if start else "") + plain[start:start + 180].strip() + "…"

        if originals:
            for seg_id, text in originals.items():
                page = tid_to_page.get(seg_id, 0) + 1
                if q in _fold(text):
                    hits.append({"page": page, "side": "original", "snippet": snippet(text), "original": text})
                elif seg_id in translations and q in _fold(translations[seg_id]):
                    hits.append({"page": page, "side": "translation", "snippet": snippet(translations[seg_id]),
                                 "original": text})
                if len(hits) >= limit:
                    break
        else:
            # Layout not prepared yet: plain page text (original only)
            for i, text in enumerate(self._doc_pages()):
                folded = _fold(text)
                pos = folded.find(q)
                while pos != -1 and len(hits) < limit:
                    hits.append({"page": i + 1, "side": "original",
                                 "snippet": "…" + re.sub(r"\s+", " ", text)[max(0, pos - 60):pos + 120] + "…",
                                 "original": query})
                    pos = folded.find(q, pos + len(q))
        hits.sort(key=lambda h: h["page"])
        return hits

    # ── Continuous reading ───────────────────────────────────────────────────

    def auto_translate_pages(self, pages: List[int]) -> Dict[str, Any]:
        """
        Continuous reading mode: translates the given 0-based pages if they
        are not translated yet and no run is active. Silent when busy.
        """
        if not getattr(self, "_active_pdf_path", None):
            return {"status": "no_document"}
        total = self.get_total_pages()
        todo = sorted({int(p) for p in pages if 0 <= int(p) < total and not self._translated_pages.get(int(p))})
        if not todo:
            return {"status": "done"}
        if self._thread_lock.locked():
            return {"status": "busy"}
        self.start_range_translation(", ".join(str(p + 1) for p in todo))
        return {"status": "started", "pages": todo}

    # ── Translated page as an image / side-by-side export ───────────────────

    def _translated_html(self) -> Optional[str]:
        """Printable translated HTML next to the workspace (caller deletes it)."""
        from ..renderer import apply_translations_offline
        html = getattr(self, "_active_html_path", None)
        if not html or not os.path.exists(html):
            return None
        translations = {k: v for page in self._translated_pages.values() for k, v in page.items()}
        fd, path = tempfile.mkstemp(suffix=".html", prefix="rocktranslate-view-", dir=os.path.dirname(html))
        os.close(fd)
        apply_translations_offline(html, path, translations)
        return path

    def snapshot_translated_page(self, page: int, req_id: str) -> Dict[str, str]:
        """
        Renders translated page `page` (0-based) as a PNG for the clipboard.
        The result arrives through window.rtAssistDone(req_id, {png: base64}).
        """
        def worker() -> None:
            path = None
            try:
                from ..cdp import screenshot_page
                from ..renderer import resolve_pdf_renderer
                path = self._translated_html()
                if not path:
                    raise RuntimeError("layout not prepared")
                png = screenshot_page(resolve_pdf_renderer(), path, int(page), timeout=120)
                if not png:
                    raise RuntimeError("screenshot failed")
                self._assist_done(req_id, {"ok": True, "png": png})
            except Exception as e:
                logger.warning(f"Translated page snapshot failed: {e}")
                self._assist_done(req_id, {"ok": False, "error": str(e)[:200]})
            finally:
                if path:
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

        threading.Thread(target=worker, name="rocktranslate-snapshot", daemon=True).start()
        return {"status": "started"}

    def save_png_file(self, png_base64: str, suggested_name: str = "rocktranslate.png") -> Dict[str, str]:
        """Fallback when the clipboard refuses images: saves the PNG with a dialog."""
        import base64
        if not self._window:
            return {"status": "error"}
        dest = self._window.create_file_dialog(
            getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG,
            save_filename=suggested_name, file_types=("PNG image (*.png)",))
        if not dest:
            return {"status": "cancelled"}
        dest = dest[0] if isinstance(dest, (list, tuple)) else dest
        with open(dest, "wb") as f:
            f.write(base64.b64decode(png_base64.split(",")[-1]))
        return {"status": "success", "path": dest}

    def save_text_file(self, content: str, suggested_name: str = "notes.md") -> Dict[str, str]:
        """Saves text (notes exported as Markdown...) with a save dialog."""
        if not self._window:
            return {"status": "error"}
        dest = self._window.create_file_dialog(
            getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG,
            save_filename=suggested_name, file_types=("Markdown (*.md)", "All files (*.*)"))
        if not dest:
            return {"status": "cancelled"}
        dest = dest[0] if isinstance(dest, (list, tuple)) else dest
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "path": dest}

    def export_side_by_side(self) -> None:
        """Bilingual study copy (original | translation on each sheet)."""
        if not getattr(self, "_active_pdf_path", None) or not self._window:
            self._send_toast_i18n("toast_export_no_doc", "warning")
            return
        if not getattr(self, "_active_html_path", None):
            self._send_toast_i18n("toast_export_failed_extract", "error")
            return
        base = os.path.splitext(os.path.basename(self._active_pdf_path))[0]
        dest = self._window.create_file_dialog(
            getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG,
            save_filename=f"{base}_bilingual.pdf", file_types=("PDF Documents (*.pdf)",))
        if not dest:
            return
        dest = dest[0] if isinstance(dest, (list, tuple)) else dest

        def worker() -> None:
            from ..renderer import print_html_with_fallback
            from ..side_by_side import make_side_by_side
            html = translated_pdf = None
            self._send_js("window.dispatchEvent(new CustomEvent('app-busy', { detail: { on: true } }))")
            try:
                html = self._translated_html()
                fd, translated_pdf = tempfile.mkstemp(suffix=".pdf", prefix="rocktranslate-sbs-")
                os.close(fd)

                def on_progress(stage: str, done: int, total: int) -> None:
                    self._send_js("window.dispatchEvent(new CustomEvent('export-progress', "
                                  f"{{ detail: {json.dumps({'stage': stage, 'done': done, 'total': total})} }}))")

                if not html or not print_html_with_fallback(html, translated_pdf, progress=on_progress):
                    raise RuntimeError("printing failed")
                password = self._pdf_passwords.get(os.path.abspath(self._active_pdf_path))
                make_side_by_side(self._active_pdf_path, translated_pdf, dest, password=password)
                self._send_status_i18n("status_export_success", {"filename": os.path.basename(dest)})
                self._send_toast_i18n("toast_export_success", "success", duration=6000)
            except Exception as e:
                logger.error(f"Side-by-side export failed: {e}")
                self._send_toast_i18n("toast_export_error", "error", variables={"error": str(e)})
            finally:
                self._send_js("window.dispatchEvent(new CustomEvent('export-progress', { detail: { stage: 'end' } }))")
                self._send_js("window.dispatchEvent(new CustomEvent('app-busy', { detail: { on: false } }))")
                for p in (html, translated_pdf):
                    if p:
                        try:
                            os.unlink(p)
                        except OSError:
                            pass

        threading.Thread(target=worker, name="rocktranslate-sbs", daemon=True).start()
