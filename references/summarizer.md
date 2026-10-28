---
name: bilibili-video-summarizer
description: 当用户需要「总结/提取 B 站某个视频的内容」时使用。自动完成：从已登录的 Chromium 浏览器里提取 bilibili.com Cookie（CDP），经 WBI 签名调用 B 站 API 获取视频元数据与 AI/普通字幕；无字幕时自动用 ffmpeg 下载音轨 + faster-whisper 本地语音识别（ASR）转写；输出结构化 Markdown 总结、逐句时间戳文稿和 info.json。可交给其他 agent 或机器复用。触发词：总结 B 站视频、提取 bilibili 字幕、B 站视频转文字、bilibili 视频总结、爬 B 站视频、B 站无字幕转写。
agent_created: true
---

# B 站视频内容提取与总结术式

## Overview

主上想把「浏览器里已登录的 B 站视频」搬运成可阅读的结构化文本。本术式把前序踩坑链路打包为单一可执行方案：

1. **取 Cookie**：用 CDP 从浏览器当前打开的 B 站标签页提取登录态。
2. **取元数据**：B 站 `view` API 拿标题、UP 主、时长、简介、CID。
3. **WBI 签名 + 取字幕**：B 站字幕真实 URL 需 WBI 签名的 `player/wbi/v2` 才能拿到，脚本自动完成。
4. **无字幕兜底（ASR）**：视频无字幕 / AI 字幕未生成时，自动走语音识别分支——WBI 签名的 `playurl` 拿 DASH 音频流 → ffmpeg 下载转 16k 单声道 wav → faster-whisper 本地中文转写。
5. **出总结**：生成 `summary.md` + `transcript.txt`（ASR 时附 `transcript_full.txt`）+ `info.json`。

交给其他 agent / 别的电脑时，只需把本 skill 目录拷过去，按下方「复用给别的机器」一节启动即可。

## 何时使用

- 用户说「总结这个 B 站视频」「把这个视频的内容整理出来」「提取 B 站字幕」。
- 视频**没有字幕**但需要文字稿：加 `--asr` 或保持默认（无字幕自动触发语音识别）。
- 需要把 B 站教程/讲座/直播录像转成文字稿，方便检索、翻译或喂给 LLM 二次总结。
- 与 Unity/VRChat/改模教程相关：快速提取 UP 主的操作流程，不必边看边记。

## 前置条件

### 1. 浏览器开启调试端口

本术式绕开 Chromium 加密的 Cookie 数据库，直接从浏览器内存里取明文 Cookie。浏览器必须以调试端口启动，并允许任意来源连接：

**星愿浏览器 (Twinkstar)**：
```bat
"C:\Program Files\Twinkstar Browser\twinkstar.exe" --remote-debugging-port=9222 --remote-allow-origins=*
```

**Chrome / Edge**：
```bat
chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
```

⚠️ **必须带 `--remote-allow-origins=*`**，否则 CDP WebSocket 握手会 403 Forbidden（星愿尤甚）。

验证端口已开：浏览器里访问 `http://127.0.0.1:9222/json/version`，应返回 JSON。

### 2. 目标 B 站视频已打开且处于登录态

脚本会遍历 `/json/list` 的 page target，只连 URL 含 `bilibili.com` 的标签页，调用 `Network.getCookies`。若没登录，则拿不到 `SESSDATA` 等会话 Cookie，B 站 API 可能返回 `-352` / `-403` / 空字幕，且 `playurl` 拿不到高码率音频流。

**优先级建议（2026-09-18 教训）**：拿不到 CDP 端口时，**不要**用空 Cookie 硬跑——空 Cookie 会让字幕静默变 0 句并误触发 ASR，白烧几分钟还拿到质量更低的繁体转写。正确顺序是：
1. 先用 `--no-asr` + 空 Cookie 探一次，确认字幕是否为 0 句；
2. 若为 0 句，**直接向用户索取 Cookie 字符串**（`SESSDATA` / `bili_jct` 等，单行 `k=v; k2=v2`），落盘后重跑；
3. 只有确认视频真的没有官方字幕，才启 ASR。

