#!/usr/bin/env python3
"""联络表（contact sheet）：把抽帧拼成带时间码烧录的网格图 + 位置映射 JSON。

灵感来源：CFITCorporation/video-watch-skill。依赖 ffmpeg（需含 tile/drawtext
滤镜的完整构建，gyan full build 即可），不需要 ImageMagick。

两种模式：
- 骨架模式（默认）：全片均匀 N 帧，输出「盲区上界 = 时长/N」指标。
- 指定时刻模式：--times-file 每行一个秒数（或 MM:SS），按给定时刻抽帧。

输出：
  <outdir>/sheet_01.png ...        联络表（每张 COLS 列）
  <outdir>/mapping.json            [{index, sheet, row, col, t, file}, ...]
  stdout 最后一行 RESULT_JSON:{...}

读图姿势（写给执行 agent）：读 sheet 图 + mapping.json，按 row/col 定位
格子的时间戳引用；格子里的帧号即 index。
"""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

COLS = 5
TILE_W = 320          # 单格宽（px），高按比例
SHEET_ROWS = 6        # 每张联络表行数 → 每张 30 帧
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\DejaVuSans.ttf",
]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def check_ffmpeg() -> str:
    """doctor 自检：ffmpeg 在场 + tile/drawtext 滤镜可用。缺失时给出离根因近的报错。"""
    r = _run(["ffmpeg", "-version"])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 不可用：未安装或不在 PATH")
    r = _run(["ffmpeg", "-hide_banner", "-filters"])
    need = [f for f in ("tile", "drawtext", "fps", "scale") if f" {f} " not in r.stdout]
    if need:
        raise RuntimeError(f"ffmpeg 构建缺滤镜 {need}——请换完整构建（如 gyan full），"
                           "否则报错会落在离根因很远的地方")
    return "ffmpeg OK（tile/drawtext/fps/scale 齐备）"


def _ffprobe_duration(video: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(video)])
    return float(r.stdout.strip())


def _find_font() -> str | None:
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60:02d}:{sec % 60:02d}"


def _parse_time(s: str) -> float:
    if ":" in s:
        parts = [float(x) for x in s.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))
    return float(s)


def _extract_and_tile(video: Path, times: list[float], outdir: Path,
                      tile_w: int) -> list[dict]:
    """逐帧抽取（保证精确时刻）→ 帧序号烧录 → tile 拼表。返回映射。"""
    font = _find_font()
    frames_dir = outdir / "_frames"
    frames_dir.mkdir(exist_ok=True)
    mapping = []
    for i, t in enumerate(times):
        # drawtext 烧帧号 + 时间码；text 里的冒号必须转义（: 是滤镜选项分隔符），
        # 否则 "01:17" 会被截成 "01"（首测踩坑实录）
        ts_label = _fmt_ts(t).replace(":", r"\:")
        vf = (f"scale={tile_w}:-2,"
              f"drawbox=y=ih-24:w=iw:h=24:color=black@0.6:t=fill,"
              f"drawtext=fontfile='{font}':text='#{i + 1} t={ts_label}':"
              f"fontcolor=white:fontsize=14:x=4:y=h-20")
        out = frames_dir / f"f_{i:04d}.png"
        r = _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video),
                  "-frames:v", "1", "-vf", vf, str(out)])
        if r.returncode != 0 or not out.exists():
            continue  # 片尾越界等单帧失败跳过，不断链
        mapping.append({"index": i + 1, "t": round(t, 2), "file": str(out)})

    # tile 拼表
    per_sheet = COLS * SHEET_ROWS
    sheets = []
    for si in range(0, len(mapping), per_sheet):
        chunk = mapping[si:si + per_sheet]
        sheet_path = outdir / f"sheet_{si // per_sheet + 1:02d}.png"
        rows = math.ceil(len(chunk) / COLS)
        tile = f"tile={COLS}x{rows}"
        r = _run(["ffmpeg", "-y", "-v", "error",
                  "-i", str(frames_dir / "f_%04d.png"), "-frames:v", "1",
                  "-vf", tile, str(sheet_path)])
        if r.returncode != 0:
            raise RuntimeError(f"tile 拼表失败：{r.stderr[:200]}")
        for j, m in enumerate(chunk):
            m["sheet"] = sheet_path.name
            m["row"] = j // COLS + 1
            m["col"] = j % COLS + 1
            del m["file"]  # 映射里不需要帧文件路径，省 token
        sheets.append(sheet_path)
    return mapping


def build(video: Path, outdir: Path, skeleton: int | None = None,
          times_file: Path | None = None, tile_w: int = TILE_W) -> dict:
    check_msg = check_ffmpeg()
    outdir.mkdir(parents=True, exist_ok=True)
    duration = _ffprobe_duration(video)

    if times_file:
        times = [_parse_time(l.strip()) for l in
                 times_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        mode = "times"
    else:
        n = skeleton or 30
        step = duration / n
        times = [step * (i + 0.5) for i in range(n)]  # 取区间中点，避开转场
        mode = "skeleton"

    mapping = _extract_and_tile(video, times, outdir, tile_w)
    blind_gap = round(duration / max(1, len(times)), 1) if mode == "skeleton" else None

    result = {
        "video": str(video),
        "duration_sec": round(duration, 1),
        "mode": mode,
        "frames": len(mapping),
        "cols": COLS,
        "sheets": sorted({m["sheet"] for m in mapping}),
        "blind_gap_sec": blind_gap,  # 骨架模式的盲区上界，可写入报告证据链
        "doctor": check_msg,
    }
    (outdir / "mapping.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[sheet] {result['frames']} 帧 → {len(result['sheets'])} 张联络表"
          + (f"（盲区上界 {blind_gap}s）" if blind_gap else ""))
    print("RESULT_JSON:" + json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="联络表生成：抽帧→烧时间码→拼表+映射")
    ap.add_argument("video", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--skeleton", type=int, default=30,
                    help="骨架模式：全片均匀帧数（默认 30）")
    ap.add_argument("--times-file", type=Path,
                    help="指定时刻模式：每行一个秒数或 MM:SS")
    ap.add_argument("--width", type=int, default=TILE_W, help="单格宽 px")
    args = ap.parse_args()
    build(args.video, args.out_dir, args.skeleton, args.times_file, args.width)
    return 0


if __name__ == "__main__":
    sys.exit(main())
