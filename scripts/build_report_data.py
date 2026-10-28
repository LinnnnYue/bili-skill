"""聚合 B 站素材为 report_data.json（供 build_report.py 注入模板）。

2026-10-28 ROUND 02 整改（DSH D9/D10/D14）：
- 阵营分类器改为**中性情绪三档**，不含任何人物/议题专有词（旧版硬编码「批判/肯定〈上一份报告的人物名〉」，
  会把上一份报告的话题污染到任意视频）。
- 关键词不再硬编码 20 词；默认不写入 payload（模板不渲染，写了就是死数据 + 话题泄漏）；
  需要时用 --with-kw 从**当前视频**标题/简介/评论派生。
- 弹幕 XML 缺失不再整链崩：降级为 0 条并写 meta.data_warnings，报告如实记 0。
- 评论文件缺键时直接指出缺哪个键，不裸抛 KeyError。

用法:
  python build_report_data.py [--src tmp_bili_extract] [--out <path>] [--with-kw]
"""
import argparse
import datetime as dt
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# ── 情绪词表（通用，禁止出现具体人物/事件/议题名） ───────────────────────────
NEG_WORDS = [
    "骗", "坑", "翻车", "垃圾", "恶心", "失望", "退钱", "割韭菜", "智商税", "无语",
    "拉黑", "举报", "虚假", "营销号", "标题党", "吃相", "傲慢", "收割", "焦虑",
    "下头", "洗白", "打脸", "不值", "劝退", "套路",
]
POS_WORDS = [
    "有用", "感谢", "受益", "学到", "良心", "靠谱", "支持", "点赞", "真好", "干货",
    "清晰", "解决了", "推荐", "好用", "舒服", "惊艳", "细致", "到位", "省事", "效率",
]
NEU_WORDS = [
    "客观", "理性", "两面", "反思", "见仁见智", "各有", "双刃剑", "看情况", "不好说",
    "各取所需", "因人而异",
]

# 派生关键词时的停用词（结构词，不含话题词）
STOP = {
    "这个", "那个", "我们", "你们", "他们", "自己", "就是", "还是", "可以", "没有", "什么",
    "怎么", "为什么", "因为", "所以", "但是", "如果", "已经", "现在", "真的", "感觉", "觉得",
    "视频", "up", "UP", "一个", "这个", "一下", "不", "了", "的", "是", "在", "有", "和",
}