### 3. Python 环境（基础依赖）

- 需要 `requests` 与 `websocket-client`。
- WorkBuddy managed Python 3.13.12 已内置；若缺失：`pip install requests websocket-client`。

### 4. ASR 分支依赖（可选，仅无字幕/强制 `--asr` 时需要）

- **ffmpeg**：必须在系统 `PATH` 内（`ffmpeg -version` 可查），用于下载并转码音轨。
- **faster-whisper**：`pip install faster-whisper`（体积较大，含 ctranslate2 / onnxruntime 等）。
- **模型**：默认 `small`（约 480MB）首次会从 HF 镜像 `https://hf-mirror.com` 自动下载到 `~/.cache/huggingface`。若本机已有模型目录，设环境变量 `BILI_WHISPER_MODEL_DIR=/path/to/whisper_small` 或传 `--asr-model /path/to/whisper_small` 走本地高速加载（目录需含 `model.bin`、`tokenizer.json`、`vocabulary.txt`、`config.json`）。
- 未安装 faster-whisper 时，脚本不会崩溃：仅跳过 ASR 并打印提示，字幕路径照常工作。

## 执行步骤

### 标准用法（自动取 Cookie + 出总结；无字幕自动 ASR）

```bash
cd bilibili-video-summarizer
python scripts/bili_video.py BV1znMH6mEM1 --out ./result
```

或传完整链接：

```bash
python scripts/bili_video.py "https://www.bilibili.com/video/BV1znMH6mEM1/" --out ./result
```

执行后会自动：
- 从 `127.0.0.1:9222` 提取 `bilibili.com` Cookie 到 `./result/cookies.txt`
- 拿到视频元数据 → `./result/info.json`
- 有字幕 → 下载字幕；无字幕 → 自动语音识别（ffmpeg 下载音轨 + faster-whisper 转写）→ `./result/transcript.txt`
- 生成总结 → `./result/summary.md`

### 只验证字幕、不跑 ASR（探底 / 省时间）

```bash
python scripts/bili_video.py BV12VeF6AEWK --out ./result_probe --no-asr
```

字幕为 0 句时不会进入语音识别分支，秒级返回，用于快速判断「这视频到底有没有官方字幕」。

### 强制走语音识别（即使视频有字幕也想用原声转写）

```bash
python scripts/bili_video.py BV15VGb6gERU --out ./result --asr
```

### 指定本地 ASR 模型（跳过下载）

```bash
BILI_WHISPER_MODEL_DIR=<你的模型目录>/whisper_small python scripts/bili_video.py BV15VGb6gERU --out ./result
# 或
python scripts/bili_video.py BV15VGb6gERU --asr-model <你的模型目录>/whisper_small --out ./result
```

### 指定调试端口

```bash
python scripts/bili_video.py BV1znMH6mEM1 --cdp-port 9222 --out ./result
```

### 已有 Cookie 文件时跳过自动提取

```bash
python scripts/bili_video.py BV1znMH6mEM1 \
    --cookie-file ./result/cookies.txt \
    --skip-cookie-extract \
    --out ./result
```

Cookie 格式支持单行 `k=v; k2=v2`（与 CDP 脚本默认输出一致）。

## 复用给别的 agent / 别的电脑

1. 把整个 `bilibili-video-summarizer/` 目录拷走（zip / git / 直接复制）。
2. 目标机器安装 Python 3.10+，并安装依赖：
   ```bash
   pip install requests websocket-client
   # 如需无字幕转写（ASR）：
   pip install faster-whisper
   # ffmpeg 需另行安装并加入 PATH（Windows 可用 scoop install ffmpeg / 官网压缩包）
   ```
3. 按「前置条件」用调试端口启动浏览器，打开登录态的 B 站视频。
4. 运行 `python scripts/bili_video.py <BV号> --out <目录>`。

**交给其他 LLM agent 时的标准指令模板：**

