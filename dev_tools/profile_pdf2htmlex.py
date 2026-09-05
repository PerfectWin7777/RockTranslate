"""
Profiles pdf2htmlEX on a page slice of the Tankeu reference PDF.
Answers two questions with real numbers:
  1. Where does conversion time go (preprocessing vs working vs assembly)?
  2. Is the cost proportional to the number of pages (slice viability)?

No RockTranslate code involved: raw binary, relative paths (0.14.6 limitation).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

PDF_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Tankeu et al. 2026.pdf"))
EXE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "rocktranslate",
                                   "assets", "pdf2htmlEX", "pdf2htmlEX.exe"))


def make_slice(src_pdf: str, page_numbers: List[int], out_pdf: str) -> None:
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(src_pdf)
    writer = PdfWriter()
    for p in page_numbers:
        writer.add_page(reader.pages[p - 1])
    with open(out_pdf, "wb") as f:
        writer.write(f)


def profile_conversion(pdf_file: str, work_dir: str) -> dict:
    """Runs pdf2htmlEX in work_dir with relative names, timestamping stderr phases."""
    cmd = [EXE, "--zoom", "1.3", pdf_file, "out.html"]
    t_start = time.time()
    proc = subprocess.Popen(cmd, cwd=work_dir, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True,
                            bufsize=1, universal_newlines=True)
    phases = {"preprocess": [None, None], "working": [None, None]}
    last_line = ""
    for line in proc.stderr:
        now = time.time() - t_start
        last_line = line.strip()
        if "Preprocessing:" in line:
            if phases["preprocess"][0] is None:
                phases["preprocess"][0] = now
            phases["preprocess"][1] = now
        elif "Working:" in line:
            if phases["working"][0] is None:
                phases["working"][0] = now
            phases["working"][1] = now
    proc.wait()
    total = time.time() - t_start
    out_html = os.path.join(work_dir, "out.html")
    size_mb = os.path.getsize(out_html) / (1024 * 1024) if os.path.exists(out_html) else 0
    return {
        "exit_code": proc.returncode,
        "total_s": total,
        "preprocess_s": (phases["preprocess"][1] - phases["preprocess"][0])
                         if all(phases["preprocess"]) else 0.0,
        "working_s": (phases["working"][1] - phases["working"][0])
                      if all(phases["working"]) else 0.0,
        "assembly_s": total - (phases["working"][1] if phases["working"][1] else 0),
        "html_mb": size_mb,
        "tail": last_line,
    }


def main():
    tmp = tempfile.mkdtemp(prefix="rt_profile_")
    try:
        # ── Reference: 5-page slice (pages 20-24, dense body content) ──
        slice_pdf = os.path.join(tmp, "slice5.pdf")
        t0 = time.time()
        make_slice(PDF_PATH, [20, 21, 22, 23, 24], slice_pdf)
        slice_prep = time.time() - t0

        r = profile_conversion("slice5.pdf", tmp)
        print(f"SLICE 5 pages  : total={r['total_s']:6.1f}s | preprocess={r['preprocess_s']:6.1f}s | "
              f"working={r['working_s']:6.1f}s | html={r['html_mb']:.1f} MB | exit={r['exit_code']}")

        # ── Second measurement: 15-page slice to check linear scaling ──
        tmp2 = tempfile.mkdtemp(prefix="rt_profile2_")
        try:
            slice15 = os.path.join(tmp2, "slice15.pdf")
            make_slice(PDF_PATH, list(range(15, 30)), slice15)
            r2 = profile_conversion("slice15.pdf", tmp2)
            print(f"SLICE 15 pages : total={r2['total_s']:6.1f}s | preprocess={r2['preprocess_s']:6.1f}s | "
                  f"working={r2['working_s']:6.1f}s | html={r2['html_mb']:.1f} MB | exit={r2['exit_code']}")
        finally:
            shutil.rmtree(tmp2, ignore_errors=True)

        print(f"(pypdf slice creation: {slice_prep:.2f}s)")
        print("REFERENCE full 40 pages (from earlier runs): total=282s, html=33.7 MB")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
