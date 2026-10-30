"""音频包络提取：把视频的声音变成可绘制的数据结构。

2026-10-29 · 阅读版 v4「声纹」的底座。

为什么做这个：
  v3 的时间轨是一根抽象的直线 + 人工定标的刻度，与视频本身没有物理联系。
  v4 让轨道变成「这条视频真实的呼吸」——响的地方宽、静的地方细。
  声纹不是设计出来的，是测出来的，所以它无法被伪造。

输出契约（JSON）：
  {
    "duration": 549.0,
    "samples": 400,            # 采样点数
    "hop": 1.3725,             # 每个采样覆盖的秒数
    "rms": [0.0..1.0, ...],    # 归一化到 0-1 的音量包络
    "peaks": [3, 17, 42, ...],  # 显著峰值所在的采样索引（用于标注）
    "source": "filename.m4a"
  }

用法：
  python envelope.py --audio a.m4a --out env.json --samples 400
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def probe_duration(audio: Path) -> float:
    """读时长（秒）。ffprobe 不可用时返回 0。"""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(audio)],
            capture_output=True, text=True, timeout=60
        )
        return float((out.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def extract_rms(audio: Path):
    """用 ffmpeg astats 逐窗取 RMS 电平（dB）。返回 float 列表。"""
    cmd = [
        "ffmpeg", "-v", "error", "-i", str(audio),
        "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
        "-f", "null", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    vals = []
    pat = re.compile(r"RMS_level=(-?\d+(?:\.\d+)?)")
    for line in (res.stdout or "").splitlines():
        m = pat.search(line)
        if m:
            try:
                vals.append(float(m.group(1)))
            except ValueError:
                pass
    return vals


def downsample(vals, target: int):
    """把原始逐窗 RMS 压到 target 个点，取每段最大值（保留峰值，避免削平）。"""
    n = len(vals)
    if n == 0:
        return []
    if n <= target:
        return list(vals)
    out = []
    for i in range(target):
        a = int(i * n / target)
        b = max(a + 1, int((i + 1) * n / target))
        seg = vals[a:b]
        out.append(max(seg) if seg else -80.0)
    return out


def _pct(vals, p):
    """取分位数（0-100）。"""
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] + (s[hi] - s[lo]) * frac


def normalize(db_vals):
    """dB → 0..1，按【本片自己的动态范围】归一。

    2026-10-29 修的坑：初版用固定 floor=-60dB、top=max。
    实测梦核音频几乎全程人声（-20 ~ -18 dB），于是 (v+60)/40 全部落在 0.95 以上，
    400 个采样点全被判定为「响」，声纹被压成一条实心方块——等于没有声纹。
    改用 5%/95% 分位数：既能容忍个别爆音，又能让本片的真实起伏撑满 0-1。
    """
    if not db_vals:
        return []
    floor = _pct(db_vals, 5)
    top = _pct(db_vals, 95)
    # 动态范围太窄（如纯静音或恒定噪声）时退化为全 0，如实反映「无起伏」
    if top - floor < 1.5:
        return [0.0 for _ in db_vals]
    out = []
    for v in db_vals:
        x = (v - floor) / (top - floor)
        x = 0.0 if x < 0 else (1.0 if x > 1 else x)
        out.append(round(x, 4))
    return out


def find_peaks(norm, max_peaks=8):
    """找显著峰值索引（局部极大且高于均值），供模板做标注。"""
    n = len(norm)
    if n < 8:
        return []
    avg = sum(norm) / n
    cand = []
    for i in range(2, n - 2):
        if norm[i] >= avg * 1.15 and norm[i] >= norm[i-1] and norm[i] >= norm[i+1]:
            cand.append((norm[i], i))
    cand.sort(reverse=True)
    picked = []
    for v, i in cand:
        if all(abs(i - j) > n * 0.06 for j in picked):
            picked.append(i)
        if len(picked) >= max_peaks:
            break
    return sorted(picked)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=400, help="采样点数（默认 400）")
    a = ap.parse_args()

    if not a.audio.exists():
        print("[err] 音频不存在: %s" % a.audio, file=sys.stderr)
        return 2

    dur = probe_duration(a.audio)
    raw = extract_rms(a.audio)
    if not raw:
        print("[err] 未取到 RMS（ffmpeg 可能失败或缺音轨）", file=sys.stderr)
        return 3

    ds = downsample(raw, a.samples)
    norm = normalize(ds)
    peaks = find_peaks(norm)
    hop = (dur / len(norm)) if (dur and norm) else 0

    payload = {
        "duration": round(dur, 3),
        "samples": len(norm),
        "hop": round(hop, 4),
        "rms": norm,
        "peaks": peaks,
        "source": a.audio.name,
        "raw_windows": len(raw),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    loud = sum(1 for x in norm if x > 0.6)
    quiet = sum(1 for x in norm if x < 0.15)
    print("[env] %s | dur=%.1fs | raw=%d -> samples=%d | peaks=%d | loud=%d quiet=%d" % (
        a.out, dur, len(raw), len(norm), len(peaks), loud, quiet), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())