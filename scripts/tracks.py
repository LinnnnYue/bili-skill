"""双信号轨道：把「创作者的声音」与「观众的反应」压到同一根时间轴。

2026-10-29 · 阅读版 v5「混音台」的底座。

为什么做这个：
  bili 技能此前所有时间轴数据都来自创作者一侧（说得多久、在哪停）。
  但一支视频还有第二条完全独立的真实信号：观众的弹幕。
  两条信号叠在一起才能回答一个文字报告永远答不出的问题——
    「声音的高峰」与「情绪的高峰」是不是同一时刻？
  重合 = 讲到了；不重合 = 讲的没人在意、在意的地方他没讲。

输出契约（tracks.json）：
  {
    "duration": 548.8,
    "samples": 400,
    "hop": 1.372,
    "audio":   [0..1, ...],    # 音量包络（来自 envelope.py 同算法）
    "danmaku": [0..N, ...],    # 每格弹幕条数（未归一，保留真实计数）
    "danmakuNorm": [0..1, ...],# 归一化后的弹幕密度
    "resonance":  [{i,t,a,d}, ...],  # 两信号同时高的时刻
    "divergence": [{i,t,a,d,kind}, ...], # 一高一低的时刻
    "corr": 0.23,              # 皮尔逊相关系数
    "danmakuTotal": 186
  }
"""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path


def probe_duration(f: Path) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(f)],
                           capture_output=True, text=True, timeout=60)
        return float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0.0


def audio_rms(audio: Path):
    cmd = ["ffmpeg", "-v", "error", "-i", str(audio),
           "-af", "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-",
           "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    pat = re.compile(r"RMS_level=(-?\d+(?:\.\d+)?)")
    out = []
    for line in (r.stdout or "").splitlines():
        m = pat.search(line)
        if m:
            try:
                out.append(float(m.group(1)))
            except ValueError:
                pass
    return out


def parse_danmaku(xml_path: Path):
    """解析 B 站弹幕 XML，返回 [秒]。p 属性首个字段就是时间。"""
    txt = xml_path.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in re.finditer(r'<d p="([^"]+)"[^>]*>', txt):
        try:
            out.append(float(m.group(1).split(",")[0]))
        except (ValueError, IndexError):
            pass
    return out


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def normalize(vals):
    """分位数归一（5%/95%）。动态范围过窄时如实返回全 0。"""
    if not vals:
        return []
    lo, hi = _pct(vals, 5), _pct(vals, 95)
    if hi - lo < 1e-9:
        return [0.0 for _ in vals]
    return [round(min(1.0, max(0.0, (v - lo) / (hi - lo))), 4) for v in vals]


def downsample(vals, target, agg="max"):
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
        if not seg:
            out.append(0.0)
        elif agg == "sum":
            out.append(sum(seg))
        else:
            out.append(max(seg))
    return out


def bin_danmaku(times, duration, samples):
    """把弹幕按时间落到 samples 个格子里，返回每格条数。"""
    bins = [0] * samples
    if not duration or not samples:
        return bins
    for t in times:
        i = int(t / duration * samples)
        if 0 <= i < samples:
            bins[i] += 1
    return bins


def pearson(a, b):
    n = min(len(a), len(b))
    if n < 3:
        return 0.0
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((a[i] - ma) ** 2 for i in range(n)))
    db = math.sqrt(sum((b[i] - mb) ** 2 for i in range(n)))
    if da == 0 or db == 0:
        return 0.0
    return round(num / (da * db), 3)


def find_crossings(audio, dm, hop, q_hi=0.72, q_lo=0.28, limit=6):
    """找共振（两高）与背离（一高一低）的时刻。

    2026-10-29 修的坑：初版对 dm 直接用 72/28 分位数定阈。
    但弹幕是稀疏的——400 格只有 97 格有弹幕，dm 的 72 分位数正好是 0，
    于是「d >= dh」恒成立（d=0 也算高），共振列表里混进 danmaku=0 的假项，
    背离列表里也出现 danmaku=0 的「crowd-only」。
    修法：弹幕阈值只在【有弹幕的格子】上取分位，并且硬性要求 d > 0。
    """
    n = min(len(audio), len(dm))
    if n < 10:
        return [], []
    ah, al = _pct(audio[:n], q_hi * 100), _pct(audio[:n], q_lo * 100)
    dm_hot = [dm[i] for i in range(n) if dm[i] > 0]
    if dm_hot:
        dh = _pct(dm_hot, q_hi * 100)
        dl = _pct(dm_hot, q_lo * 100)
    else:
        dh, dl = 1.0, 0.0   # 无弹幕 → 永不共振
    res, div = [], []
    for i in range(n):
        t = round(i * hop, 1)
        a, d = audio[i], dm[i]
        if a >= ah and d > 0 and d >= dh:
            res.append({"i": i, "t": t, "a": round(a, 3), "d": round(d, 3),
                        "kind": "resonance"})
        elif a >= ah and d <= dl:
            div.append({"i": i, "t": t, "a": round(a, 3), "d": round(d, 3),
                        "kind": "talk-only"})
        elif d > 0 and d >= dh and a <= al:
            div.append({"i": i, "t": t, "a": round(a, 3), "d": round(d, 3),
                        "kind": "crowd-only"})
    # 相邻合并，避免连续几十格都算一次
    def dedupe(arr, gap=6):
        out = []
        last = -999
        for x in arr:
            if x["i"] - last > gap:
                out.append(x)
                last = x["i"]
        return out[:limit]
    return dedupe(res), dedupe(div)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--danmaku", type=Path, help="弹幕 XML（可缺；缺则只出单信号）")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--samples", type=int, default=400)
    a = ap.parse_args()

    dur = probe_duration(a.audio)
    raw = audio_rms(a.audio)
    if not raw:
        print("[err] 未取到音频 RMS", file=sys.stderr)
        return 3

    audio = normalize(downsample(raw, a.samples))
    n = len(audio)
    hop = (dur / n) if (dur and n) else 0

    dm_counts = [0] * n
    dm_total = 0
    if a.danmaku and a.danmaku.exists():
        times = parse_danmaku(a.danmaku)
        dm_total = len(times)
        dm_counts = bin_danmaku(times, dur, n)

    dm_norm = normalize(dm_counts) if dm_total else [0.0] * n
    corr = pearson(audio, dm_norm) if dm_total else 0.0
    res, div = find_crossings(audio, dm_norm, hop) if dm_total else ([], [])

    payload = {
        "duration": round(dur, 3),
        "samples": n,
        "hop": round(hop, 4),
        "audio": audio,
        "danmaku": dm_counts,
        "danmakuNorm": dm_norm,
        "danmakuTotal": dm_total,
        "corr": corr,
        "resonance": res,
        "divergence": div,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    hot = sum(1 for x in dm_counts if x > 0)
    print("[tracks] %s | dur=%.1fs | samples=%d | 弹幕=%d(落在%d格) | corr=%.3f | 共振=%d 背离=%d" % (
        a.out, dur, n, dm_total, hot, corr, len(res), len(div)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())