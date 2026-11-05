"""
Table integrity check: compares how two instrumentation versions cut the
lines of a document into translation segments (cells), WITHOUT any LLM call.

A line cut into N segments by the reference version (e.g. the 2.0.2 line-by-
line pipeline, which keeps table cells apart) but into fewer segments by the
candidate version means table cells were merged — the bug to avoid.

Usage:
    python dev_tools/table_integrity_check.py reference_workspace.html candidate_workspace.html

Both files must be instrumented from the SAME raw pdf2htmlEX HTML.
Exit code 1 when merged cells are found.
"""

import html as html_lib
import re
import sys
from typing import List, Tuple

from bs4 import BeautifulSoup


def line_cells(path: str) -> List[Tuple[int, List[str]]]:
    """For every div.t line (document order): (page index, [segment texts])."""
    with open(path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "lxml")
    out = []
    for p_idx, page in enumerate(soup.find_all("div", class_="pf")):
        for div in page.find_all("div", class_="t"):
            cells = []
            for span in div.find_all("span", attrs={"data-trans-id": True}):
                orig = span.get("data-orig-html") or ""
                text = BeautifulSoup(html_lib.unescape(orig), "lxml").get_text() if orig else span.get_text()
                cells.append(re.sub(r"\s+", " ", text).strip())
            out.append((p_idx, cells))
    return out


def compare(reference: str, candidate: str) -> int:
    ref, cand = line_cells(reference), line_cells(candidate)
    if len(ref) != len(cand):
        print(f"! different line counts: {len(ref)} vs {len(cand)} (not the same raw HTML?)")
    merged = 0
    for (page, r_cells), (_p, c_cells) in zip(ref, cand):
        if len(r_cells) >= 2 and len(c_cells) < len(r_cells):
            merged += 1
            print(f"page {page + 1}: {len(r_cells)} cells -> {len(c_cells)}")
            print(f"    before: {r_cells}")
            print(f"    after : {c_cells}")
    multi = sum(1 for _p, cells in ref if len(cells) >= 2)
    print(f"multi-cell lines in reference: {multi} | merged in candidate: {merged}")
    return merged


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(1 if compare(sys.argv[1], sys.argv[2]) else 0)
