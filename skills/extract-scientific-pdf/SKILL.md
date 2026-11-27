---
name: extract-scientific-pdf
description: Turn a scientific or technical PDF into clean structured data - titles, sections, paragraphs, lists, tables cell by cell, figure captions, formulas, footnotes and figures as PNG images, each element with its page and exact position. Outputs JSON, Markdown and retrieval-ready chunks (RAG). Runs locally, free, no API key. Use when the user wants the text, tables or figures of a PDF, a Markdown version of a paper, or to index papers for search or a RAG pipeline.
---

# Extract the structure of a scientific PDF

This skill uses **RockTranslate**'s extraction engine (open source, MIT). It reads
the exact layout of each page (pdf2htmlEX + a headless browser), so columns,
reading order, tables and captions come out right on dense two-column papers.
Everything runs on the user's machine: no upload, no LLM, no cost.

## 1. Setup (once per machine)

```bash
python3 scripts/rt_setup.py        # Windows: python scripts\rt_setup.py
```

Use the path printed on the last line (`RT=...`) as the `rocktranslate`
command below. macOS needs `brew install pdf2htmlex` first.

## 2. Extract

```bash
RT extract paper.pdf                         # -> paper.json + paper.md (+ paper_images/)
RT extract paper.pdf -f json,md,chunks       # + paper.chunks.json for RAG
RT extract paper.pdf -p 3-7 -o out/section   # some pages, custom output base path
RT extract https://arxiv.org/abs/1706.03762  # links work (arXiv /abs/ resolved)
RT extract paper.pdf --no-images             # text only, faster
```

About 1-2 seconds per page after the first run. For a folder of PDFs, loop over
the files; outputs go next to each PDF unless `-o` is given.

## 3. What you get

- **`paper.json`**: a list of elements. Each has `type`, `text`, `metadata.page_number`,
  `metadata.coordinates` (box in PDF points), and for tables `metadata.text_as_html`
  (cells with rowspan/colspan). Types: `Title`, `Section`, `NarrativeText`, `ListItem`,
  `Table`, `TableCaption`, `FigureCaption`, `Image`, `Formula`, `Footnote`, `Reference`,
  `Header`, `Footer`, `FigureText` (labels inside figures), `UncategorizedText`.
  Coordinates are 4 points in PDF points, origin top-left.
- **`paper.md`**: clean Markdown (headings, paragraphs, lists, Markdown tables, captions,
  figures linked as `![Figure 3](paper_images/page004_figure1.png)`).
- **`paper.chunks.json`**: section-aware chunks (never mixing two sections, never cutting an
  element), each with its pages and boxes, ready for embedding.
- **`paper_images/`**: every captioned figure rendered as PNG (vector plots included).

## 4. Typical follow-ups (do them for the user when asked)

```python
import json
els = json.load(open("paper.json", encoding="utf-8"))
tables = [e for e in els if e["type"] == "Table"]                 # tables as HTML
abstract = next(e["text"] for e in els if e["type"] == "NarrativeText")
captions = [e["text"] for e in els if e["type"] == "FigureCaption"]
```

Python API, when writing code is easier than the CLI:

```python
import rocktranslate
doc = rocktranslate.extract("paper.pdf", pages="1-5")
doc.to_markdown("paper.md"); doc.to_json("paper.json")
chunks = doc.chunks(max_characters=1500)
hits = doc.search("dropout")          # elements containing a phrase, with page + box
```

## Limits to mention when relevant

- Scanned PDFs (images only, no text layer) are not supported (no OCR).
- Tables drawn as one single text run per row may come out as text lines.
- Password-protected PDFs need `--password`.
