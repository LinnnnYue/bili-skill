#!/usr/bin/env python3
"""融合抽帧：场景切换点优先占位 + 均匀网格补位，产出时刻表。

灵感来源：xiaohui5206/let-ai-read-video 的 frames.py（auto 模式）。
解决两个失败模式：
- 纯场景检测在 PPT/讲课件类视频上「一帧都抓不到」（翻页是渐变淡入，
  scene 分永不触发）→ 无场景点时自动退化纯均匀网格；
- 纯定间隔在镜头切换频繁的视频上浪费帧预算 → 场景点优先，均匀补位。

输出时刻表文件（每行一个秒数），供 contact_sheet.py --times-file 消费：
  python frames_fuse.py <video> --n 30 --out times.txt
  python contact_sheet.py <video> --times-file times.txt --out-dir sheets/
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

SCENE_TH = 0.3      # 场景检测阈值
MIN_GAP = 2.0       # 任意两帧的最小间隔（秒）


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_duration(video: Path) -> float:
    r = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(video)])
    return float(r.stdout.strip())


def detect_scene_times(video: Path) -> list[float]:
    """场景检测：select='gt(scene,TH)' + showinfo → 解析 pts_time，去重升序。"""
    r = _run(["ffmpeg", "-hide_banner", "-i", str(video),
              "-vf", f"select='gt(scene,{SCENE_TH})',showinfo",
              "-f", "null", "-"])
    pts = sorted({round(float(m.group(1)), 2)
                  for m in re.finditer(r"pts_time:([\d.]+)", r.stderr)
                  if float(m.group(1)) > 0.1})
    return pts


def select_max_spacing(cands: list[float], occupied: list[float],
                       n: int) -> list[float]:
    """从候选中挑 n 个，使与已占位点的最小距离最大化（贪心）。"""
    sel: list[float] = []
    pool = sorted(set(cands))
    while pool and len(sel) < n:
        def mind(t: float) -> float:
            refs = occupied + sel
            return min((abs(t - o) for o in refs), default=1e9)
        best = max(pool, key=mind)
        if mind(best) < MIN_GAP:
            break
        sel.append(best)
        pool.remove(best)
        pool = [t for t in pool if abs(t - best) >= MIN_GAP]
    return sel


def plan_points(mode: str, scene_pts: list[float], duration: float,
                n: int) -> tuple[list[float], str]:
    """按模式产出抽帧时刻列表与实际模式说明。"""
    if mode == "scene":
        if not scene_pts:
            # 优雅退化：无场景切换 → 纯均匀（PPT 类视频的救命分支）
            step = duration / n
            return [round(step * (i + 0.5), 2) for i in range(n)], \
                "scene→uniform（未检测到场景切换，已退化均匀网格）"
        return scene_pts, "scene"

    # auto：场景点与均匀网格融合——场景点最多占一半名额，其余均匀补位
    scene_quota = min(len(scene_pts), max(1, n // 2))
    scene_sel = select_max_spacing(scene_pts, [], scene_quota)
    uniform_n = n - len(scene_sel)
    step = duration / max(1, uniform_n)
    grid = [step * (i + 0.5) for i in range(uniform_n)]
    # 均匀点避开已占场景点（MIN_GAP 内剔除）
    grid = [t for t in grid
            if all(abs(t - s) >= MIN_GAP for s in scene_sel)]
    points = sorted(scene_sel + grid)
    note = f"auto（场景点 {len(scene_sel)} + 均匀 {len(grid)}）"
    return points, note


def main() -> int:
    ap = argparse.ArgumentParser(description="融合抽帧时刻表生成")
    ap.add_argument("video", type=Path)
    ap.add_argument("--n", type=int, default=30, help="目标帧数")
    ap.add_argument("--mode", choices=["auto", "scene", "uniform"], default="auto")
    ap.add_argument("--out", type=Path, required=True, help="时刻表输出路径")
    args = ap.parse_args()

    duration = ffprobe_duration(args.video)
    scene_pts = []
    if args.mode in ("auto", "scene"):
        print(f"[fuse] 场景检测中（阈值 {SCENE_TH}）…")
        scene_pts = detect_scene_times(args.video)
        print(f"[fuse] 命中 {len(scene_pts)} 个切换点")
    points, note = plan_points(args.mode, scene_pts, duration, args.n)
    args.out.write_text("\n".join(f"{t:.2f}" for t in points) + "\n",
                        encoding="utf-8")
    print(f"[fuse] {len(points)} 帧（{note}）→ {args.out}")
    print("RESULT_JSON:" + __import__("json").dumps(
        {"mode": args.mode, "planned": note, "frames": len(points),
         "scene_hits": len(scene_pts), "out": str(args.out)},
        ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
