# Changelog

## 2.0.6 — 2026-11

### A PDF reader that understands the paper (new)
- **Selection bubble**: select a passage, read its translation or a plain explanation streamed in a bubble (~1 s to the first
  words); clean copy, copy with citation, highlight; the same actions in a right-click menu.
- **Link previews**: hover a citation, figure, table or equation link to see its target; "go there", DOI, "open & translate"
  for arXiv references.
- **Side panel**: contents (bookmarks, or detected headings) with per-section summaries, bilingual search, questions answered
  with verbatim quotes that open the exact passage, notes exported as Markdown, paper glossary applied to the translations.
- **Comfort**: continuous translation of the pages being read, resume at the last page, night reading (figures intact),
  hold Alt for the original, document tabs, command palette (Ctrl+K), snapshot of an area or a page to the clipboard.
- **Exports**: bilingual side-by-side PDF.
- **Reading comfort**: answers rendered as Markdown (bubble, summaries, questions) and always in the reading language;
  collapsible contents and summaries; document tabs shown from the first PDF, a PDF dropped on a pane opens in a new tab;
  the copied snapshot appears as a thumbnail; download progress when opening a link; estimated time left while the PDF
  export is written (learned from the previous exports).
- **Default reader**: open a PDF passed on the command line, single instance, "Open with RockTranslate" and an optional
  default-app task in the installer.
- **Figures as images in extraction**: every captioned figure (pictures and vector plots) is rendered as PNG, written
  beside the Markdown/JSON and linked (`![Figure 1](paper_images/page003_figure1.png)`); `Image` elements with
  `image_path` in JSON. On by default; `images=False` / `--no-images` turns it off.
- **Python API / CLI**: `translate_text`, `explain`, `summarize`, `glossary`, `ask`, `side_by_side`, `Document.toc()`;
  `rocktranslate ask | summarize | glossary | explain`, `--side-by-side`, `--glossary`, `--auto-glossary`.

### Fixes and improvements
- **Open a PDF from a link** (GUI field on the home screen, CLI, Python API); arXiv `/abs/` pages are resolved to their PDF.
- **Option to leave the references untranslated** (Preferences > Translation, CLI `--skip-references`, API `translate_references=False`).
- **Default model: Gemini 3.5 Flash-Lite** (`gemini/gemini-3.5-flash-lite`).
- **Layout**: lines broken by inline math (subscripts such as v<sub>l0</sub>, "CO<sub>2</sub>"), list items with a hanging indent and
  sentence double spaces are now kept in one paragraph: no more tiny or overlapping fragments. Lone lines may use the free
  room on their right instead of shrinking. "positionwise" style hyphen losses and the LaTeX "7→" arrow are fixed.
- **Progress**: the page counter now reaches the total (it followed the last batch received), and the PDF export shows the
  pages being prepared, then the printing step.
- Startup no longer opens, at times, without the saved API keys and recent files (UI read the settings before the bridge was ready).

## 2.0.5 — 2026-11

### Structured extraction (new)
- `rocktranslate.extract(pdf)`: typed, positioned elements (titles, sections with depth, paragraphs, lists,
  tables with cells, captions, formulas, footnotes, references, headers/footers), JSON (Unstructured-compatible),
  Markdown, RAG chunks, search and highlight in the original PDF. Local, free, no API key.
- `rocktranslate.translate(pdf, lang)`: the same Document with every element's aligned translation;
  bilingual Markdown. CLI: `rocktranslate extract`, `--format pdf,json,md,chunks`, `--bilingual`.

### Translation quality & layout
- **Paragraph-level translation with justified reflow**: lines are regrouped into paragraphs from the page geometry, translated as whole sentences, then redistributed over the original lines with one uniform scale per paragraph, justified when the original was. Footnote markers, sub/superscripts and inline fragments are kept inside their paragraph.
- Justified (LaTeX / publisher) word spacing is no longer mistaken for table columns; tables are preserved.
- Fixed blank pages after every page on A4 publisher PDFs, per-page paper sizes (mixed portrait/landscape), names glued together ("KaimingHe"), mixed fonts inside a translated line, glyph corruption of Icelandic text and fractions.

### Speed & cost
- The layout is prepared in the background as soon as a PDF opens: the first translation starts instantly.
- Exact line geometry with the installed Edge/Chrome (DevTools protocol), no extra download needed.
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
