"""构建 bili 正式成品（HTML 主 + 可选 MD 副）。

用法:
  python build_report.py --data tmp_bili_extract/report_data.json \
      --narrative narrative.json --template <bili_report_v4.html> --out report.html \
      [--transcript transcript.txt]
叙事（call/points/env_fit/note_sections/evidence）由 agent 依据正文与评论撰写。
"""
import argparse
import json
import re
import sys
from pathlib import Path


def parse_transcript(path: Path) -> list[dict]:
    """解析逐句稿，自动识别三种格式。

    1. [MM:SS] 文本                              —— 简化稿 / frame_ocr.py 输出
    2. SRT（序号 + HH:MM:SS,mmm --> ... + 文本）  —— transcribe.py 的 .srt
    3. 纯文本（一行一句，无时间戳）                —— transcribe.py 的 .txt

    纯文本无时间信息，t 留空但**句子必须保留** —— 否则 07 节会静默退回空态
    （2026-10-29 实测：传 .txt 导致 07 只剩 30 字空态文案）。
    """
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    rows: list[dict] = []

    def _mmss(tc: str) -> str:
        """时间码归一化：00:01:23,456 / 01:23,456 -> MM:SS（超 1 小时留 HH:MM:SS）。"""
        tc = tc.split(",")[0].split(".")[0].strip()
        parts = [p for p in tc.split(":") if p != ""]
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return tc
        if len(nums) >= 3:
            h, m, s = nums[-3], nums[-2], nums[-1]
            return "%02d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)
        if len(nums) == 2:
            return "%02d:%02d" % (nums[0], nums[1])
        return tc

    # --- 格式 2：SRT ---
    if suffix == ".srt" or "-->" in text:
        for blk in re.split(r"\n\s*\n", text.strip()):
            lines = [l for l in blk.splitlines() if l.strip()]
            ti = next((i for i, l in enumerate(lines) if "-->" in l), None)
            if ti is None:
                continue
            start_tc = lines[ti].split("-->")[0].strip()
            body = " ".join(lines[ti + 1:]).strip()
            if body:
                rows.append({"t": _mmss(start_tc), "text": body})
        if rows:
            return rows

    # --- 格式 1：方括号时间戳 ---
    for line in text.splitlines():
        m = re.match(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)", line.strip())
        if m and m.group(2):
            rows.append({"t": _mmss(m.group(1)), "text": m.group(2)})
    if rows:
        return rows

    # --- 格式 3：纯文本兜底（无时间戳）---
    for line in text.splitlines():
        s = line.strip()
        if s and not re.match(r"^\d+$", s):
            rows.append({"t": "", "text": s})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--narrative", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--transcript", type=Path)
    ap.add_argument("--transcript-label", dest="transcript_label", default=None,
                    help="07 节的来源标注，如「画面文字（OCR）」；默认 transcript")
    a = ap.parse_args()

    # ── 模板白名单（ROUND 02 · T2）：把 SKILL.md 的文字约束变成代码约束，
    # 杜绝「照文档抄命令却静默降级到旧模板」。新增模板须在此登记。
    ALLOWED = {"bili_report_v4.html"}   # v3 已于 2026-10-29 移除：缺深色默认 / 新配色 / 画面 OCR / 渲染自检
    if a.template.name not in ALLOWED:
        print(f"[err] 模板不在白名单: {a.template.name}", file=sys.stderr)
        print(f"      允许: {sorted(ALLOWED)}", file=sys.stderr)
        print(f"      旧模板（v2 / guide / clean）已作废：它们或硬编码他人报告，或数据链断裂必白屏。",
              file=sys.stderr)
        return 2

    d = json.loads(a.data.read_text(encoding="utf-8"))
    n = json.loads(a.narrative.read_text(encoding="utf-8"))
    for k in ("call", "points", "env_fit", "note_sections", "evidence"):
        if k in n:
            d[k] = n[k]
    if a.transcript and a.transcript.exists():
        d["transcript"] = parse_transcript(a.transcript)
        # 画面 OCR 稿不是语音转写，必须标注来源（默认 transcript）
        if a.transcript_label:
            d["transcript_label"] = a.transcript_label

    tpl = a.template.read_text(encoding="utf-8")
    title = (d.get("meta") or {}).get("title", "B站解析")
    payload = json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    # 只替换「赋值处」的 __DATA__，不一刀切全替换。
    # 原因：模板里还有 `typeof __DATA__ === 'undefined'` 这种「未注入数据」的探测，
    # 全量替换会把探测变成 `typeof {...}` —— 既是语法错误，又让数据被注入两次（产物翻倍）。
    TPL_FLAG = "const __TPL_MODE__ = (typeof __DATA__ === 'undefined');"
    if ": __DATA__;" in tpl:
        html = (tpl.replace("__TITLE__", title)
                   .replace(TPL_FLAG, "const __TPL_MODE__ = false;", 1)   # ← 关键：探测行必须同时改掉
                   .replace(": __DATA__;", ": " + payload + ";", 1))
        if ": __DATA__;" in html:
            print("[err] 模板里还有未替换的赋值占位符 : __DATA__;", file=sys.stderr)
            return 2
    else:
        html = tpl.replace("__TITLE__", title).replace("__DATA__", payload)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")
    print(f"OK {a.out} · {len(html.encode('utf-8'))} B · 要点 {len(d.get('points', []))} · "
          f"笔记节 {len(d.get('note_sections', []))} · 评论 {len(d.get('top_comments', []))} · "
          f"逐句 {len(d.get('transcript', []))}")
    # 契约校验：note_sections 必须是 {h, items:[{title,text}]}
    # 写成 {h, blocks:[...]} 时模板读不到 items → 四个笔记卡片只剩标题，静默空内容，最难发现。
    bad = [s for s in (d.get("note_sections") or [])
           if not (s.get("items") or s.get("text"))]
    if bad:
        print("[warn] note_sections 有 %d 节缺 items（模板将渲染为空卡片）。"
              "正确契约：{'h':'概念卡','items':[{'title':'…','text':'…'}]}" % len(bad),
              file=sys.stderr)
    if not d.get("env_fit"):
        print("[warn] env_fit 缺失——适配度评估是必填项。", file=sys.stderr)
    else:
        f = d["env_fit"]
        if not (f.get("summary") or f.get("why")):
            print("[warn] env_fit 缺 summary（为什么）——02 节会只剩结论词。"
                  "契约：summary/reasons[]/requirements[]/unknown", file=sys.stderr)
        if not (f.get("requirements") or f.get("needs")):
            print("[warn] env_fit 缺 requirements（需要满足）。", file=sys.stderr)
    ev = d.get("evidence")
    if ev is not None and not (isinstance(ev, dict) and ev) and not (isinstance(ev, list) and ev):
        print("[warn] evidence 为空——08 节会退回默认骨架、真实证据不显示。"
              "可用 dict{meta,transcript,comments,danmaku,note} 或 list[{src,note}]", file=sys.stderr)

    warns = ((d.get("meta") or {}).get("data_warnings") or [])
    for w in warns:
        print(f"[warn] {w}（报告已按 0 条如实记录）")
    return 0


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    main()
