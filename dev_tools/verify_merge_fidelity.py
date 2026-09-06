"""
Merge Fidelity Harness — the judge for the slice-merge engine (Step 1).

Protocol:
  1. Ground truth: the whole-document pdf2htmlEX conversion of Tankeu (out.html
     at the repo root, or regenerated sequentially if missing).
  2. Candidate: the same document converted as N parallel page slices, then
     merged with core/html_merger.merge_pdf2htmlex_slices.
  3. DOM-geometry diff (exhaustive, automated): for EVERY page, compare the
     multiset of element signatures (tag + canonical classes + style attr) and
     every canonical CSS rule value referenced by that page's elements.
  4. Pixel diff: both documents are printed to vector PDF with the same
     production renderer (headless Chrome), rasterized page-by-page with
     pypdfium2, and compared pixel-wise. Worst pages are exported as PNG.

Exit code 0 only when both diffs are clean.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PDF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Tankeu et al. 2026.pdf"))
GROUND_TRUTH_HTML = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "out.html"))
REPORT_DIR = os.path.join(os.path.dirname(__file__), "fidelity_report")
N_SLICES = 4
PIXEL_SCALE = 2.0


# ─────────────────────────────── helpers ───────────────────────────────

def canonical_token(token: str) -> str:
    return re.sub(r"_s\d+$", "", token)


def build_css_map(css_text: str) -> dict:
    """selector -> body, flattened: @media / @-moz-document wrappers are opened
    so inner geometry rules (the vast majority in pdf2htmlEX output) are
    directly comparable between the merged doc and the ground truth."""
    import tinycss2

    def walk(rules, out: dict) -> None:
        for rule in rules:
            if rule.type == "error":
                continue
            if rule.type == "qualified-rule":
                sel = tinycss2.serialize(rule.prelude).strip()
                body = tinycss2.serialize(rule.content or []).strip()
                out.setdefault(sel, set()).add(body)
            elif rule.type == "at-rule":
                if rule.lower_at_keyword in ("media", "supports", "-moz-document") and rule.content is not None:
                    walk(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True), out)

    out: dict = {}
    walk(tinycss2.parse_stylesheet(css_text, skip_comments=True, skip_whitespace=True), out)
    return out


def page_fingerprint(soup, page_el, css_map: dict) -> dict:
    """
    Canonical fingerprint of one page: element signatures + the canonical CSS
    values every class used on this page resolves to. Lookup uses the RAW
    (possibly suffixed, e.g. 'y30_s0') class names — exactly how the browser
    resolves them — then canonicalizes keys and font-family references so the
    merged document can be compared with the ground truth.
    """
    elements = []
    used_classes = set()
    for el in page_el.find_all(True):
        raw_classes = tuple(el.get("class") or [])
        elements.append((el.name, tuple(sorted(canonical_token(c) for c in raw_classes)),
                         el.get("style", "")))
        used_classes.update(raw_classes)

    css_values = {}
    for cls in used_classes:
        for sel, bodies in css_map.items():
            if re.search(rf"\.{re.escape(cls)}(?![A-Za-z0-9_-])", sel):
                key = canonical_token(cls)
                css_values.setdefault(key, set()).update(
                    canonical_css_body(b) for b in bodies)

    return {
        "elements": Counter(elements),
        "css": {k: sorted(v) for k, v in css_values.items()},
        "text": re.sub(r"\s+", " ", page_el.get_text()).strip(),
    }


def canonical_css_body(body: str) -> str:
    """Strips slice suffixes from font-family references inside rule bodies."""
    return re.sub(r"\b(ff[0-9a-zA-Z]+)_s\d+", r"\1", body)


def all_page_fingerprints(html_path: str) -> dict:
    from bs4 import BeautifulSoup
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    css_map = {}
    for style in soup.find_all("style"):
        for sel, bodies in build_css_map(style.get_text()).items():
            css_map.setdefault(sel, set()).update(bodies)

    pages = {}
    for el in soup.find_all(id=re.compile(r"^pf[0-9a-fA-F]+$")):
        page_no = int(el["id"][2:], 16)
        pages[page_no] = page_fingerprint(soup, el, css_map)
    return pages


def diff_fingerprints(truth: dict, merged: dict) -> list:
    issues = []
    for page_no in sorted(truth.keys()):
        if page_no not in merged:
            issues.append(f"page {page_no}: MISSING in merged document")
            continue
        t, m = truth[page_no], merged[page_no]
        if t["text"] != m["text"]:
            issues.append(f"page {page_no}: TEXT differs")
        if t["elements"] != m["elements"]:
            missing = t["elements"] - m["elements"]
            extra = m["elements"] - t["elements"]
            issues.append(f"page {page_no}: ELEMENTS differ "
                          f"(missing={sum(missing.values())}, extra={sum(extra.values())})")
        for cls, t_vals in t["css"].items():
            m_vals = m["css"].get(cls)
            if m_vals != t_vals:
                issues.append(f"page {page_no}: CSS value differs for class '{cls}': "
                              f"truth={t_vals} merged={m_vals}")
    for page_no in sorted(set(merged.keys()) - set(truth.keys())):
        issues.append(f"page {page_no}: UNEXPECTED page in merged document")
    return issues


# ─────────────────────────────── pixel diff ───────────────────────────────

def print_to_pdf(html_path: str, out_pdf: str, page_size_css: str, work_dir: str) -> None:
    """Prints exactly like the production export: a final @page override with
    the document's real size and margin 0, so each .pf page maps to exactly
    one PDF page (pdf2htmlEX's own @page sets margin only — without the
    explicit size Chrome paginates onto default A4 pages)."""
    from rocktranslate.core.renderer import resolve_pdf_renderer, print_html_to_vector_pdf
    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()
    # Mimic the production export: the iframe DOM carries the runtime body
    # zoom (default 0.8), which is what makes content fit the physical page.
    page_style = f"<style>body {{ zoom: 0.8; }} @page {{ size: {page_size_css}; margin: 0; }} body {{ margin: 0; padding: 0; }}</style>"
    if "</head>" in html:
        html = html.replace("</head>", f"{page_style}\n</head>", 1)
    else:
        html += page_style
    printed_name = os.path.splitext(os.path.basename(html_path))[0] + "_printed.html"
    printed_html = os.path.join(work_dir, printed_name)
    with open(printed_html, "w", encoding="utf-8") as f:
        f.write(html)
    browser = resolve_pdf_renderer()
    if not browser:
        raise RuntimeError("No Chromium browser available for printing")
    ok = print_html_to_vector_pdf(browser, printed_html, out_pdf)
    if not ok or not os.path.exists(out_pdf):
        raise RuntimeError(f"Printing failed for {printed_html}")


def pixel_diff(truth_pdf: str, merged_pdf: str, report_dir: str, expected_pages: int) -> dict:
    import pypdfium2 as pdfium
    from PIL import Image, ImageChops

    doc_t, doc_m = pdfium.PdfDocument(truth_pdf), pdfium.PdfDocument(merged_pdf)
    counts = {"truth_pdf_pages": len(doc_t), "merged_pdf_pages": len(doc_m)}
    if len(doc_t) != expected_pages or len(doc_m) != expected_pages:
        return {"status": "PAGINATION_MISMATCH", **counts,
                "note": "Print pagination diverged; per-page pixel comparison not meaningful."}
    n = len(doc_t)
    per_page = []
    worst = []
    for i in range(n):
        img_t = doc_t[i].render(scale=PIXEL_SCALE).to_pil().convert("RGB")
        img_m = doc_m[i].render(scale=PIXEL_SCALE).to_pil().convert("RGB")
        if img_t.size != img_m.size:
            per_page.append({"page": i + 1, "size_mismatch": [img_t.size, img_m.size], "diff_ratio": 1.0})
            continue
        diff = ImageChops.difference(img_t, img_m)
        hist = diff.convert("L").histogram()
        changed = sum(hist[1:])
        total = img_t.size[0] * img_t.size[1]
        ratio = changed / total
        per_page.append({"page": i + 1, "diff_ratio": round(ratio, 6),
                         "changed_px": changed, "total_px": total})
        worst.append((ratio, i + 1))
    worst.sort(reverse=True)

    for ratio, page_no in worst[:3]:
        if ratio <= 0:
            break
        img_t = doc_t[page_no - 1].render(scale=PIXEL_SCALE).to_pil().convert("RGB")
        img_m = doc_m[page_no - 1].render(scale=PIXEL_SCALE).to_pil().convert("RGB")
        w = img_t.width + img_m.width + 12
        canvas = Image.new("RGB", (w, max(img_t.height, img_m.height)), (255, 255, 255))
        canvas.paste(img_t, (0, 0))
        canvas.paste(img_m, (img_t.width + 12, 0))
        canvas.save(os.path.join(report_dir, f"page_{page_no:02d}_truth_vs_merged.png"))

    return {
        "pages_compared": n,
        "identical_pages": sum(1 for p in per_page if p.get("diff_ratio") == 0),
        "worst_pages": [{"page": p, "diff_ratio": round(r, 6)} for r, p in worst[:5]],
        "mean_diff_ratio": round(sum(p["diff_ratio"] for p in per_page) / max(n, 1), 8),
        "per_page": per_page,
    }


def convert_ranges_adaptive(pdf_path: str, initial_ranges: list, parent_dir: str,
                            max_workers: int = 4) -> tuple:
    """
    Converts page ranges in parallel with adaptive bisection: the legacy 0.14.6
    binary crashes ('Cannot save font … fe.woff') on SOME page-range combinations
    while converting both sub-ranges (and the whole document) successfully.
    A failing range is split in half and retried until it converges to healthy
    sub-ranges; a failing single page is excluded and reported. Under parallel
    CPU contention progress lines can be delayed, so the inactivity watchdog is
    relaxed to 90s per worker (a genuine hang is infinite, a contention pause
    is not).
    """
    from rocktranslate.core.html_transformer import convert_pdf_to_html

    segments = []
    failed_pages = []
    stats = {"initial_ranges": len(initial_ranges), "bisections": 0, "failed_ranges": []}
    pending = list(initial_ranges)

    while pending:
        current, pending = pending, []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {}
            for (f, l) in current:
                out_dir = os.path.join(parent_dir, f"r{f}_{l}")
                os.makedirs(out_dir, exist_ok=True)
                env = dict(os.environ)
                env["TEMP"] = out_dir
                env["TMP"] = out_dir
                futs[pool.submit(convert_pdf_to_html, pdf_path, output_dir=out_dir,
                                 env=env, first_page=f, last_page=l,
                                 stall_timeout=90.0)] = (f, l)
            for fut, (f, l) in futs.items():
                html = None
                try:
                    html = fut.result()
                except Exception:
                    pass
                if html is None:
                    if l - f + 1 > 1:
                        mid = (f + l) // 2
                        pending.append((f, mid))
                        pending.append((mid + 1, l))
                        stats["bisections"] += 1
                    else:
                        failed_pages.append(f)
                        stats["failed_ranges"].append((f, l))
                else:
                    segments.append({"html": html, "first": f, "last": l})

    segments.sort(key=lambda s: s["first"])
    return segments, sorted(set(failed_pages)), stats


# ─────────────────────────────── pipeline ───────────────────────────────

def main():
    from rocktranslate.core.html_transformer import convert_pdf_to_html
    from rocktranslate.core.html_merger import merge_pdf2htmlex_slices
    from pypdf import PdfReader

    os.makedirs(REPORT_DIR, exist_ok=True)
    # Work on D: (dev_tools/fidelity_report/work): C: is critically low on
    # space and tempfile defaults to C:\...\Temp.
    work = os.path.join(REPORT_DIR, "work")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    results = {"n_slices": N_SLICES, "source": os.path.basename(PDF_PATH)}

    try:
        total_pages = len(PdfReader(PDF_PATH).pages)
        results["total_pages"] = total_pages
        base = total_pages // N_SLICES
        ranges = []
        start = 1
        for k in range(N_SLICES):
            end = start + base - 1 + (1 if k < total_pages % N_SLICES else 0)
            ranges.append((start, end))
            start = end + 1
        results["slice_ranges"] = ranges
        print(f"[1/5] Slicing {total_pages} pages into {N_SLICES} slices: {ranges}")

        # 1. Convert page ranges IN PARALLEL on the ORIGINAL file with pdf2htmlEX
        #    -f/-l and adaptive bisection: the legacy binary crashes on certain
        #    page-range combinations ('Cannot save font … fe.woff') while both
        #    sub-ranges and the whole document convert fine. Converted segments
        #    are cached on disk (dev_tools/fidelity_cache) to iterate quickly.
        print(f"[1/5] Converting {total_pages} pages as {N_SLICES} parallel ranges (adaptive bisection)…")
        t0 = time.time()
        cache_dir = os.path.join(REPORT_DIR, "fidelity_cache")
        os.makedirs(cache_dir, exist_ok=True)
        segments, failed_pages, conv_stats = convert_ranges_adaptive(
            PDF_PATH, ranges, cache_dir, max_workers=N_SLICES)
        results["conversion"] = {
            **conv_stats,
            "failed_pages": failed_pages,
            "segments": [{"first": s["first"], "last": s["last"]} for s in segments],
            "elapsed_s": round(time.time() - t0, 1),
        }
        print(f"      {len(segments)} healthy segments ({conv_stats['bisections']} bisections, "
              f"failed pages: {failed_pages or 'none'}) in {results['conversion']['elapsed_s']}s "
              f"(sequential reference: 282s)")

        # 2. Merge
        print("[2/5] Merging segments with CSS namespacing…")
        t0 = time.time()
        merged_html = os.path.join(work, "merged.html")
        results["merge_stats"] = merge_pdf2htmlex_slices(
            [s["html"] for s in segments], [s["first"] - 1 for s in segments], merged_html)
        results["merge_stats"]["elapsed_s"] = round(time.time() - t0, 1)
        results["merged_size_mb"] = round(os.path.getsize(merged_html) / 1e6, 1)
        print(f"      merged in {results['merge_stats']['elapsed_s']}s -> {results['merged_size_mb']} MB")

        # 3. Ground truth
        print("[3/5] Loading ground truth (whole-document conversion)…")
        if not os.path.exists(GROUND_TRUTH_HTML):
            print("      out.html missing — regenerating sequentially (slow)…")
            gt = convert_pdf_to_html(PDF_PATH, output_dir=work)
            if not gt:
                raise RuntimeError("Ground truth conversion failed")
            shutil.copy(gt, GROUND_TRUTH_HTML)
        results["truth_size_mb"] = round(os.path.getsize(GROUND_TRUTH_HTML) / 1e6, 1)

        # 4. DOM-geometry diff
        print("[4/5] Exhaustive DOM-geometry diff (all pages)…")
        t0 = time.time()
        truth_fp = all_page_fingerprints(GROUND_TRUTH_HTML)
        merged_fp = all_page_fingerprints(merged_html)
        issues = diff_fingerprints(truth_fp, merged_fp)
        results["dom_diff"] = {
            "pages_truth": len(truth_fp), "pages_merged": len(merged_fp),
            "issues": issues[:40], "issue_count": len(issues),
            "elapsed_s": round(time.time() - t0, 1),
        }
        dom_pass = not issues
        print(f"      {'PASS' if dom_pass else 'FAIL'} — {len(issues)} issue(s) "
              f"across {len(truth_fp)} pages in {results['dom_diff']['elapsed_s']}s")
        for issue in issues[:10]:
            print(f"        - {issue}")

        # 5. Pixel diff (same production print pipeline: @page size from metadata)
        print("[5/5] Printing both documents and rasterizing for pixel diff…")
        t0 = time.time()
        from rocktranslate.core.pdf_metadata import get_pdf_metadata
        size_match = re.search(r"\[([\d\.]+)\s*x\s*([\d\.]+)\s*cm\]",
                               get_pdf_metadata(PDF_PATH).get("page_size", ""))
        page_size_css = f"{size_match.group(1)}cm {size_match.group(2)}cm" if size_match else "A4"
        truth_pdf = os.path.join(work, "truth.pdf")
        merged_pdf = os.path.join(work, "merged.pdf")
        print_to_pdf(GROUND_TRUTH_HTML, truth_pdf, page_size_css, work)
        print_to_pdf(merged_html, merged_pdf, page_size_css, work)
        results["pixel_diff"] = pixel_diff(truth_pdf, merged_pdf, REPORT_DIR, total_pages)
        results["pixel_diff"]["elapsed_s"] = round(time.time() - t0, 1)
        pd = results["pixel_diff"]
        pixel_pass = pd.get("status") != "PAGINATION_MISMATCH" and             pd["pages_compared"] == total_pages and pd["mean_diff_ratio"] < 0.0005
        print(f"      {'PASS' if pixel_pass else 'FAIL'} — {pd['identical_pages']}/{pd['pages_compared']} "
              f"identical pages, mean diff {pd['mean_diff_ratio']*100:.4f}% "
              f"(worst: {pd['worst_pages'][:3]}) in {pd['elapsed_s']}s")

        results["verdict"] = "PASS" if (dom_pass and pixel_pass) else "FAIL"
        with open(os.path.join(REPORT_DIR, "report.json"), "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nVERDICT: {results['verdict']}  (report: dev_tools/fidelity_report/report.json)")
        return 0 if results["verdict"] == "PASS" else 1

    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
