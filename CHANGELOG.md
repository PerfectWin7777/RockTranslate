# Changelog

## 2.0.5 — 2026-11

### Translation quality & layout
- **Paragraph-level translation with justified reflow**: lines are regrouped into paragraphs from the page geometry, translated as whole sentences, then redistributed over the original lines with one uniform scale per paragraph, justified when the original was. Footnote markers, sub/superscripts and inline fragments are kept inside their paragraph.
- Justified (LaTeX / publisher) word spacing is no longer mistaken for table columns; tables are preserved.
- Fixed blank pages after every page on A4 publisher PDFs, per-page paper sizes (mixed portrait/landscape), names glued together ("KaimingHe"), mixed fonts inside a translated line, glyph corruption of Icelandic text and fractions.

### Speed & cost
- Windows: pdf2htmlEX 0.18.8 compiled natively for Windows x64 (replaces the 32-bit 0.14.6 build from 2015):
  1.4–2.5x faster conversions, no 32-bit memory limit, fixes of the 0.18 series.
- Concurrent requests (4 by default), source-text context so batches are independent.
- Hidden reasoning disabled for DeepSeek (≈5× faster, ≈4× cheaper, same quality).
- Real backoff on rate limits, request timeouts, omitted segments re-requested, hallucinated ids dropped.
- Translations cached and restored per document, model and language: nothing is paid twice.

### Reliability & security
- Hardened local file server (session token, allow-list, host check, no wildcard CORS).
- LLM output can no longer inject HTML/JS into the workspace.
- Copy-restricted PDFs open; password-protected PDFs ask for their password.
- Stop → Start can no longer resurrect a cancelled run or freeze the UI.
- `pip install "rocktranslate[gui]"` now ships the interface, PDF.js and fonts (they were missing from the wheel).
- pdf2htmlEX on Linux works without FUSE; engines are downloaded to the user folder; PDF printing falls back to a pinned `chrome-headless-shell` when the system browser fails.

### Interface
- Light / dark / system themes (Ctrl/⌘+Shift+D), redesigned menus, status bar, progress panel and dialogs.
- Unified Settings window (Ctrl/⌘+,) with auto-save, explanations, cache management and usage statistics.
- Live elapsed / remaining time, tokens and estimated cost; end-of-run summary.

### CLI & library
- Shared headless pipeline; `--pages`, `--parallel`, `--password`, `--keep-html`, `--base-url`; `rocktranslate doctor`.
- `RockTranslator.translate_document()` returns a detailed report (tokens, cost, time, failures).
