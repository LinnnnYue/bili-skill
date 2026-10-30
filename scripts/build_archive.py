"""bili 知识库版生成器：产出 archive.md —— 给 AI / 检索 / 二次加工用。

与 build_report.py 的分工（2026-10-29 主上裁定「双产物」）：
  build_report.py  -> read.html    给人读，<3000 字，逐句稿移出
  build_archive.py -> archive.md   给 AI 读，完整、结构化、可 grep

设计原则：
  1. 纯 Markdown，零装饰。样式负担交给 read.html。
  2. YAML frontmatter 存机器可读的元数据，正文存人类/模型可读的事实。
  3. 完整优先：逐句稿、全部评论、全部要点一条不删。
  4. 固定标题层级（## / ###），便于 RAG 切片与 grep 定位。
  5. 时间戳一律保留（[MM:SS]），让检索能落到具体秒。
"""
import argparse
import json
import re
import sys
from pathlib import Path


def parse_transcript(path: Path):
    """解析逐句稿，返回 [(mmss, text)]。支持 SRT / 方括号 / 纯文本。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = []

    def mmss(tc: str) -> str:
        tc = tc.split(",")[0].split(".")[0].strip()
        parts = [p for p in tc.split(":") if p]
        try:
            n = [int(p) for p in parts]
        except ValueError:
            return tc
        if len(n) >= 3:
            h, m, s = n[-3], n[-2], n[-1]
            return "%02d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)
        if len(n) == 2:
            return "%02d:%02d" % (n[0], n[1])
        return tc

    # SRT
    if path.suffix.lower() == ".srt" or "-->" in text:
        for blk in re.split(r"\r?\n\s*\r?\n", text.strip()):
            lines = [l for l in blk.splitlines() if l.strip()]
            ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
            if ti is None:
                continue
            start = lines[ti].split("-->")[0].strip()
            body = " ".join(lines[ti + 1:]).strip()
            if body:
                rows.append((mmss(start), body))
        if rows:
            return rows

    # [MM:SS]
    for line in text.splitlines():
        m = re.match(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)", line.strip())
        if m and m.group(2):
            rows.append((mmss(m.group(1)), m.group(2)))
    if rows:
        return rows

    # 纯文本兜底
    for line in text.splitlines():
        s = line.strip()
        if s and not re.match(r"^\d+$", s):
            rows.append(("", s))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True, help="report_data.json")
    ap.add_argument("--narrative", type=Path, required=True, help="narrative.json")
    ap.add_argument("--out", type=Path, required=True, help="输出 archive.md")
    ap.add_argument("--transcript", type=Path, help="逐句稿（SRT/TXT）")
    ap.add_argument("--transcript-label", dest="tlabel", default="ASR 语音转写")
    a = ap.parse_args()

    d = json.loads(a.data.read_text(encoding="utf-8"))
    n = json.loads(a.narrative.read_text(encoding="utf-8"))
    for k in ("call", "points", "evidence", "type",
              "env_fit", "note_sections", "backdrop", "takeaways", "quotes"):
        if k in n:
            d[k] = n[k]

    m = d.get("meta") or {}
    st = m.get("stat") or {}
    owner = (m.get("owner") or {}).get("name", "")
    rtype = d.get("type") or "tutorial"
    L = []

    # ── YAML frontmatter：让 RAG / 脚本能按字段解析 ──
    L.append("---")
    L.append("title: %s" % json.dumps(m.get("title", ""), ensure_ascii=False))
    L.append("bvid: %s" % (m.get("bvid") or ""))
    if m.get("url"):
        L.append("url: %s" % m["url"])
    L.append("up: %s" % json.dumps(owner, ensure_ascii=False))
    L.append("published: %s" % (m.get("published") or ""))
    L.append("duration_sec: %s" % (m.get("duration") or 0))
    L.append("type: %s" % rtype)
    L.append("view: %s" % (st.get("view") or 0))
    L.append("like: %s" % (st.get("like") or 0))
    L.append("favorite: %s" % (st.get("favorite") or 0))
    L.append("reply: %s" % (st.get("reply") or 0))
    L.append("danmaku: %s" % (st.get("danmaku") or 0))
    L.append("generator: bili/build_archive.py")
    L.append("---")
    L.append("")

    L.append("# %s" % (m.get("title") or "未命名视频"))
    L.append("")
    meta_bits = []
    if owner:
        meta_bits.append("UP 主 %s" % owner)
    if m.get("published"):
        meta_bits.append(m["published"])
    if m.get("duration"):
        meta_bits.append("%d 分 %d 秒" % (m["duration"] // 60, m["duration"] % 60))
    if m.get("bvid"):
        meta_bits.append("https://www.bilibili.com/video/%s/" % m["bvid"])
    if meta_bits:
        L.append("> " + " · ".join(meta_bits))
        L.append("")

    # ── 一句话结论 ──
    if d.get("call"):
        L.append("## 结论")
        L.append("")
        L.append(re.sub(r"</?b>|</?strong>", "**", d["call"]))
        L.append("")

    # ── 命题与背景 (essay) / 适配度 (tutorial) ──
    bd = d.get("backdrop") or {}
    fit = d.get("env_fit") or {}
    if rtype == "essay" and (bd.get("thesis") or bd.get("context")):
        L.append("## 命题与背景")
        L.append("")
        if bd.get("title"):
            L.append("### %s" % bd["title"])
            L.append("")
        if bd.get("thesis"):
            L.append(re.sub(r"</?b>|</?strong>", "**", bd["thesis"]))
            L.append("")
        if bd.get("stats"):
            L.append("关键数字：")
            L.append("")
            for s in bd["stats"]:
                L.append("- **%s** — %s" % (s[0], s[1]))
            L.append("")
        if bd.get("context"):
            L.append("背景要点：")
            L.append("")
            for c in bd["context"]:
                L.append("- %s" % c)
            L.append("")
    elif fit:
        L.append("## 适配度评估")
        L.append("")
        if fit.get("verdict"):
            L.append("**结论：%s**（等级 %s/2 · 匹配度 %s/5）" % (
                fit["verdict"], fit.get("level", 0), fit.get("score", 0)))
            L.append("")
        if fit.get("summary"):
            L.append(fit["summary"])
            L.append("")
        if fit.get("reasons"):
            L.append("为什么：")
            L.append("")
            for r in fit["reasons"]:
                L.append("- %s" % r)
            L.append("")
        if fit.get("requirements"):
            L.append("需要满足：")
            L.append("")
            for r in fit["requirements"]:
                L.append("- %s" % r)
            L.append("")
        if fit.get("unknown"):
            L.append("不确定项：%s" % fit["unknown"])
            L.append("")

    # ── 分层脉络（takeaways / note_sections）─��
    secs = d.get("takeaways") or d.get("note_sections") or []
    if secs:
        L.append("## %s" % ("论证脉络" if rtype == "essay" else "学习笔记"))
        L.append("")
        for s in secs:
            L.append("### %s" % (s.get("h") or "未命名"))
            L.append("")
            for it in (s.get("items") or []):
                txt = re.sub(r"</?b>|</?strong>", "**", it.get("text") or "")
                L.append("- **%s** — %s" % (it.get("title", ""), txt))
            if s.get("text"):
                L.append("")
                L.append(s["text"])
            L.append("")

    # ── 带时间戳要点 ──
    pts = d.get("points") or []
    if pts:
        L.append("## 时间线要点（%d 条）" % len(pts))
        L.append("")
        for p in pts:
            txt = re.sub(r"</?b>|</?strong>", "**", p.get("text") or "")
            L.append("- `%s` %s" % (p.get("t") or "", txt))
        L.append("")

    # ── 金句 ──
    qs = d.get("quotes") or []
    if qs:
        L.append("## 金句（%d 条）" % len(qs))
        L.append("")
        for q in qs:
            txt = re.sub(r"</?b>|</?strong>", "**", q.get("text") or "")
            L.append("> %s" % txt)
            L.append(">")
            L.append("> `%s` %s" % (q.get("t") or "", q.get("why") or ""))
            L.append("")

    # ── 评论区全集 ──
    cmts = d.get("top_comments") or []
    if cmts:
        L.append("## 评论（%d 条）" % len(cmts))
        L.append("")
        for c in cmts:
            who = c.get("user") or c.get("name") or ((c.get("member") or {}).get("uname")) or "匿名"
            txt = c.get("text") or c.get("content") or ((c.get("content") or {}).get("message") or "")
            if isinstance(txt, dict):
                txt = txt.get("message", "")
            like = c.get("like") or 0
            tm = c.get("time") or ""
            L.append("- **%s**%s%s：%s" % (
                who,
                (" · %s" % tm) if tm else "",
                (" · %s 赞" % like) if like else "",
                txt))
        L.append("")

    # ── 弹幕 ──
    dms = d.get("danmaku_top") or []
    if dms:
        L.append("## 弹幕（%d 条）" % len(dms))
        L.append("")
        vals = []
        for x in dms:
            if isinstance(x, str):
                vals.append(x)
            elif isinstance(x, dict):
                vals.append(x.get("text") or x.get("content") or "")
        vals = [v for v in vals if v]
        if vals:
            L.append("、".join(vals))
        L.append("")

    # ── 完整逐句稿（这是知识库版的核心价值）──
    if a.transcript and a.transcript.exists():
        rows = parse_transcript(a.transcript)
        if rows:
            L.append("## 逐句稿（%d 句 · %s）" % (len(rows), a.tlabel))
            L.append("")
            L.append("> 完整原文，带时间戳。这是知识库版相对阅读版的最大增量。")
            L.append("")
            for t_, txt in rows:
                L.append("- `%s` %s" % (t_ or "--:--", txt))
            L.append("")

    # ── 证据链 ──
    ev = d.get("evidence")
    if ev:
        L.append("## 证据链")
        L.append("")
        if isinstance(ev, dict):
            labels = {"meta": "元信息", "transcript": "文本", "comments": "评论",
                      "danmaku": "弹幕", "note": "备注"}
            for k, v in ev.items():
                if v:
                    L.append("- **%s**：%s" % (labels.get(k, k), v))
        elif isinstance(ev, list):
            for x in ev:
                if isinstance(x, dict):
                    L.append("- **%s**：%s" % (x.get("src", ""), x.get("note", "")))
        L.append("")

    L.append("---")
    L.append("")
    L.append("*由 bili 技能生成 · 知识库版 · 完整未删减。*")
    L.append("*配套阅读版见 `read.html`（<3000 字，给人在 3 分钟内看懂）。*")
    L.append("")

    out = "\n".join(L)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(out, encoding="utf-8")
    print("OK %s | %d 字 | 逐句 %d | 评论 %d | 金句 %d" % (
        a.out, len(out),
        len(parse_transcript(a.transcript)) if (a.transcript and a.transcript.exists()) else 0,
        len(cmts), len(qs)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())