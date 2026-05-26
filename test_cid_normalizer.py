"""
test_cid_normalizer.py — Valide la résolution CID sur ton PDF
Usage: python test_cid_normalizer.py <pdf_path> <page_num>
"""
import sys, os
sys.path.insert(0, os.path.abspath("src"))

import fitz
from core.cid_normalizer import build_cid_map, normalize_cids

PDF_PATH = sys.argv[1] if len(sys.argv) > 1 else "Nsangou Ngapna et al._ASR_2024.pdf"
PAGE_NUM = int(sys.argv[2]) if len(sys.argv) > 2 else 6

doc = fitz.open(PDF_PATH)

print(f"=== Construction de la table CID depuis ToUnicode embarqué ===\n")
cid_map = build_cid_map(doc)

print(f"\n10 premiers mappings trouvés:")
for k, v in list(cid_map.items())[:10]:
    print(f"  CID {k:5d} → '{v}' (U+{ord(v):04X})")

# Test sur le texte de la page
page = doc[PAGE_NUM - 1]
raw_text = page.get_text("text")

# Trouve toutes les occurrences (cid:X) dans la page
import re
cid_occurrences = re.findall(r"\(cid:\d+\)", raw_text)
print(f"\nPage {PAGE_NUM} — {len(cid_occurrences)} occurrences (cid:X) trouvées")
print(f"Exemples bruts : {cid_occurrences[:10]}")

# Applique la normalisation
normalized = normalize_cids(raw_text, cid_map)
remaining  = re.findall(r"\(cid:\d+\)", normalized)

print(f"\nAprès normalisation : {len(remaining)} (cid:X) restants")
print(f"Taux de résolution : {(1 - len(remaining)/max(len(cid_occurrences),1))*100:.1f}%")

# Montre quelques exemples avant/après
print("\nExemples avant → après :")
samples = [
    "(cid:1)88.89",
    "(cid:3)0.5",
    "(cid:8)Rr",
    "class(cid:3)1",
]
for s in samples:
    result = normalize_cids(s, cid_map)
    status = "✅" if result != s else "❌"
    print(f"  {status} '{s}' → '{result}'")

doc.close()