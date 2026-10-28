"""Export danmaku as a time-ordered timeline to help reconstruct video structure."""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "tmp_bili_extract/danmaku2.xml"
BUCKET = int(sys.argv[2]) if len(sys.argv) > 2 else 60

root = ET.parse(PATH).getroot()
rows = []
for d in root.findall("d"):
    p = (d.get("p") or "").split(",")
    if len(p) < 8:
        continue
    t = (d.text or "").strip()
    if t:
        rows.append((float(p[0]), t))

rows.sort()
groups = defaultdict(list)
for t, text in rows:
    groups[int(t // BUCKET)].append(text)

for k in sorted(groups):
    seen, uniq = set(), []
    for t in groups[k]:
        if t in seen or len(t) < 2:
            continue
        seen.add(t)
        uniq.append(t)
    m = k * BUCKET // 60
    s = k * BUCKET % 60
    print(f"\n[{m:02d}:{s:02d}] ({len(groups[k])} 条) " + " / ".join(uniq[:14]))
