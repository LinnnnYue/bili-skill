"""Analyze Bilibili comments: top-liked threads and keyword themes."""
import json
import re
import sys
from collections import Counter

PATH = sys.argv[1] if len(sys.argv) > 1 else "tmp_bili_extract/comments_raw.json"
TOP_N = int(sys.argv[2]) if len(sys.argv) > 2 else 45

data = json.load(open(PATH, encoding="utf-8"))
items = data["items"]
print(f"items={len(items)} total_fetched={data['total_fetched_comments']} all_count={data['wbi_main_all_count']}")


def clean(text):
    text = re.sub(r"\[[^\]]{1,12}\]", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ── 2026-10-28 ROUND 02 修（D15）：B 站两种评论接口形态并存，须兼容
#    新版 /x/v2/reply/main：用户名在 member.uname、正文在 content.message
#    旧版 /x/v2/reply：扁平 uname / message
def uname(c):
    return ((c.get("member") or {}).get("uname")
            or c.get("uname") or "匿名")


def body(c):
    return clean((c.get("content") or {}).get("message") or c.get("message") or "")


def kids_of(c):
    return c.get("replies") or c.get("children") or []


rows = sorted(items, key=lambda x: -(x.get("like") or 0))
print("\n===== TOP LEVEL COMMENTS BY LIKES =====")
for i, c in enumerate(rows[:TOP_N], 1):
    kids = kids_of(c)
    print(f"\n[{i}] like={c.get('like')} reply={c.get('rcount')} user={uname(c)}")
    print(body(c)[:400])
    top_kids = sorted(kids, key=lambda k: -(k.get("like") or 0))[:3]
    for k in top_kids:
        if (k.get("like") or 0) >= 5:
            print(f"    └ like={k.get('like')} {uname(k)}: {body(k)[:200]}")

all_text = " ".join(body(c) for c in items)
for c in items:
    for k in (c.get("replies") or []):
        all_text += " " + body(k)

print("\n===== KEYWORD FREQ（从当前语料派生，不再硬编码话题词表）=====")
# 2026-10-28 ROUND 02：旧版 57 词硬编码表含「〈上一份报告的人物名〉/高考/志愿/小镇做题家」等，
# 属上一份报告的话题指纹，跨视频会给出误导性零值。改为 2–4 字 n-gram 派生。
STOP = {"这个", "那个", "我们", "你们", "他们", "自己", "就是", "还是", "可以", "没有",
        "什么", "怎么", "因为", "所以", "但是", "如果", "已经", "现在", "真的", "感觉",
        "觉得", "视频", "一个", "一下", "不是", "什么", "时候", "知道", "看到"}
cnt = Counter()
for n in (2, 3, 4):
    for i in range(len(all_text) - n + 1):
        frag = all_text[i:i + n]
        if re.search(r"[\s\d\W]", frag) or frag in STOP or re.fullmatch(r"[A-Za-z]+", frag):
            continue
        cnt[frag] += 1
ranked = [(w, c) for w, c in cnt.most_common(200) if c >= 2]
keep = []
for w, c in ranked:                      # 去子串重复（「光刻」与「光刻机」只留长的）
    if any(w != k and w in k for k, _ in keep):
        continue
    keep.append((w, c))
    if len(keep) >= 25:
        break
for w, n in keep:
    print(f"{w}\t{n}")
if not keep:
    print("（语料不足，无 2 次以上重复词）")