```text
请调用本地 skill bilibili-video-summarizer：
1. 确认用户浏览器（Twinkstar/Chrome/Edge）已用 --remote-debugging-port=9222 --remote-allow-origins=* 启动，且 B 站视频标签页处于登录态。
2. 执行：python scripts/bili_video.py <BV号或URL> --out ./bili_output
3. 若视频无字幕，脚本会自动走语音识别（需本机有 ffmpeg + faster-whisper）；如需强制转写加 --asr。
4. 读取 ./bili_output/summary.md 与 ./bili_output/transcript.txt 向用户汇报核心内容。
```

## 输出文件说明

| 文件 | 内容 |
|------|------|
| `info.json` | BV 号、标题、UP 主、UID、CID、时长、发布时间、文本来源、行数 |
| `transcript.txt` | 逐句稿，带时间戳 `[mm:ss] 文本`，可直接搜索或喂 LLM |
| `transcript_full.txt` | **仅 ASR 时**生成：去掉时间戳的纯文本，便于二次总结 |
| `summary.md` | 结构化 Markdown 总结：标题、链接、UP 主、简介、核心要点、章节速览 |
| `cookies.txt` | 自动提取的 bilibili Cookie（敏感，勿外传） |

## 故障排查

| 现象 | 根因 | 对策 |
|------|------|------|
| `未提取到 domain 含 bilibili.com 的 Cookie` | 浏览器没开调试端口 / 没加 `--remote-allow-origins=*` / B 站标签页未登录 | 重启浏览器带参数；确认标签页登录 |
| `view API 返回 -352 或 -403` | Cookie 无效 / 被风控 / 未登录 | 重新登录 B 站，刷新标签页，重跑 |
| `字幕来源：无字幕，共 0 句` | 视频本身没有字幕 / AI 字幕未生成 / 未登录导致返回空 | 保持默认会自动触发 ASR；或确认已登录 |
| WebSocket 403 | 浏览器没加 `--remote-allow-origins=*` | 重启浏览器 |
| `[asr] 失败：未安装 faster-whisper` | ASR 依赖缺失 | `pip install faster-whisper` |
| `[asr] 失败：ffmpeg 未能生成可用音轨` | ffmpeg 不在 PATH / 网络中断 | `ffmpeg -version` 验证；检查网络与 Cookie 登录态 |
| `[asr] 失败：playurl 未返回音频流` | 未登录 / 地区限制 / 该视频仅 FLV 源 | 确认 B 站标签页登录态；重试 |
| ASR 首次极慢 | 正在从 HF 镜像下载 small 模型（~480MB） | 设 `BILI_WHISPER_MODEL_DIR` 指向本机已下载模型目录以跳过 |
| `Segmentation fault`（构造 WhisperModel 时，进程退出码 139） | 罕见：本机其他软件写入的 Intel OpenMP(`libiomp5md.dll`)/MKL 或 VC++ 运行时与 ctranslate2 自带版本 DLL 冲突（Windows 环境退化个例；干净环境通常不触发） | 本技能已在 `asr_transcribe` 内置 `os.add_dll_directory`，优先加载 ctranslate2 自带 `libiomp5md.dll`。若仍崩：重启系统清理冲突运行时；或在干净 Python 环境 `pip install --force-reinstall ctranslate2 faster-whisper` |
| `[subtitle] 字幕来源：无字幕，共 0 句` 但视频明显有字幕 | 传了空/无效 Cookie，脚本「假性无字幕」并误触发 ASR | 换有效 Cookie 重跑；仅验证字幕时加 `--no-asr` 免得白等 |
| ASR 报 `CAS Client Error ... 401 Unauthorized, domain: https://cas-server.xethub.hf.co` | 新版 `huggingface_hub` 默认走 xet 协议，被 CAS 服务拒绝（设 `HF_ENDPOINT` 镜像也拦不住） | 加环境变量 `HF_HUB_DISABLE_XET=1` 强制走普通 HTTP |
| 输出目录已有结果却被清空/覆盖 | 脚本在「无字幕 + ASR 失败」时仍写 `summary.md`/`transcript.txt` | 每次跑用独立 `--out` 目录 |

## 扩展：不只 B 站

本 skill 的 `scripts/extract_cookies.py` 是通用 CDP Cookie 提取器，可复用于其他站点：

