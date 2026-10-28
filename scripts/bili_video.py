#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站视频内容提取术式：元数据 + AI/普通字幕 + 结构化 Markdown 总结。

用法示例：
    python scripts/bili_video.py BV1znMH6mEM1 --out ./result
    python scripts/bili_video.py https://www.bilibili.com/video/BV1znMH6mEM1/ --out ./result
    python scripts/bili_video.py BV15VGb6gERU --out ./result --asr        # 无字幕视频走语音识别

前置：浏览器已带 --remote-debugging-port=9222 --remote-allow-origins=* 启动，
      且已登录的 B 站标签页处于打开状态（脚本会自动提取 Cookie）。

ASR 分支（可选，用于无字幕视频）：
    - 依赖 ffmpeg（系统 PATH 内）与 faster-whisper（pip install faster-whisper）
    - 通过 WBI 签名的 playurl 拿到 DASH 音频流，ffmpeg 下载转 16k 单声道 wav
    - faster-whisper 本地转写（默认 small 模型，支持本地目录 / HF 镜像自动下载）
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, quote

import requests

from extract_cookies import extract_cookies, parse_cookie_header

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"

# WBI mixin key 重排表（B站固定算法）
MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
             27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
             37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22,
             25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44]


def get_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_TAB[:32])


def wbi_sign(params: dict, mixin_key: str) -> dict:
    params["wts"] = int(time.time() * 1000)
    params = dict(sorted(params.items()))
    query = urlencode(params, quote_via=quote)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


def sec_to_ts(s):
    try:
        s = int(float(s))
    except Exception:
        return "00:00"
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_bvid(text: str) -> str:
    m = re.search(r"BV[0-9A-Za-z]+", text)
    if m:
        return m.group(0)
    raise ValueError(f"无法从输入解析 BV 号：{text}")


