#!/usr/bin/env python3
"""ASR 后离线质量门禁（探针，不拦截流程，只报告信号）。

灵感来源：dsh-bili-humanism 的取稿后离线质检（QUALITY.md）。
纯本地、零网络、不调模型；同一写法稳定地错和稳定地对，在这里看起来一样——
它只报告统计信号，语义对错由上层（agent 或人）判断。

统计口径：
- 字/分钟：CJK 字符数 / 时长分钟。异常低 → 空音频/大段静音/ASR 幻觉漏转；
  异常高 → 时长与文本不匹配（拿错文件）。
- 繁体行占比：zhconv 转 zh-cn 后发生变化的行。异常高 → 字幕来源可疑
  （如空 Cookie 拿到繁体 AI 字幕）或 whisper 繁体输出未被简体化。
- 拉丁碎片率：紧贴中文的 ≤3 字符拉丁串占全部拉丁串比例。异常高 →
  ASR 按音节乱拼外文名（幻觉信号）。

用法：
  python asr_quality.py <transcript.txt> [--duration SEC | --info info.json]
输出：人类可读摘要 + 最后一行 RESULT_JSON:{...}
"""
import argparse
import json
import re
import sys
from pathlib import Path

try:
    from zhconv import convert as zhconv_convert
except ImportError:
    zhconv_convert = None

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]+")
# 紧贴中文的短拉丁串（前后任一侧贴着 CJK 即算），长度 ≤3 视为碎片
FRAG_RE = re.compile(r"[\u4e00-\u9fff][A-Za-z]{1,3}(?=[\u4e00-\u9fff])|"
                     r"[\u4e00-\u9fff][A-Za-z]{1,3}$|"
                     r"^[A-Za-z]{1,3}(?=[\u4e00-\u9fff])")


def probe(transcript_path: Path, duration_sec: float | None = None) -> dict:
    text = transcript_path.read_text(encoding="utf-8")
    lines = [l for l in text.splitlines() if l.strip()]

    # 空转写 ≠ 质量差：可能压根没跑 ASR（--no-asr）或字幕本就为空。
    # 误报过一次（--no-asr 时报「字/分钟=0 异常」），此处明确跳过。
    if not lines:
        return {
            "file": str(transcript_path),
            "lines": 0,
            "skipped": True,
            "reason": "无转写内容（未跑 ASR 或字幕为空），质量探针跳过",
            "ok": True,
            "warnings": [],
        }

    cjk_total = sum(len(CJK_RE.findall(l)) for l in lines)
    latin_all = LATIN_RE.findall(text)
    latin_frags = sum(len(FRAG_RE.findall(l)) for l in lines)

    trad_lines = 0
    if zhconv_convert and lines:
        for l in lines:
            if CJK_RE.search(l) and zhconv_convert(l, "zh-cn") != l:
                trad_lines += 1

    cpm = round(cjk_total / (duration_sec / 60), 1) if duration_sec else None
    trad_ratio = round(trad_lines / len(lines), 3) if lines else None
    frag_ratio = round(latin_frags / len(latin_all), 3) if latin_all else None

    warnings = []
    if cpm is not None and (cpm < 50 or cpm > 400):
        warnings.append(f"字/分钟={cpm} 超出常理区间 [50, 400]——"
                        "疑似空音频/大段静音/ASR 漏转，或文本与视频不匹配")
    if trad_ratio is not None and trad_ratio > 0.3:
        warnings.append(f"繁体行占比={trad_ratio:.0%} 异常——检查字幕来源"
                        "（空 Cookie 常拿到繁体 AI 字幕）或 whisper 输出未简体化")
    if frag_ratio is not None and frag_ratio > 0.5 and len(latin_all) >= 10:
        warnings.append(f"拉丁碎片率={frag_ratio:.0%} 异常——ASR 可能在按音节"
                        "乱拼外文名（幻觉信号），对照官方文档校准术语")

    return {
        "file": str(transcript_path),
        "lines": len(lines),
        "cjk_chars": cjk_total,
        "duration_sec": duration_sec,
        "chars_per_min": cpm,
        "traditional_line_ratio": trad_ratio,
        "latin_frag_ratio": frag_ratio,
        "latin_total": len(latin_all),
        "ok": not warnings,
        "warnings": warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="ASR 离线质量探针")
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--duration", type=float, help="视频时长（秒）")
    ap.add_argument("--info", type=Path, help="info.json（自动读 duration）")
    args = ap.parse_args()

    duration = args.duration
    if duration is None and args.info and args.info.exists():
        try:
            duration = json.loads(args.info.read_text(encoding="utf-8")).get("duration")
        except Exception:
            pass

    r = probe(args.transcript, duration)
    print(f"[probe] {r['lines']} 行 / {r['cjk_chars']} 汉字"
          f" / 字·分钟 {r['chars_per_min']}"
          f" / 繁体行 {r['traditional_line_ratio']}"
          f" / 拉丁碎片率 {r['latin_frag_ratio']}")
    for w in r["warnings"]:
        print(f"[probe] ⚠ {w}")
    print("RESULT_JSON:" + json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