```bash
# 给 yt-dlp / gallery-dl 用的 Netscape cookies.txt
python scripts/extract_cookies.py --domain youtube.com --format netscape --out youtube_cookies.txt
```

如需把「Pixiv / YouTube / Twitter」的「取 Cookie + 内容提取」也做成端到端方案，可复制 `bili_video.py` 的结构，替换对应 API 调用即可。

## 踩坑结晶

- **必须连到开着目标站点的 page target**：空白页 `/json/list` 的 `getCookies` 返回空子集。
- **WebSocket 必须带 `Origin` 头**：脚本默认发送 `Origin: http://127.0.0.1:<port>`。
- **B 站字幕真实 URL 需 WBI 签名**：`view` 接口返回的 `subtitle_url` 对 AI 字幕可能是空的，必须调 `player/wbi/v2` 才能拿到。
- **音频流走 `player/wbi/playurl`**：取音轨要用另一套 WBI 签名接口（不是 v2），返回 DASH `audio` 列表，按带宽排序取最高码率。
- **ffmpeg 下载媒体流比 Python 流式下载稳健**：直接 `requests.get` 音轨易因 CDN 读取超时中断（残片）；用 `ffmpeg -headers "Referer/Cookie" -rw_timeout 120000000` 直连更稳；先试 `-c copy` 存 m4a，失败再解封装转 wav。
- **whisper 输入需 16k 单声道 wav**：`-ar 16000 -ac 1 -c:a pcm_s16le`。
- **HF 模型下载走镜像**：设 `HF_ENDPOINT=https://hf-mirror.com` 避免官网被墙；本机已有模型时优先用 `BILI_WHISPER_MODEL_DIR` 环境变量避免重复下载。
- **不要尝试 `browser_cookie3` 解密 Chrome 127+ Cookie 库**：App-Bound Encryption 会失败，CDP 才是稳定方案。
- **Cookie 文件敏感**：落盘文件包含 `SESSDATA`、`bili_jct` 等登录凭证，勿外传，仅在本机使用。
- **字幕/音频流必须登录态（关键坑）**：B站 AI 字幕与 `player/wbi/playurl` 音频流均需有效 `SESSDATA`。未登录或占位 Cookie 时 `player/wbi/v2` 字幕返回空、`playurl` 返回 `-403`/空，脚本会误判为「无字幕」进而触发 ASR 或仅输出元数据。**无浏览器调试端口时**，用 `--skip-cookie-extract --cookie-file` 指向本机已有的有效 `cookies.txt`（如 `./cookies.txt`、`./cookies.txt`）；本机已缓存 whisper `small` 模型于 `<你的模型目录>/whisper_small`（2026-09-18 已补全 `model.bin` 483 MB），传 `--asr-model <你的模型目录>/whisper_small` 直载免联网下载。
- **空 Cookie 会「假性无字幕」，白烧 ASR 时间（2026-09-18 实测）**：为绕过脚本的 Cookie 必填校验，传入**空** `--cookie-file` 可以跑通，但 `player/wbi/v2` 会返回 0 句，脚本误判「无字幕」直接触发 ASR（本机 538 秒视频耗时 5 分 23 秒）。同一视频换真 Cookie 后拿到 **324 句官方字幕**。→ 铁律：**先拿到有效 Cookie 再跑**；只想验证字幕是否存在时，加 `--no-asr` 避免白跑。
- **HF 模型下载被 xet CAS 拦死**：即使设了 `HF_ENDPOINT=https://hf-mirror.com`，新版 `huggingface_hub` 默认走 xet 协议，报 `RuntimeError: Task error: File reconstruction error: CAS Client Error: HTTP status client error (401 Unauthorized), domain: https://cas-server.xethub.hf.co/...`。**对策：同时设 `HF_HUB_DISABLE_XET=1`**，强制回退普通 HTTP 下载，走镜像 31 秒拿到 483 MB。
- **HF 缓存目录可能「假完整」**：`~/.cache/huggingface/hub/models--Systran--faster-whisper-small` 曾只落了 `config.json` / `tokenizer.json` / `vocabulary.txt`（合计 2.6 MB）而无 `model.bin`，看起来像「本机已有模型」实则不可用。**核验标准只看 `model.bin` 是否存在且约 480 MB**。
- **ASR 输出为繁体 + 同音错字**：`Systran/faster-whisper-small` 对中文普通话输出**繁体**，并伴少量同音替换（实测：文件夹→文件甲、根因→更音、噪声→造聲、车祸现场→使善现场、学坏→徐壞）。官方字幕质量显著更高，ASR 仅作兜底；若必须用 ASR，需后处理转简体 + 人工校对关键词。
- **失败也会覆盖既有成果**：即使字幕为空且 ASR 失败，脚本仍会写出 `summary.md` / `transcript.txt`，**覆盖上一次的有效结果**。→ 每次跑用独立 `--out` 目录（本次以 `bili_BV12VeF6AEWK_sub` 单独跑字幕，保住了先前的 ASR 产物）。
- **CDP 端口不可用时的替代通道**：浏览器没开 `--remote-debugging-port` 时（`http://127.0.0.1:9222/json/version` 拒绝连接），可先用 `opencli --profile <profile> browser <session> open <url>` 打开目标页；但注意两点——opencli 的 `network` 抓包**看不到 httpOnly Cookie**（`SESSDATA` 取不到），且 B 站若未请求字幕接口则抓不到字幕 JSON。**最省事的路径仍是直接向用户索取 Cookie 字符串**，落盘为单行 `k=v; k2=v2` 格式即可。

