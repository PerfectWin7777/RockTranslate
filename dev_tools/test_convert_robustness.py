"""Quick verification of the merged convert_pdf_to_html: real conversion with
progress, stall watchdog on a hung fake binary, and cache bypass."""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rocktranslate.core import html_transformer as ht

# ── Test 1: real conversion emits progress and returns the HTML path ──
src_pdf = os.path.join(os.path.dirname(__file__), "..", "1_PDFsam_Nsangou Ngapna et al._ASR_2024.pdf")
tmp = tempfile.mkdtemp(prefix="rt_convert_")
pdf_copy = os.path.join(tmp, "sample.pdf")
shutil.copy(src_pdf, pdf_copy)

pages = []
html = ht.convert_pdf_to_html(pdf_copy, on_progress=lambda c, t: pages.append((c, t)), stall_timeout=30.0)
assert html and os.path.exists(html) and os.path.getsize(html) > 0, "conversion failed"
assert pages, "no progress events received"
print(f"TEST1 OK: converted, {len(pages)} progress events, last={pages[-1]}, html={os.path.getsize(html)} bytes")

# ── Test 2: cache bypass on second call ──
t0 = time.time()
html2 = ht.convert_pdf_to_html(pdf_copy)
assert html2 == html
print(f"TEST2 OK: cache bypass returned in {time.time()-t0:.3f}s")

# ── Test 3: stall watchdog kills a hung binary ──
fake = os.path.join(tmp, "fake_pdf2htmlex.bat")
with open(fake, "w") as f:
    f.write("@echo off\r\necho Working: 1/10\r\nping -n 60 127.0.0.1 > nul\r\n")
orig = ht.check_and_download_pdf2htmlex
ht.check_and_download_pdf2htmlex = lambda assets_dir: fake
try:
    t0 = time.time()
    stall_pdf = os.path.join(tmp, "stall.pdf")
    shutil.copy(src_pdf, stall_pdf)
    result = ht.convert_pdf_to_html(stall_pdf, on_progress=None, stall_timeout=3.0)
    elapsed = time.time() - t0
    assert result is None, "watchdog should return None"
    assert elapsed < 15, f"watchdog took too long: {elapsed:.1f}s"
    print(f"TEST3 OK: stall detected and killed after {elapsed:.1f}s")
finally:
    ht.check_and_download_pdf2htmlex = orig

shutil.rmtree(tmp, ignore_errors=True)
print("ALL TESTS PASSED")
