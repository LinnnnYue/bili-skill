"""Parse Bilibili danmaku XML into stats + representative comments."""
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter

PATH = sys.argv[1] if len(sys.argv) > 1 else "tmp_bili_extract/danmaku2.xml"
tree = ET.parse(PATH)
root = tree.getroot()
rows = []
for d in root.findall("d"):
    p = (d.get("p") or "").split(",")
    if len(p) < 8:
        continue
    rows.append({"time": float(p[0]), "mode": int(p[1]), "text": (d.text or "").strip()})

print("danmaku_total", len(rows))
texts = [r["text"] for r in rows if r["text"]]
cnt = Counter(texts)
print("\n=== TOP REPEATED DANMAKU ===")
for t, n in cnt.most_common(30):
    print(n, t)

print("\n=== TIME BUCKETS (5min) ===")
buckets = Counter(int(r["time"] // 300) for r in rows)
for k in sorted(buckets):
    print(f"{k*5:>3}-{k*5+5:>3}min  {buckets[k]}")

print("\n=== DANMAKU THROUGHOUT (first appearance order, dedup) ===")
seen = set()
for r in sorted(rows, key=lambda x: x["time"]):
    t = r["text"]
    if t in seen or len(t) < 4:
        continue
    seen.add(t)
print("unique", len(seen))