def clean(t: str) -> str:
    t = re.sub(r"\[[^\]]{1,12}\]", "", t or "")
    t = re.sub(r"回复 @[^:：]+ ?[:：]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def sentiment(text: str) -> str:
    """中性三档：负面 / 中性 / 正面。启发式词表命中计数，不做模型推断。"""
    neg = sum(1 for w in NEG_WORDS if w in text)
    pos = sum(1 for w in POS_WORDS if w in text)
    neu = sum(1 for w in NEU_WORDS if w in text)
    if neu and neu >= max(neg, pos):
        return "中性"
    if neg > pos:
        return "负面"
    if pos > neg:
        return "正面"
    return "中性"


def derive_keywords(meta: dict, items: list, top: int = 12) -> list:
    """从当前视频标题/简介/评论派生关键词（2–4 字 n-gram，过滤停用词与纯数字）。"""
    seeds = [meta.get("title") or "", meta.get("desc") or ""]
    corpus = " ".join(seeds) + " " + " ".join(clean(c.get("message", "")) for c in items)
    counter = Counter()
    for n in (2, 3, 4):
        for i in range(len(corpus) - n + 1):
            frag = corpus[i:i + n]
            if re.search(r"[\s\d\W]", frag) or re.fullmatch(r"[A-Za-z]+", frag):
                continue
            if frag in STOP:
                continue
            counter[frag] += 1
    # 过滤被更长片段完全覆盖的子串（避免「激光」「光刻」与「激光刻」重复）
    ranked = [w for w, c in counter.most_common(120) if c >= 2]
    keep = []
    for w in ranked:
        if any(w != k and w in k for k in keep):
            continue
        keep.append(w)
        if len(keep) >= top:
            break
    return keep


def main() -> int:
    ap = argparse.ArgumentParser(description="聚合 B 站素材为 report_data.json")
    ap.add_argument("--src", default="tmp_bili_extract", help="素材目录（含 metadata.json / comments_raw.json / danmaku2.xml）")
    ap.add_argument("--out", default=None, help="输出路径（默认 <src>/report_data.json）")
    ap.add_argument("--with-kw", action="store_true", help="额外派生 kw_freq（模板未渲染，默认不写）")
    a = ap.parse_args()

    src = Path(a.src)
    out = Path(a.out) if a.out else src / "report_data.json"
    warnings = []

    meta_p = src / "metadata.json"
    cm_p = src / "comments_raw.json"
    if not meta_p.exists():
        print(f"[err] 缺少 {meta_p}（先跑 extract_bilibili.py）", file=sys.stderr)
        return 2
    if not cm_p.exists():
        print(f"[err] 缺少 {cm_p}（extract_bilibili.py 需加 --comments）", file=sys.stderr)
        return 2

    raw = json.loads(meta_p.read_text(encoding="utf-8"))
    meta = raw.get("data", raw)
    cm = json.loads(cm_p.read_text(encoding="utf-8"))

    need = ["items", "fetched_at", "wbi_main_all_count", "total_fetched_comments"]
    missing = [k for k in need if k not in cm]
    if missing:
        print(f"[err] comments_raw.json 缺键: {missing}——请用 bili-note 的 "
              f"extract_bilibili.py 重新抓取（旧版脚本产物格式不兼容）", file=sys.stderr)
        return 2
    items = cm["items"]

    camp_counter = Counter(sentiment(clean(c["message"])) for c in items)
    camp_likes = Counter()
    for c in items:
        camp_likes[sentiment(clean(c["message"]))] += c.get("like") or 0

    top_comments = []
    for c in sorted(items, key=lambda x: -(x.get("like") or 0))[:20]:
        kids = sorted(c.get("children") or [], key=lambda k: -(k.get("like") or 0))
        top_comments.append({
            "user": c.get("uname") or "匿名",
            "like": c.get("like") or 0,
            "rcount": c.get("rcount") or 0,
            "time": (c.get("time") or "")[:10],
            "text": clean(c.get("message", ""))[:420],
            "top_reply": ({"user": kids[0].get("uname"), "like": kids[0].get("like") or 0,
                           "text": clean(kids[0].get("message", ""))[:200]}
                          if kids and (kids[0].get("like") or 0) >= 30 else None),
            "camp": sentiment(clean(c.get("message", ""))),
        })

    likes = [c.get("like") or 0 for c in items]
    like_buckets = {"0": 0, "1-4": 0, "5-19": 0, "20-99": 0, "100-499": 0, "500+": 0}
    for l in likes:
        if l == 0:
            like_buckets["0"] += 1
        elif l < 5:
            like_buckets["1-4"] += 1
        elif l < 20:
            like_buckets["5-19"] += 1
        elif l < 100:
            like_buckets["20-99"] += 1
        elif l < 500:
            like_buckets["100-499"] += 1
        else:
            like_buckets["500+"] += 1

    time_dist = Counter((c.get("time") or "")[:10] for c in items if c.get("time"))

    # ── 弹幕：缺失降级，不整链崩 ──
    dm_rows = []
    dm_p = src / "danmaku2.xml"
    if dm_p.exists():
        try:
            root = ET.parse(dm_p).getroot()
            for d in root.findall("d"):
                p = (d.get("p") or "").split(",")
                if len(p) >= 8 and (d.text or "").strip():
                    dm_rows.append((float(p[0]), d.text.strip()))
        except ET.ParseError as e:
            warnings.append(f"danmaku2.xml 解析失败（{e}），弹幕按 0 条处理")
    else:
        warnings.append("danmaku2.xml 未提供，弹幕按 0 条处理")
    dm_buckets = Counter(int(t // 300) for t, _ in dm_rows)
    dm_top = Counter(t for _, t in dm_rows).most_common(14)

    stat = meta.get("stat") or {}
    report = {
        "meta": {
            "title": meta.get("title", ""),
            "owner": meta.get("owner", {}),
            "published": dt.datetime.fromtimestamp(meta["pubdate"]).strftime("%Y-%m-%d %H:%M")
                         if meta.get("pubdate") else "",
            "duration": meta.get("duration", 0),
            "bvid": meta.get("bvid", ""),
            "url": f"https://www.bilibili.com/video/{meta.get('bvid','')}/",
            "stat": stat,
            "fetched_at": cm["fetched_at"],
            "comments_all": cm["wbi_main_all_count"],
            "comments_fetched": cm["total_fetched_comments"],
            "danmaku_fetched": len(dm_rows),
            "data_warnings": warnings,
        },
        "camp": {"counts": camp_counter.most_common(), "likes": camp_likes.most_common()},
        "top_comments": top_comments,
        "like_buckets": like_buckets,
        "time_dist": sorted(time_dist.items()),
        "danmaku_buckets": [[k * 5, v] for k, v in sorted(dm_buckets.items())],
        "danmaku_top": dm_top,
    }
    if a.with_kw:
        report["kw_freq"] = [{"word": w, "count": 0}
                             for w in derive_keywords(meta, items)]

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print("camp:", camp_counter.most_common())
    print("like_buckets:", like_buckets)
    print("danmaku:", len(dm_rows), "条", ("(降级)" if warnings else ""))
    for w in warnings:
        print("[warn]", w)
    print("time_dist:", report["time_dist"])
    print(f"ok -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