## 2026-10-25 融入升级（吸收三仓库：let-ai-read-video / video-watch-skill / dsh-bili-humanism）

### GPU 转写（默认启用，5.7× 提速）

- `bili_video.py` 的 `asr_transcribe` 已改 device auto：探测到 CUDA 即 GPU `float16`，
  初始化失败或转写中途失败自动回退 CPU `int8` 重跑。`BILI_WHISPER_DEVICE=cpu|cuda` 可强制。
- GPU 依赖 pip 包 `nvidia-cublas-cu12` + `nvidia-cudnn-cu12`（本机 venv 已装）。
  **ctranslate2 的 DLL 解析不认 `os.add_dll_directory`（实测无效），必须把
  `nvidia/*/bin` 前置到 PATH**——代码已内置处理。
- CUDA 错误可能延迟到**消费 segments 生成器时**才爆发（cuDNN 惰性加载），
  生成器迭代必须 try/except 并整体回退重跑，不能只包模型加载。
- 实测：RTX 3080，538s 音轨 CPU 266s → GPU 47s。GPU/CPU 量化差异使分段句数微变（224→202），正常。

### B 站客户端缓存直读（免下载快路）

ASR 分支在下载前自动探测本机 B 站 PC 客户端缓存（`~/Videos/bilibili/`）：命中同 BV/cid
条目则剥 m4s 头部 9 字节伪前缀生成修复副本（**原缓存只读不动**）→ 转 wav 直转写，零网络。
也可手动跑：`python scripts/bili_cache.py --list`（列条目）/ `--bvid BV...`（命中并修复）。
未命中则回落在线下载，行为不变。合成条目实测：修复副本 ffprobe 时长与源一致，audio/video 分类正确。

### ASR 后离线质量门禁（探针，不拦截）

`bili_video.py` 写完 transcript 后自动跑 `scripts/asr_quality.py`，输出
`RESULT_JSON:{quality:{...}}`。三信号与阈值：**字/分钟** <50 或 >400（空音频/漏转/文件错配）、
**繁体行占比** >30%（字幕来源可疑——治「空 Cookie 拿繁体 AI 字幕白烧 ASR」旧伤）、
**拉丁碎片率** >50% 且拉丁串 ≥10（ASR 按音节乱拼外文名的幻觉信号）。
触警时上层应人工复核或换字幕来源，不要直接采信转写。也可手动跑：
`python scripts/asr_quality.py transcript.txt --info info.json`。

### 多P / 合集守则

输入是多P视频或合集时：先探测清单（集数+标题+时长）摆给用户选集，意图不明不擅自全跑；
超过 10 集先报总时长与预计耗时，确认后再执行。逐集产出独立目录，单集失败跳过不影响其余。
