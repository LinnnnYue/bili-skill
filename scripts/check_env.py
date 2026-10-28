#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bili 技能环境自检 —— 换机器 / 拿给朋友 / 上 GitHub 后先跑这个。

用法
----
    python scripts/check_env.py          # 体检
    python scripts/check_env.py --strict # 缺任一功能项也返回非零（默认只缺核心项才非零）

设计原则
--------
* **核心项**（缺了完全跑不了）→ 缺失即退出码 1
* **功能项**（缺了只是某个能力不可用）→ 提示 + 给安装命令，不判失败
* 每项都写清「缺了会怎样」，避免用户装了一堆不知道干嘛的包
"""
import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

# (分组, 显示名, 检测方式, 值, 是否核心, 用途, 安装命令)
# 检测方式：mod=import 名；cmd=可执行文件
CHECKS = [
    # ── 核心：没有就跑不起来 ──
    ("核心", "requests", "mod", "requests", True,
     "所有 B 站接口调用（元数据/评论/字幕）", "pip install requests"),
    ("核心", "ffmpeg", "cmd", "ffmpeg", True,
     "抽音频、抽帧、音量探测", "winget install Gyan.FFmpeg 或 https://ffmpeg.org"),
    ("核心", "ffprobe", "cmd", "ffprobe", True,
     "读视频时长（抽帧时间戳要用）", "随 ffmpeg 一同安装"),
    ("核心", "yt-dlp", "cmd", "yt-dlp", True,
     "下载音频/视频流", "pip install yt-dlp"),

    # ── 画面 OCR：无人声视频靠它 ──
    ("画面 OCR", "rapidocr_onnxruntime", "mod", "rapidocr_onnxruntime", False,
     "画面文字识别（宣传片/演示片/录屏）",
     "pip install rapidocr_onnxruntime"),
    ("画面 OCR", "Pillow", "mod", "PIL", False,
     "OCR 前的图像缩放（--scale）", "pip install Pillow"),

    # ── 语音转写：有语音的视频靠它 ──
    ("语音转写", "faster-whisper", "mod", "faster_whisper", False,
     "本地 ASR（无字幕轨时的主力）", "pip install faster-whisper"),
    ("语音转写", "zhconv", "mod", "zhconv", False,
     "繁简归一（ASR 质量门禁）", "pip install zhconv"),
    ("语音转写", "torch", "mod", "torch", False,
     "GPU 加速 ASR（没有则用 CPU，慢但能用）", "pip install torch"),

    # ── 备选引擎：仅在指定时用 ──
    ("备选", "openai-whisper", "mod", "whisper", False,
     "备选 ASR（run_qwen_asr / transcribe 的另一路径）", "pip install openai-whisper"),
    ("备选", "funasr", "mod", "funasr", False,
     "Qwen ASR 引擎（仅在用户指定 Qwen 时）", "pip install funasr"),
]


def check(it):
    group, name, kind, value, core, use, cmd = it
    if kind == "mod":
        try:
            m = importlib.import_module(value)
            ver = getattr(m, "__version__", "")
            return True, (str(ver)[:14] if ver else "已安装")
        except Exception:
            return False, ""
    else:
        p = shutil.which(value)
        if not p:
            return False, ""
        try:
            out = subprocess.run([value, "-version"] if value.startswith("ff") else [value, "--version"],
                                 capture_output=True, text=True, timeout=8,
                                 encoding="utf-8", errors="replace").stdout
            first = (out or "").splitlines()[0] if out else ""
            for tok in first.split():
                if tok[:1].isdigit():
                    return True, tok[:14]
            return True, "已安装"
        except Exception:
            return True, "已安装"


def find_whisper_model():
    """ASR 需要模型目录；环境变量优先，其次常见位置。"""
    import os
    # 优先环境变量；其次 faster-whisper / HuggingFace 的默认缓存位置
    cands = [
        os.environ.get("WHISPER_MODEL", ""),
        os.environ.get("BILI_WHISPER_MODEL_DIR", ""),
        os.path.expanduser("~/.cache/huggingface/hub"),
        str(HERE / "models"),
    ]
    for c in cands:
        if c and Path(c).is_dir():
            return c
    return ""


def main():
    ap = argparse.ArgumentParser(description="bili 技能环境自检")
    ap.add_argument("--strict", action="store_true", help="缺任一功能项也返回非零")
    a = ap.parse_args()

    print(f"bili skill 环境自检")
    print(f"  python  {sys.version.split()[0]}  ({sys.executable})")
    print(f"  skill   {SKILL}")
    print()

    missing_core, missing_opt = [], []
    group_now = None
    for it in CHECKS:
        group, name, _, _, core, use, cmd = it
        if group != group_now:
            print(f"[{group}]")
            group_now = group
        ok, info = check(it)
        mark = "OK  " if ok else ("缺失" if core else "未装")
        print(f"  {mark}  {name:<22} {info:<16} {use}")
        if not ok:
            (missing_core if core else missing_opt).append((name, cmd, use))

    # ASR 模型单独提示
    model = find_whisper_model()
    print(f"\n[可选资源]")
    import importlib as _il
    try:
        _il.import_module("faster_whisper")
        has_asr = True
    except Exception:
        has_asr = False
    if has_asr:
        if model:
            print(f"  OK    whisper 模型           {model}")
        else:
            print("  未找到 whisper 模型目录（ASR 会失败）")
            print("       设置环境变量 WHISPER_MODEL=<模型目录>，或用 faster-whisper 自动下载")

    # 汇总
    if missing_core:
        print("\n" + "=" * 64)
        print("缺少核心依赖，技能无法运行：")
        for name, cmd, use in missing_core:
            print(f"  · {name:<22} {use}\n    → {cmd}")
        print("=" * 64)
        return 1

    if missing_opt:
        print("\n可选依赖（缺了只是对应能力不可用）：")
        for name, cmd, use in missing_opt:
            print(f"  · {name:<22} {use}\n    → {cmd}")
        if a.strict:
            return 1

    print("\n核心依赖齐全。")
    if missing_opt:
        print("提示：装齐上面几项即可解锁「画面 OCR」与「语音转写」。")
    else:
        print("全部功能可用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
