#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""画面文字提取（抽帧 + OCR）——无人声视频的兜底信息源。

为什么需要它
------------
ASR 只吃语音。但产品宣传 / 软件演示 / 录屏教程这类视频常常**没有旁白**，
信息全在画面上：标题卡、功能列表、UI 文字、命令行输出。
此前这类视频转写为 0 句，报告就只能靠评论和简介撑着——等于主动放弃一半信息。

用法
----
    # 1) 先下视频流（720p 足够 OCR，再高没必要）
    yt-dlp -f "bestvideo[height<=720]" --add-header "Referer: https://www.bilibili.com/" \
           -o "bili_video/%(id)s.%(ext)s" "https://www.bilibili.com/video/<BV>"

    # 2) 抽帧 + OCR
    python frame_ocr.py bili_video/BV19Rn26CExe.mp4 --out tmp_bili_extract/frames_ocr.json

    # 可选参数
    --scene 0.30     场景变化阈值（越小抽帧越多）
    --fps   0.5      场景抽帧不足时的兜底抽帧率（帧/秒）
    --min-frames 5   场景抽帧少于此数则回退定时抽帧
    --lang  ch       RapidOCR 语言（ch / en）
    --dedup 0.72     相邻帧文本 Jaccard 相似度高于此值视为重复

产出
----
    {out}.json  → [{"t":"00:12","sec":12.4,"text":"…","conf":0.93}]
    {out}.txt   → 人类可读的「[mm:ss] 文字」列表
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("[err] 缺少 rapidocr_onnxruntime。"
          "安装：pip install rapidocr_onnxruntime", file=sys.stderr)
    sys.exit(2)


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def extract_frames(video: Path, workdir: Path, scene: float, fps: float,
                   min_frames: int, mode: str, scale: int):
    """抽帧。默认用定时抽帧（fps），可选场景变化（scene）。

    为什么默认不是场景检测：实测同一支 60 秒宣传片，
    场景阈值 0.30 只抽出 7 帧、漏掉大半画面文字；
    fps=0.5 抽出 30 帧，多拿到「好素材，直接开拍」「换个角度，都是好设计」
    「150 SHOTS / 124 RECIPES」「网页/PPT/幻灯片/海报/宣传片」等关键文案。
    宣传片画面切换慢、单帧停留久，场景检测反而抽得太稀。
    """
    pat = str(workdir / "f_%05d.jpg")

    def run(vf: str) -> int:
        cmd = ["ffmpeg", "-y", "-i", str(video), "-vf", vf,
               "-vsync", "vfr", "-q:v", "2", "-loglevel", "error", pat]
        subprocess.run(cmd, capture_output=True)
        return len(list(workdir.glob("f_*.jpg")))

    if mode == "scene":
        n = run(f"select='gt(scene,{scene})'")
        if n < min_frames:
            for f in workdir.glob("f_*.jpg"):
                f.unlink()
            n = run(f"fps={fps}")
    else:
        # scale>1 时在抽帧同时放大（放大后 OCR 对小字略有改善，实测有限）
        vf = f"fps={fps}" + (f",scale=iw*{scale}:ih*{scale}" if scale > 1 else "")
        n = run(vf)
    return n


def probe_duration(video: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
        return float(out.strip())
    except Exception:
        return 0.0


def jaccard(a: str, b: str) -> float:
    """字符级 Jaccard（中文无空格，用 2-gram 更合理）"""
    def grams(s, n=2):
        s = re.sub(r"\s+", "", s)
        return {s[i:i + n] for i in range(max(0, len(s) - n + 1))} or {s}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def main():
    ap = argparse.ArgumentParser(description="视频画面文字提取（抽帧 + OCR）")
    ap.add_argument("video", help="视频文件路径（mp4/flv/webm…）")
    ap.add_argument("--out", required=True, help="输出 JSON 路径（同时产出同名 .txt）")
    ap.add_argument("--scene", type=float, default=0.30, help="场景变化阈值，默认 0.30")
    ap.add_argument("--fps", type=float, default=0.5, help="兜底抽帧率（帧/秒），默认 0.5")
    ap.add_argument("--min-frames", type=int, default=5, help="scene 模式抽帧下限，默认 5")
    ap.add_argument("--mode", choices=("fps", "scene"), default="fps",
                    help="抽帧方式：fps=定时（默认，更全）/ scene=场景变化（更省）")
    ap.add_argument("--scale", type=int, default=1, help="抽帧放大倍数，默认 1（2 对小字略有改善）")
    ap.add_argument("--dedup", type=float, default=0.72, help="相邻帧去重相似度，默认 0.72")
    ap.add_argument("--lang", default="ch", help="OCR 语言，默认 ch")
    ap.add_argument("--max-frames", type=int, default=400, help="最多处理帧数，默认 400")
    a = ap.parse_args()

    video = Path(a.video)
    if not video.exists():
        print(f"[err] 视频不存在: {video}", file=sys.stderr)
        return 2
    if not has_ffmpeg():
        print("[err] 未找到 ffmpeg", file=sys.stderr)
        return 2

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="bili_ocr_"))
    try:
        dur = probe_duration(video)
        n = extract_frames(video, workdir, a.scene, a.fps, a.min_frames, a.mode, a.scale)
        print(f"抽帧 {n} 张（模式 {a.mode}"
              + (f"·fps {a.fps}" if a.mode == "fps" else f"·场景阈值 {a.scene}")
              + f"·放大 {a.scale}x，时长 {dur:.0f} 秒）")

        frames = sorted(workdir.glob("f_*.jpg"))
        if not frames:
            print("[warn] 未抽到任何帧", file=sys.stderr)
            out.write_text("[]", encoding="utf-8")
            return 0
        if len(frames) > a.max_frames:
            step = len(frames) / a.max_frames
            frames = [frames[int(i * step)] for i in range(a.max_frames)]
            print(f"抽帧过多，等距抽样到 {len(frames)} 张")

        engine = RapidOCR()
        rows, prev = [], ""
        for i, f in enumerate(frames):
            sec = (dur / max(1, len(frames))) * i if dur else i * 2.0
            try:
                res, _ = engine(str(f))
            except Exception as e:
                print(f"  [{i}] OCR 失败: {type(e).__name__}", file=sys.stderr)
                continue
            if not res:
                continue
            texts = [r[1] for r in res if r[1] and len(r[1].strip()) > 1]
            confs = [float(r[2]) for r in res if r[1] and len(r[1].strip()) > 1]
            if not texts:
                continue
            text = " / ".join(t.strip() for t in texts)
            conf = round(sum(confs) / len(confs), 3)
            # 相邻帧去重：宣传片常有多帧同一张标题卡
            if prev and jaccard(prev, text) >= a.dedup:
                continue
            prev = text
            rows.append({"t": mmss(sec), "sec": round(sec, 1),
                         "text": text, "conf": conf})
            print(f"  [{mmss(sec)}] {text[:70]}")

        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        txt = out.with_suffix(".txt")
        txt.write_text("\n".join(f"[{r['t']}] {r['text']}" for r in rows), encoding="utf-8")
        print(f"\nOK → {out} · {txt.name} · {len(rows)} 条画面文字（去重后）")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
