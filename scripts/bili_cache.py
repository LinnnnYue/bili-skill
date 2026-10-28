#!/usr/bin/env python3
"""B站 PC 客户端本地缓存直读（免下载快路）。

灵感来源：xiaohui5206/let-ai-read-video 的缓存模式。原缓存文件只读不动，
剥掉 m4s 头部 9 字节伪前缀生成修复副本到临时目录，再用 ffprobe 区分
纯音频流与无音频视频流。

缓存目录（自动探测）：C:\\Users\\<用户>\\Videos\\bilibili\\<目录>\\
目录内含 videoInfo.json（新版）或 entry.json（旧版）与 .m4s 文件。

用法：
  python bili_cache.py [--cache-root PATH] [--bvid BV...] [--cid CID] [--fix-out DIR]
输出：最后一行 RESULT_JSON:{...}，命中项含修复后的音/视频路径。
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

M4S_HEADER_BYTES = 9  # B站缓存 m4s 的头部伪前缀长度


def default_cache_root() -> Path | None:
    cand = Path.home() / "Videos" / "bilibili"
    return cand if cand.is_dir() else None


def _ffprobe(path: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name", "-of", "json", str(path)],
        capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


def fix_m4s(src: Path, out_dir: Path) -> Path:
    """剥 9 字节前缀生成修复副本（原文件只读不动）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (src.stem + "_fixed.m4s")
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fi.seek(M4S_HEADER_BYTES)
        shutil.copyfileobj(fi, fo)
    return dst


def classify(path: Path) -> str:
    """返回 'audio' | 'video' | 'unknown'。"""
    info = _ffprobe(path)
    codecs = [s.get("codec_type") for s in info.get("streams", [])]
    if "audio" in codecs and "video" not in codecs:
        return "audio"
    if "video" in codecs:
        return "video"
    return "unknown"


def scan_entries(cache_root: Path) -> list[dict]:
    """扫描缓存根下所有条目：目录含 videoInfo.json/entry.json + .m4s。"""
    entries = []
    for d in sorted(cache_root.iterdir()):
        if not d.is_dir():
            continue
        info = {}
        for name in ("videoInfo.json", "entry.json"):
            p = next(d.rglob(name), None)
            if p:
                try:
                    info = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
                break
        # 旧版 entry.json 的结构与新版不同，两种都兜住
        title = info.get("title") or (info.get("page_data", {}) or {}).get("part", "")
        bvid = info.get("bvid") or ""
        cid = info.get("cid") or ""
        m4s = list(d.rglob("*.m4s"))
        if m4s or info:
            entries.append({"dir": str(d), "bvid": bvid, "title": title,
                            "cid": cid, "m4s_count": len(m4s),
                            "m4s_files": [str(f) for f in m4s]})
    return entries


def probe_entry(entry: dict, fix_out: Path) -> dict:
    """把一个条目的 m4s 修复 + 分类。返回 {audio, video, unknown[]}。"""
    out = {"audio": None, "video": None, "unknown": []}
    for f in entry["m4s_files"]:
        src = Path(f)
        fixed = fix_m4s(src, fix_out)
        kind = classify(fixed)
        if kind in ("audio", "video"):
            out[kind] = str(fixed)
        else:
            out["unknown"].append(str(fixed))
    return out


def find_media_for(bvid: str = "", cid: str = "", cache_root: Path | None = None,
                   fix_out: Path | None = None) -> dict | None:
    """按 bvid/cid 找缓存条目并返回修复后的媒体路径；未命中返回 None。"""
    root = cache_root or default_cache_root()
    if not root:
        return None
    for e in scan_entries(root):
        if (bvid and e["bvid"] == bvid) or (cid and str(e["cid"]) == str(cid)):
            e = dict(e)
            e["media"] = probe_entry(e, fix_out or Path.home() / ".bili_cache_fix")
            return e
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="B站客户端缓存直读")
    ap.add_argument("--cache-root", type=Path)
    ap.add_argument("--bvid")
    ap.add_argument("--cid")
    ap.add_argument("--fix-out", type=Path, help="修复副本输出目录")
    ap.add_argument("--list", action="store_true", help="只列条目不修复")
    args = ap.parse_args()

    root = args.cache_root or default_cache_root()
    if not root or not root.is_dir():
        print("RESULT_JSON:" + json.dumps(
            {"cache_root": str(root), "entries": 0, "note": "未找到缓存目录"},
            ensure_ascii=False))
        return 0

    entries = scan_entries(root)
    if args.bvid or args.cid:
        hit = next((e for e in entries
                    if (args.bvid and e["bvid"] == args.bvid)
                    or (args.cid and str(e["cid"]) == str(args.cid))), None)
        if hit and not args.list:
            hit["media"] = probe_entry(hit, args.fix_out or Path.home() / ".bili_cache_fix")
        print("RESULT_JSON:" + json.dumps(
            {"cache_root": str(root), "entries": len(entries), "hit": hit},
            ensure_ascii=False))
    else:
        brief = [{k: e[k] for k in ("bvid", "title", "cid", "m4s_count")}
                 for e in entries]
        print("RESULT_JSON:" + json.dumps(
            {"cache_root": str(root), "entries": len(entries), "list": brief},
            ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