def make_session(cookie_file: Path = None, cookie_text: str = None):
    """构造带 Cookie 与统一 UA 的 requests Session。"""
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json, text/plain, */*",
    })

    if cookie_text:
        sess.cookies.update(parse_cookie_header(cookie_text))
    elif cookie_file and cookie_file.exists():
        text = cookie_file.read_text(encoding="utf-8").strip()
        sess.cookies.update(parse_cookie_header(text))
    return sess


def fetch_video_info(sess, bvid: str):
    r = sess.get("https://api.bilibili.com/x/web-interface/view",
                 params={"bvid": bvid}, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"view API 返回错误：{data}")
    return data["data"]


def fetch_wbi_keys(sess):
    nav = sess.get("https://api.bilibili.com/x/web-interface/nav", timeout=15).json()
    wbi = nav.get("data", {}).get("wbi_img", {})
    img_key = wbi.get("img_url", "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi.get("sub_url", "").rsplit("/", 1)[-1].split(".")[0]
    return get_mixin_key(img_key, sub_key)


def fetch_player_v2(sess, bvid: str, cid: int, mixin_key: str):
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": 64,
        "fnval": 4048,
        "fourk": 1,
        "web_location": f"https://www.bilibili.com/video/{bvid}",
    }
    signed = wbi_sign(params, mixin_key)
    r = sess.get("https://api.bilibili.com/x/player/wbi/v2", params=signed, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"player/v2 API 返回错误：{data}")
    return data.get("data", {})


def fetch_playurl(sess, bvid: str, cid: int, mixin_key: str) -> str:
    """WBI 签名调用 playurl，返回带宽最高的 DASH 音频流 baseUrl。"""
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": 64,
        "fnval": 4048,
        "fourk": 1,
        "web_location": f"https://www.bilibili.com/video/{bvid}",
    }
    signed = wbi_sign(params, mixin_key)
    r = sess.get("https://api.bilibili.com/x/player/wbi/playurl", params=signed, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"playurl API 返回错误：{data}")
    dash = data.get("data", {}).get("dash", {})
    audios = dash.get("audio", [])
    if not audios:
        raise RuntimeError("playurl 未返回音频流（可能未登录 / 地区限制 / 仅 FLV 源）")
    audios.sort(key=lambda a: a.get("bandwidth", 0), reverse=True)
    return audios[0]["baseUrl"]


def download_subtitle(sess, player_data: dict):
    """优先下载 AI 字幕；无则取第一条普通字幕。返回 (lines, source_name, subtitle_url)。"""
    ai = player_data.get("ai_subtitle") or {}
    ai_url = ai.get("subtitle_url")
    subs = player_data.get("subtitle", {}).get("subtitles", [])

    url = None
    source_name = "未知"
    if ai_url:
        url = ai_url
        source_name = "AI 字幕"
    elif subs:
        s0 = subs[0]
        url = s0.get("subtitle_url")
        source_name = s0.get("lan_doc", "普通字幕")

    if not url:
        return [], "无字幕", ""

    if url.startswith("//"):
        url = "https:" + url

    sj = sess.get(url, timeout=15).json()
    body = sj.get("body", [])
    lines = [f"[{sec_to_ts(b.get('from', 0))}] {b.get('content', '').strip()}" for b in body]
    return lines, source_name, url


def download_audio(audio_url: str, out_wav: Path, cookie_text: str, verbose: bool = False) -> Path:
    """用 ffmpeg 直连下载 B 站音频流，并转成 16k 单声道 wav（whisper 友好格式）。"""
    headers = "Referer: https://www.bilibili.com/\r\n"
    if cookie_text:
        headers += f"Cookie: {cookie_text}\r\n"
    headers += f"User-Agent: {UA}\r\n"

    m4a = out_wav.with_suffix(".m4a")
    # 先尝试原样拷贝 m4a（最快）
    r1 = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-rw_timeout", "120000000",
         "-headers", headers, "-i", audio_url, "-c", "copy", str(m4a)],
        capture_output=True, text=True,
    )
    if not (m4a.exists() and m4a.stat().st_size > 100000):
        if verbose:
            print(r1.stderr[:1200])
        # 拷贝失败则直接解封装转 wav
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-rw_timeout", "120000000",
             "-headers", headers, "-i", audio_url,
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            capture_output=True, text=True,
        )
    else:
        # m4a 成功，转 wav
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(m4a),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            capture_output=True, text=True,
        )
    if not (out_wav.exists() and out_wav.stat().st_size > 10000):
        raise RuntimeError("ffmpeg 未能生成可用音轨（检查 ffmpeg 是否在 PATH、网络是否可达）")
    return out_wav


def asr_transcribe(wav_path: Path, model_arg: str, verbose: bool = False):
    """faster-whisper 本地中文转写。返回带时间戳的逐句列表。

    model_arg 可为：模型名（small/base/tiny）或本地模型目录路径。
    优先级：--asr-model 目录 > 环境变量 BILI_WHISPER_MODEL_DIR > --asr-model 名称 > 默认 "small"。
    """
    # 修复 Windows 上 ctranslate2 构造 WhisperModel 时的段错误：若系统 PATH 存在
    # 其他版本的 libiomp5md.dll（Intel OpenMP 运行时），会与 ctranslate2 自带版本
    # 发生 ABI 冲突。将 ctranslate2 自带 DLL 目录注册为进程级 DLL 搜索路径
    # （优先级高于 PATH），强制优先加载自带版本。
    try:
        import importlib.util as _ilu
        _spec = _ilu.find_spec("ctranslate2")
        if _spec and getattr(_spec, "submodule_search_locations", None):
            _cdir = _spec.submodule_search_locations[0]
            if _cdir and os.path.exists(os.path.join(_cdir, "libiomp5md.dll")):
                try:
                    os.add_dll_directory(_cdir)
                except Exception:
                    _p = os.environ.get("PATH", "")
                    if _cdir not in _p.split(os.pathsep):
                        os.environ["PATH"] = _cdir + os.pathsep + _p
    except Exception:
        pass

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("未安装 faster-whisper。请执行：pip install faster-whisper")

    local_dir = None
    env_dir = os.environ.get("BILI_WHISPER_MODEL_DIR")
    if env_dir and Path(env_dir).is_dir():
        local_dir = Path(env_dir)
    if model_arg:
        p = Path(model_arg)
        if p.exists() and p.is_dir():
            local_dir = p
    model_id = str(local_dir) if local_dir else (model_arg or "small")
    if verbose:
        print(f"[asr] 加载模型：{model_id}")

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    # 设备选择：BILI_WHISPER_DEVICE=cpu|cuda 可强制；默认 auto——探测到 CUDA 就用
    # GPU（float16），初始化失败（缺 cuDNN/cuBLAS、显存不足等）自动回退 CPU int8。
    # GPU 依赖 nvidia-cublas-cu12 / nvidia-cudnn-cu12 两个 pip 包的 DLL；ctranslate2
    # 的依赖链解析不认 add_dll_directory，必须把 bin 目录前置到 PATH（实测验证）。
    model = None
    used_gpu = False
    forced = os.environ.get("BILI_WHISPER_DEVICE", "").strip().lower()
    if forced != "cpu":
        try:
            import ctranslate2 as _ct2
            if _ct2.get_cuda_device_count() > 0:
                _sp = os.path.dirname(
                    os.path.dirname(os.path.abspath(_ct2.__file__)))
                for _sub in (os.path.join("nvidia", "cublas", "bin"),
                             os.path.join("nvidia", "cudnn", "bin")):
                    _p = os.path.join(_sp, _sub)
                    if os.path.isdir(_p):
                        os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
                model = WhisperModel(model_id, device="cuda", compute_type="float16")
                used_gpu = True
                if verbose:
                    print("[asr] 设备：GPU (cuda/float16)")
        except Exception as e:
            if verbose:
                print(f"[asr] GPU 初始化失败（{type(e).__name__}），回退 CPU")
            model = None
    if model is None:
        model = WhisperModel(model_id, device="cpu", compute_type="int8")
        if verbose:
            print("[asr] 设备：CPU (int8)")

    segs, info = model.transcribe(
        str(wav_path), language="zh", beam_size=5, vad_filter=True)
    if verbose:
        print(f"[asr] 检测语言 {info.language} 概率 {info.language_probability:.2f}")

    lines = []
    try:
        for s in segs:
            t0 = f"{int(s.start) // 60:02d}:{int(s.start) % 60:02d}"
            lines.append(f"[{t0}] {s.text.strip()}")
    except Exception as e:
        # CUDA 错误可能延迟到消费生成器时才爆发（cuDNN 惰性加载）；此时整体回退 CPU 重跑
        if not used_gpu or forced == "cuda":
            raise
        if verbose:
            print(f"[asr] GPU 转写中途失败（{type(e).__name__}），回退 CPU 重跑")
        model = WhisperModel(model_id, device="cpu", compute_type="int8")
        segs, info = model.transcribe(
            str(wav_path), language="zh", beam_size=5, vad_filter=True)
        lines = []
        for s in segs:
            t0 = f"{int(s.start) // 60:02d}:{int(s.start) % 60:02d}"
            lines.append(f"[{t0}] {s.text.strip()}")
    return lines


def build_summary(info: dict, bvid: str, video_url: str, source_name: str, line_count: int) -> str:
    owner = info.get("owner", {})
    title = info.get("title", "")
    desc = info.get("desc", "") or ""
    duration = info.get("duration", 0)

    duration_text = f"{duration // 60} 分 {duration % 60} 秒" if duration else "未知"
    is_asr = "ASR" in source_name or "语音" in source_name
    source_note = "语音识别（ASR）逐句稿" if is_asr else "字幕逐句稿"

    md = f"""# {title}

**视频链接：** {video_url}  
**UP 主：** {owner.get('name', '未知')}（UID {owner.get('mid', '未知')}）  
**时长：** {duration_text}  
**发布时间：** {time.strftime('%Y-%m-%d %H:%M', time.localtime(info.get('pubdate', 0)))}  
**文本来源：** {source_name}（共 {line_count} 句）

## 视频简介

{desc or '（UP 主未填写简介）'}

## 内容总结

> 本总结由{source_note}自动结构化生成。若需要更深入的分段摘要，可把 `transcript.txt` 喂给任意大模型做二次提炼。

### 核心要点

- 视频主题：{title}
- 主讲/UP 主：{owner.get('name', '未知')}
- 目标受众与前置：见视频简介或开篇 1-2 分钟说明
- 关键工具/插件/资源：在逐句稿中搜索「下载」「安装」「插件」「软件」等关键词可快速定位

### 章节速览

建议结合 `transcript.txt` 中的时间戳，按以下方式快速定位：

| 内容方向 | 搜索关键词 |
|----------|------------|
| 准备工作 | 安装、下载、环境、版本 |
| 核心操作 | 导入、转换、设置、参数 |
| 常见问题 | 报错、失败、注意、警告 |
| 结尾资源 | 链接、地址、仓库、推荐 |

## 原始逐句文稿

逐句带时间戳文稿保存在同目录 `transcript.txt`。{'（ASR 另附无时间戳纯文本 `transcript_full.txt`）' if is_asr else ''}  
如需生成更细的段落总结，可在任意 LLM 中提示：「请根据以下带时间戳逐句稿，按主题分节总结。」

---
*提取时间：{time.strftime('%Y-%m-%d %H:%M:%S')}*
"""
    return md


def main():
    p = argparse.ArgumentParser(description="B 站视频：自动取 Cookie + 抓字幕/语音识别 + 生成结构化总结")
    p.add_argument("url_or_bvid", help="B 站视频链接或 BV 号，如 BV1znMH6mEM1")
    p.add_argument("--out", default="./bili_output", help="输出目录（默认 ./bili_output）")
    p.add_argument("--cookie-file", help="已有 Cookie 文件路径；省略则自动从浏览器 CDP 提取")
    p.add_argument("--cookie-text", help="直接传入 Cookie 字符串（k=v;...）")
    p.add_argument("--cdp-port", type=int, default=9222, help="浏览器调试端口（默认 9222）")
    p.add_argument("--skip-cookie-extract", action="store_true",
                   help="不自动从浏览器提取 Cookie（需同时提供 --cookie-file/--cookie-text）")
    p.add_argument("--asr", action="store_true",
                   help="强制走语音识别（即使有字幕也用原声转写覆盖）")
    p.add_argument("--no-asr", action="store_true",
                   help="禁用自动语音识别（无字幕时只输出元数据）")
    p.add_argument("--asr-model", default=None,
                   help="ASR 模型：模型名(small/base) 或本地模型目录路径；默认 small（自动下载）")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    bvid = parse_bvid(args.url_or_bvid)
    video_url = f"https://www.bilibili.com/video/{bvid}/"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) Cookie 准备
    cookie_text_final = args.cookie_text
    cookie_file = None
    if args.cookie_file:
        cookie_file = Path(args.cookie_file)
        if not cookie_text_final:
            cookie_text_final = cookie_file.read_text(encoding="utf-8").strip()
    elif not args.cookie_text and not args.skip_cookie_extract:
        print(f"[cookie] 从浏览器 CDP 端口 {args.cdp_port} 提取 bilibili.com Cookie ...")
        cookies = extract_cookies("bilibili.com", args.cdp_port, args.verbose)
        if not cookies:
            print("[error] 未能从浏览器提取 bilibili.com Cookie。", file=sys.stderr)
            print("        请确认：浏览器已加 --remote-debugging-port=9222 --remote-allow-origins=* 启动",
                  file=sys.stderr)
            print("        并已打开登录态的 B 站标签页。", file=sys.stderr)
            sys.exit(1)
        cookie_text_final = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        cookie_file = out_dir / "cookies.txt"
        cookie_file.write_text(cookie_text_final, encoding="utf-8")
        print(f"[cookie] 已提取 {len(cookies)} 条 Cookie -> {cookie_file}")
    elif not cookie_text_final:
        print("[error] 未提供 Cookie 且禁用了自动提取。", file=sys.stderr)
        sys.exit(1)

    # 2) 视频信息
    sess = make_session(cookie_file=cookie_file, cookie_text=cookie_text_final)
    print(f"[info] 正在获取视频信息：{bvid}")
    info = fetch_video_info(sess, bvid)
    cid = info.get("cid")
    title = info.get("title", "")
    print(f"[info] 标题：{title}")
    print(f"[info] UP 主：{info.get('owner', {}).get('name', '未知')}")
    print(f"[info] CID：{cid}，时长：{info.get('duration')} 秒")

    # 3) WBI 签名 + 字幕
    mixin_key = fetch_wbi_keys(sess)
    if args.verbose:
        print(f"[wbi] mixin_key={mixin_key[:16]}...")
    player_data = fetch_player_v2(sess, bvid, cid, mixin_key)
    lines, source_name, sub_url = download_subtitle(sess, player_data)
    print(f"[subtitle] 字幕来源：{source_name}，共 {len(lines)} 句")

    # 4) ASR 分支（无字幕自动触发；或 --asr 强制；--no-asr 禁用）
    use_asr = False
    if args.asr:
        use_asr = True
    elif not lines and not args.no_asr:
        use_asr = True

    if use_asr:
        print("[asr] 进入语音识别分支（需 ffmpeg + faster-whisper）...")
        try:
            wav = None
            # 快路：B站 PC 客户端本地缓存直读（免下载，原缓存只读不动）
            try:
                from bili_cache import find_media_for
                _hit = find_media_for(bvid=bvid, cid=str(cid),
                                      fix_out=out_dir / "cache_fix")
                if _hit and _hit.get("media", {}).get("audio"):
                    print(f"[cache] 命中客户端缓存「{_hit.get('title') or bvid}」，免下载")
                    wav = out_dir / "audio.wav"
                    _r = subprocess.run(
                        ["ffmpeg", "-y", "-v", "error", "-i",
                         _hit["media"]["audio"], str(wav)],
                        capture_output=True, text=True)
                    if _r.returncode != 0:
                        print(f"[cache] 缓存音频转 wav 失败，回落下载："
                              f"{_r.stderr[:120]}")
                        wav = None
            except ImportError:
                pass
            if wav is None:
                audio_url = fetch_playurl(sess, bvid, cid, mixin_key)
                wav = download_audio(audio_url, out_dir / "audio.wav", cookie_text_final, args.verbose)
            print(f"[asr] 音轨就绪：{wav.stat().st_size} bytes，开始转写...")
            asr_lines = asr_transcribe(wav, args.asr_model, args.verbose)
            if asr_lines:
                lines = asr_lines
                source_name = "语音识别(ASR)"
                print(f"[asr] 识别完成，共 {len(lines)} 句")
            else:
                print("[asr] 未识别到有效语音片段。", file=sys.stderr)
        except Exception as e:
            print(f"[asr] 失败：{e}", file=sys.stderr)
            if not lines:
                print("      由于无字幕且无 ASR，仅输出元数据。", file=sys.stderr)

    if not lines:
        print("[warn] 该视频未生成字幕或字幕为空，且未启用/未成功执行语音识别。输出仅含元数据。",
              file=sys.stderr)

    # 5) 落盘
    info_file = out_dir / "info.json"
    info_file.write_text(json.dumps({
        "bvid": bvid,
        "title": title,
        "url": video_url,
        "owner": info.get("owner", {}),
        "duration": info.get("duration"),
        "pubdate": info.get("pubdate"),
        "cid": cid,
        "subtitle_source": source_name,
        "subtitle_url": sub_url,
        "subtitle_lines": len(lines),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    transcript_file = out_dir / "transcript.txt"
    transcript_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ASR 后离线质量门禁：零成本探针，只报信号不拦截。异常时上层需人工复核。
    try:
        from asr_quality import probe as _quality_probe
        _q = _quality_probe(transcript_file, info.get("duration"))
        print("RESULT_JSON:" + json.dumps(
            {"quality": {k: v for k, v in _q.items() if k != "file"}},
            ensure_ascii=False))
        for _w in _q.get("warnings", []):
            print(f"[quality] ⚠ {_w}")
    except Exception:
        pass  # 探针自身故障不影响主流程

    summary_file = out_dir / "summary.md"
    summary_file.write_text(build_summary(info, bvid, video_url, source_name, len(lines)),
                            encoding="utf-8")

    # ASR 额外输出无时间戳纯文本，便于二次处理
    if "ASR" in source_name or "语音" in source_name:
        (out_dir / "transcript_full.txt").write_text(
            "".join(l.split("] ", 1)[1] if "] " in l else l for l in lines),
            encoding="utf-8")

    print(f"\n[ok] 已输出到 {out_dir.resolve()}：")
    print(f"    - {info_file.name}")
    print(f"    - {transcript_file.name}")
    print(f"    - {summary_file.name}")


if __name__ == "__main__":
    main()
