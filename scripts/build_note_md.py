"""同源 Markdown 副产物：从 narrative + report_data 生成笔记，与 HTML 同源。

用法: python build_note_md.py --data <report_data.json> --narrative <narrative.json>
        [--transcript <transcript.txt>] --out <note.md>
"""
import argparse
import json
import re
from pathlib import Path


def nf(n):
    n = n or 0
    return f"{n/10000:.2f} 万" if n >= 10000 else str(n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--narrative", type=Path, required=True)
    ap.add_argument("--transcript", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()

    d = json.loads(a.data.read_text(encoding="utf-8"))
    n = json.loads(a.narrative.read_text(encoding="utf-8"))
    m = d.get("meta") or {}
    st = m.get("stat") or {}
    owner = (m.get("owner") or {}).get("name", "—")

    L = []
    L.append(f"# {m.get('title','（无标题）')}")
    L.append("")
    L.append(f"> UP：{owner} ｜ 时长 {(m.get('duration') or 0)//60} 分 "
             f"{(m.get('duration') or 0)%60} 秒 ｜ 发布 {m.get('published','—')} ｜ "
             f"播放 {nf(st.get('view'))} · 赞 {nf(st.get('like'))} · 收藏 {nf(st.get('favorite'))} · "
             f"币 {nf(st.get('coin'))}")
    L.append(f"> 原片：<https://www.bilibili.com/video/{m.get('bvid','')}/>")
    L.append("")

    if n.get("call"):
        L += ["## 一句话结论", "", f"> {n['call']}", ""]

    if n.get("points"):
        L += ["## 要点（带时间戳）", ""]
        L += [f"- `{p.get('t','')}` {p.get('text','')}" for p in n["points"]]
        L.append("")

    f = n.get("env_fit") or {}
    if f:
        lv = f.get("level", 0)
        label = f.get("verdict") or ("适合上手" if lv >= 2 else "有条件可用" if lv == 1 else "暂不建议")
        L += ["## 适配度评估", "", f"**{label}**"
              + (f"（匹配度 {f.get('score')}/5）" if f.get("score") else "")
              + (f" · 目标环境：{f.get('target')}" if f.get("target") else ""), ""]
        if f.get("summary"):
            L += [f["summary"], ""]
        if f.get("reasons"):
            L += ["**为什么**", ""] + [f"- {x}" for x in f["reasons"]] + [""]
        if f.get("requirements"):
            L += ["**需要满足**", ""] + [f"- {x}" for x in f["requirements"]] + [""]
        if f.get("unknown"):
            L += [f"**不确定项**：{f['unknown']}", ""]

    if n.get("note_sections"):
        L += ["## 学习笔记", ""]
        for s in n["note_sections"]:
            L += [f"### {s.get('h','')}", ""]
            for i in s.get("items", []):
                L.append(f"- **{i.get('title','')}**" + (f"：{i['text']}" if i.get("text") else ""))
            if s.get("text"):
                L.append(s["text"])
            L.append("")

    L += ["## 数据画像", "",
          f"| 播放 | 点赞 | 收藏 | 投币 | 评论 | 弹幕 |", "|---|---|---|---|---|---|",
          f"| {nf(st.get('view'))} | {nf(st.get('like'))} | {nf(st.get('favorite'))} | "
          f"{nf(st.get('coin'))} | {nf(st.get('reply'))} | {nf(st.get('danmaku'))} |", ""]

    cm = d.get("top_comments") or []
    if cm:
        L += ["## 评论精选（按赞排序）", ""]
        for c in cm[:10]:
            L.append(f"- **{c.get('user','匿名')}**（{c.get('like',0)} 赞"
                     + (f" · {c.get('rcount')} 回复" if c.get('rcount') else "") + "）："
                     + re.sub(r"\s+", " ", str(c.get("text", "")))[:180])
        L.append("")

    e = n.get("evidence") or {}
    if e:
        L += ["## 证据链与数据来源", ""]
        # 契约兼容：报告侧（HTML）写的是 [{src,note}] 列表，早期笔记侧写的是
        # {meta,transcript,comments,danmaku,note} 字典。两种都要吃得下，否则
        # 换一个视频就崩——这正是只在单个视频上回归测不出来的那类裂缝。
        if isinstance(e, list):
            for item in e:
                if isinstance(item, dict):
                    src = item.get("src") or item.get("label") or ""
                    note = item.get("note") or ""
                    L.append(f"- **{src}**" + (f" — {note}" if note else ""))
                else:
                    L.append(f"- {item}")
        else:
            for k, label in (("meta", "元信息"), ("transcript", "文本"), ("comments", "评论"),
                             ("danmaku", "弹幕"), ("note", "说明")):
                if e.get(k):
                    L.append(f"- **{label}**：{e[k]}")
        L.append("")

    if a.transcript and a.transcript.exists():
        rows = re.findall(r"\[(\d{2}:\d{2})\]\s*(.+)", a.transcript.read_text(encoding="utf-8"))
        L += ["## 逐句稿", "", "<details><summary>展开全文（%d 句）</summary>" % len(rows), ""]
        L += [f"- `{t}` {x}" for t, x in rows]
        L += ["", "</details>", ""]

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text("\n".join(L), encoding="utf-8")
    body = "\n".join(L)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", body))
    print(f"OK {a.out} · {len(body.encode('utf-8'))} B · 汉字 {cjk}")


if __name__ == "__main__":
    main()
