"""bili 速览层：把逐句稿压成「给模型读」的极简清单。

设计借鉴 dsh-video-storyboard（SAOS-3624）三条原则：
  1. 清单只给原材料，不下结论 —— 判断交给调用方
  2. 每加一行都要能说出它挡掉了什么误判，说不出来就不加
  3. 数字不可信时要说出来 —— 宁可自曝不确定，也不给会被误用的数字

与 build_report.py 的分工：
  - build_report.py → 给人读的 HTML 报告（长、有叙事、有美学）
  - brief.py        → 给模型读的速览清单（短、无结论、无修辞）

用法：
  python brief.py --data tmp_bili_extract/report_data.json \\
                  --transcript tmp_bili_extract/transcript/xxx.srt \\
                  --out brief.md
"""
import argparse
import json
import re
import sys
from pathlib import Path

# 每段台词预算（字）。按 skill 的 detail 档位对齐：low 60 / med 120 / high 400
BUDGETS = {"low": 60, "med": 120, "high": 400}


def parse_srt(path: Path):
    """解析 SRT，返回 [(start_sec, end_sec, text)]。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = []
    for blk in re.split(r"\r?\n\s*\r?\n", text.strip()):
        lines = [l for l in blk.splitlines() if l.strip()]
        ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if ti is None:
            continue
        a, _, b = lines[ti].partition("-->")
        body = " ".join(lines[ti + 1:]).strip()
        if not body:
            continue
        rows.append((_sec(a), _sec(b), body))
    return rows


def _sec(tc: str) -> float:
    tc = tc.strip().split(",")[0].split(".")[0]
    parts = [p for p in tc.split(":") if p]
    try:
        n = [int(p) for p in parts]
    except ValueError:
        return 0.0
    if len(n) >= 3:
        return n[-3] * 3600 + n[-2] * 60 + n[-1]
    if len(n) == 2:
        return n[0] * 60 + n[1]
    return float(n[0]) if n else 0.0


def parse_txt(path: Path):
    """纯文本逐句稿兜底：无时间戳，按行均摊到时长上（明确标注为估算）。"""
    lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    return [(i, i + 1, t) for i, t in enumerate(x for x in lines if x)]


def mmss(s: float) -> str:
    return "%02d:%02d" % (int(s) // 60, int(s) % 60)


def chunk(rows, target_segments: int):
    """把逐句稿切成 target_segments 段（等时长，不按字数）。

    旧实现把 edge 更新成 s + step，当某句跨度很大时会把边界推得永远追不上，
    结果 47 分钟只切出 1 段（2026-10-29 实测 bug）。
    正确做法：边界固定在 k*step，不随句移动。
    """
    if not rows:
        return []
    total = max(rows[-1][1], 0.1)
    step = max(total / max(target_segments, 1), 0.1)
    out = [[] for _ in range(target_segments)]
    for s, e, t in rows:
        idx = int(s / step)
        if idx >= target_segments:
            idx = target_segments - 1
        out[idx].append((s, e, t))
    return [seg for seg in out if seg]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, help="report_data.json（取 meta）")
    ap.add_argument("--transcript", type=Path, required=True, help="SRT / TXT 逐句稿")
    ap.add_argument("--segments", type=int, default=12, help="切几段（默认 12，对齐 storyboard 的 9-16）")
    ap.add_argument("--detail", choices=list(BUDGETS), default="med", help="每段台词预算")
    ap.add_argument("--out", type=Path, help="输出路径（默认 stdout）")
    args = ap.parse_args()

    if not args.transcript.exists():
        print("逐句稿不存在: %s" % args.transcript, file=sys.stderr)
        return 2

    meta = {}
    if args.data and args.data.exists():
        meta = json.loads(args.data.read_text(encoding="utf-8")).get("meta", {})

    suffix = args.transcript.suffix.lower()
    if suffix == ".srt" or "-->" in args.transcript.read_text(encoding="utf-8", errors="ignore"):
        rows = parse_srt(args.transcript)
        ts_source = "srt"
    else:
        rows = parse_txt(args.transcript)
        ts_source = "estimated"

    if not rows:
        print("逐句稿解析为空", file=sys.stderr)
        return 2

    budget = BUDGETS[args.detail]
    segs = chunk(rows, args.segments)
    dur = rows[-1][1] or 0

    L = []
    # 头部：只放机器可判的原始量，不放形容词
    L.append('<brief source="%s" duration="%.2f" segments="%d" ts="%s" detail="%s">'
             % (args.transcript.name, dur, len(segs), ts_source, args.detail))
    if meta:
        L.append("meta: %s | up=%s | %s | %.0fs" % (
            meta.get("bvid", "?"),
            (meta.get("owner") or {}).get("name", "?"),
            meta.get("published", "?"),
            meta.get("duration", 0)))
        st = meta.get("stat") or {}
        if st:
            L.append("stat: view=%s like=%s fav=%s reply=%s danmaku=%s"
                     % (st.get("view", 0), st.get("like", 0), st.get("favorite", 0),
                        st.get("reply", 0), st.get("danmaku", 0)))
    L.append("")

    # 自曝不确定（原则 3）
    if ts_source == "estimated":
        L.append("!! timestamps are ESTIMATED (plain-text transcript, no SRT) — do not cite as precise")
    tight = [i for i, s in enumerate(segs) if len(s) > 0 and (s[-1][1] - s[0][0]) < 3.0]
    if tight:
        L.append("!! segments %s span <3s — their text may be truncated by the cut, not by content"
                 % ", ".join(str(i + 1) for i in tight))
    L.append("")

    # 主体：每段只给 时间 + 台词（截断到预算），不加任何判断词
    for i, seg in enumerate(segs, 1):
        if not seg:
            continue
        s0, e0 = seg[0][0], seg[-1][1]
        body = " ".join(t for _, _, t in seg)
        cut = body[:budget]
        ell = "…" if len(body) > budget else ""
        L.append("seg %d = %s-%s (%ds)" % (i, mmss(s0), mmss(e0), int(e0 - s0)))
        L.append('    "%s%s"' % (cut, ell) if cut else '    ""')

    L.append("")
    L.append("<!-- 本清单只给原材料，不含结论；判断由调用方做。 -->")
    L.append("</brief>")

    out = "\n".join(L)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out, encoding="utf-8")
        print("OK %s | %d segs | source=%s | %d chars"
              % (args.out, len(segs), ts_source, len(out)), file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
