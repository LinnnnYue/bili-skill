---
name: bili-deep-report
description: 把 B 站视频做成「单文件 HTML 深度解析报告」——含视频正文、评论区生态、弹幕反应三源。当用户要求「总结B站视频」「要包含评论区」「做一份视频解析/吃瓜报告」「深度解析」时使用。无字幕视频自动走音频 ASR 兜底。触发词：B站总结、bilibili总结、包含评论区、视频深度解析、吃瓜报告。
agent_created: true
---

# B站视频深度解析报告

把一条 B 站视频变成可阅读、可引用的离线 HTML 报告。三个数据源，缺一不可：

| 源 | 接口 / 手段 | 得到什么 |
|---|---|---|
| 视频正文 | 字幕 → B站 AI 摘要 → 音频 ASR | 论证脉络、原话、时间轴 |
| 评论区 | WBI 评论接口 | 观点阵营、高赞原文、争议焦点 |
| 弹幕 | 弹幕 XML 接口 | 观众实时情绪、集体落点 |

**核心原则：不要因为「没有字幕」就退化成只看简介写总结。** 无字幕是常态，必须走 ASR 兜底。

## 一、取 ID 与元数据

从 URL 提取 `BVxxxxxxxxxx`。元数据一把取全（标题、UP、时长、简介、stat 七项）：

```bash
python "$SKILL/scripts/extract_bilibili.py" "BVxxxxxxxxxx" --out ./tmp_bili_extract --comments
```

（`extract_bilibili.py` 来自 bili-note skill；若不可用，直接调
`https://api.bilibili.com/x/web-interface/view?bvid=<BV>`，注意返回体是 `{"data":{...}}` 套一层。）

## 二、字幕探测（三步判定，别跳）

1. 公开字幕接口：`/x/player/wbi/v2?bvid=&cid=` → 看 `subtitle.subtitles`。
2. 若为空数组，**带登录态再探一次**（用 `scripts/bili_probe.py`，Cookie 走环境变量 `BILI_COOKIE`）。
   登录后仍为 `subtitles: []` 才是真的「无任何字幕轨」。
3. **登录态下大概率存在 `ai-zh` 自动字幕轨** —— 它比 ASR 快两个数量级、且**无同音误字**，优先用它。
   下载见 `scripts/fetch_subtitle.py <BV> <CID>`（读 `BILI_COOKIE` 环境变量）。
   两个已知特征：**该轨无标点**，且按语义碎片切分（实测约 11 字/段），
   所以「按标点切句」的统计会失效，做句长/句数分析前须自行断句或改用 3-gram 类统计。
4. B站 AI 摘要接口（可省时）：

```bash
python "$SKILL/scripts/bili_conclusion.py" <BV> <CID> <UP_MID>
```

`data.code == 0` 才有摘要；返回 `model_result.summary` 为空即该视频未被 AI 摘要覆盖（争议内容常见）。
**注意：`x/web-interface/view/conclusion/get` 需要 WBI 签名（img_key+sub_key 从 `/x/web-interface/nav` 取），签名逻辑见脚本。**

## 三、ASR 兜底（无字幕时的唯一正路）

### 3.1 环境（一次性）

```bash
python -m venv "$ASR_VENV"
"$ASR_VENV/Scripts/python.exe" -m pip install -U faster-whisper zhconv
```

**关键：HuggingFace 直连在中国网络下常超时（ConnectTimeout / IncompleteSnapshotError），必须设镜像：**

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

镜像可达性先自检：`curl -s -o /dev/null -w "%{http_code}" https://hf-mirror.com/`（期望 200）。
模型缓存若存在但缺 `model.bin`，是**断点残留的半成品**，用 `snapshot_download(..., allow_patterns=['*.bin','*.json','*.txt','*.md'])` 补齐即可，不要删缓存重下。

### 3.2 下音频

```bash
yt-dlp -f "bestaudio/best" \
  --add-header "Referer: https://www.bilibili.com/" \
  -o "bili_audio/%(id)s.%(ext)s" "https://www.bilibili.com/video/<BV>"
```

**yt-dlp 自带 WBI 签名，普通视频（含 1080P）音频下载不需要 Cookie。** 先裸跑，别一上手就塞 Cookie——
`BILI_COOKIE` 过期时（`/x/web-interface/nav` 返回 `isLogin: False`）塞进去反而可能干扰。

Cookie 只在两种情况下才必要：① 付费/大会员清晰度；② 需要登录态的字幕轨。
此时 `--cookies-from-browser` 在 Windows 上**大概率直接失败**（`Could not copy Chrome cookie database` /
`Failed to decrypt with DPAPI`），这两条路走不通就放弃字幕、直接走 ASR，不要在 Cookie 上耗时间。

> 另注：`curl` 直接打 `api.bilibili.com` 的 playurl 才会 412，那是**缺 WBI 签名**而非缺 Cookie，
> 用 curl 硬扛签名是本末倒置——下载一律交给 yt-dlp。

### 3.3 转写

```bash
"$ASR_VENV/Scripts/python.exe" "$SKILL/scripts/transcribe.py" bili_audio/<BV>.m4a tmp_bili_extract/transcript
```

- 默认 `small` + CPU + `int8` + `vad_filter=True`。
- **性能基线：38 分钟音频 ≈ 25 分钟转写（约 0.65× 实时）**，务必后台跑，不要前台阻塞。
- faster-whisper 对中文默认输出**繁体**，必须用 `zhconv.convert(text,'zh-cn')` 转简体，并对关键人名做同音字校正（张雪峰/张雪丰/张雪鋒/张子彪 等）。
- 常见同音误字需人工过一遍：填报志愿→"填爆志愿"、郑州大学→"郑作大学"、峰学蔚来→"丰学蔚来"。引用原话前先校正。

#### ⚠️ faster-whisper × PyAV 版本地雷（必看）

`faster-whisper 1.2.1` 依赖 `av>=11`，但它的 `audio.py` 调的是
`av.open(..., metadata_errors="ignore")`，而 **PyAV 19 已删除该参数**，于是必崩：

```
TypeError: open() got an unexpected keyword argument 'metadata_errors'
```

pip 会自动装上最新的 `av 19.x`，所以**新环境默认踩雷**。降 PyAV 能治但会牵连别的包，不值得。

**正解：绕开 PyAV，用 ffmpeg 管道喂 PCM 给模型。** 不依赖 `av` 解码，也顺带免掉额外转码：

```python
proc = subprocess.run(
    [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", AUDIO,
     "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],   # 16k 单声道 float32
    capture_output=True)
pcm = np.frombuffer(proc.stdout, dtype=np.float32).copy()
segments, info = model.transcribe(pcm, language="zh", beam_size=5, vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 500}, condition_on_previous_text=False)
```

- `np.frombuffer` 出来是只读视图，**必须 `.copy()`**，否则 ctranslate2 会报不可写。
- 参数要和 whisper 期望严格对齐：`16000 Hz / 单声道 / f32le`，三个都不能省。
- 完整可跑脚本见 `scripts/asr_run.py`（本次新增），它就是专为绕这个雷写的。
- 其他实测基线：**879.6 s 音频 → 179 段 → 428 s（0.49× 实时）**，`small/int8/CPU`，可前台跑但建议后台。

### 3.4 GPU 转写与 ASR 质量门禁（2026-10-25 融入）

**GPU 转写（默认已启用）**：`asr_run.py` / `transcribe.py` / summarizer 的 `bili_video.py`
共用 `scripts/whisper_device.py` 做 device auto——探测到 CUDA 即 GPU float16，失败自动回退 CPU int8。
`BILI_WHISPER_DEVICE=cpu|cuda` 可强制。

- GPU 依赖 pip 包 `nvidia-cublas-cu12` + `nvidia-cudnn-cu12`；**ctranslate2 的 DLL 解析
  不认 `os.add_dll_directory`（实测无效），必须把 `nvidia/*/bin` 前置到 PATH**——助手已处理。
- CUDA 错误可能延迟到**消费 segments 生成器时**才爆发（cuDNN 惰性加载）；
  迭代生成器要 try/except，GPU 模式下失败→整体回退 CPU 重跑（bili_video.py 有样板）。
- 实测基线：RTX 3080，9 分钟音轨 CPU 266s → **GPU 47s（5.7×）**。
- GPU/CPU 量化差异会让分段句数微变（224→202），正常，不影响语义。

**ASR 后质量门禁**：summarizer 的 `scripts/asr_quality.py`（探针，只报信号不拦截）。
三信号：**字/分钟**（<50 疑空音频/漏转，>400 疑文本与视频不匹配）、**繁体行占比**
（>30% 疑字幕来源可疑或 whisper 未简体化——治「空 Cookie 拿繁体 AI 字幕白烧 ASR」旧伤）、
**拉丁碎片率**（>50% 且拉丁串 ≥10 疑 ASR 按音节乱拼外文名）。来源：
dsh-bili-humanism 的取稿后离线质检。bili_video.py 已在写完 transcript 后自动跑并输出
`RESULT_JSON`；deep-report 流程可手动跑一次做门禁。

**多P/合集守则**（吸收自 let-ai-read-video）：先探测清单（每集标题+时长）摆给用户选集；
意图不明不擅自 `all`；超 10 集先报总时长与预计耗时，确认后再跑。

## 四、评论区（用户说「包含评论区」时是重点）

```bash
python "$SKILL/scripts/analyze_comments.py" tmp_bili_extract/comments_raw.json 40
```

- **两种接口形态不同，别混**：
  - `/x/v2/reply`（旧，**扁平**）：字段就是 `uname / like / rcount / message`，子回复在同级 `children[]`。分页用 `pn`，稳。
  - `/x/v2/reply/main`（新，**嵌套**）：用户名在 `member.uname`、正文在 `content.message`。
    直接按扁平字段取会得到一片 `None`，看起来像「接口挂了」。
  - **兼容写法**：`m = r.get("member") or {}; c = r.get("content") or {}`，再 `uname = m.get("uname") or r.get("uname")`。
  - `reply/main` 的 `cursor.next` 翻页常返回空页，取不全；要全量走旧接口 `pn` 翻页。
- 800 顶层 + 1000+ 子回复足够，不必强求全量。
- 输出：按赞排序的高赞榜（含高赞子回复）、关键词词频、点赞分层、按日分布。
- **别漏 `up_action.like` 与 `card_label`**：前者标记「UP 主觉得很赞」，后者可能是「UP 主觉得很赞」等运营标签。
  UP 主在评论区亲自答疑时，这两个字段能直接把「作者本尊的补充」从观众噪音里挑出来——
  教程类视频里，这往往是全篇最有价值的增量（本次视频的三条关键解法全部来自 UP 的子回复）。

**写报告时的读法**：把评论分成「亲历叙事」（我是农村/县城/某年高考）与「消费体验」（花多少钱、买了什么、退了没退）两类，
这两类通常各自代表一方立场，比简单的「支持/反对」二分更有信息量。

## 五、弹幕

```bash
curl -s --compressed -A "Mozilla/5.0" -H "Referer: https://www.bilibili.com/" \
  "https://api.bilibili.com/x/v1/dm/list.so?oid=<CID>" -o danmaku.xml
python "$SKILL/scripts/parse_danmaku.py" danmaku.xml
python "$SKILL/scripts/danmaku_timeline.py" danmaku.xml 120 > danmaku_timeline.md
```

- **必须加 `--compressed`**，否则拿到的是压缩字节乱码（表现为满屏怪字，容易误判为接口失效）。
- 返回条数有池上限（常见 3000–3600），不是全量。
- 弹幕按时间轴排布可以**反推视频结构**：某些段落弹幕突然密集或出现统一吐槽，说明那里是剪辑高潮。
- 高频重复弹幕（如「？」「还真是」）是集体情绪落点，值得单列。

## 六、报告产出（单文件 HTML）

用 `scripts/build_report_data.py` 聚合数据为 `report_data.json`，再注入 HTML 模板里的 `const D = __DATA__;` 占位符：

```bash
python - <<'PY'
html=open('report.html',encoding='utf-8').read()
data=open('report_data.json',encoding='utf-8').read().replace('</','<\\/')
open('report.html','w',encoding='utf-8').write(html.replace('__DATA__',data))
PY
```

**硬性要求：**

- **单文件离线**：所有图表手写内联 SVG / CSS 条形，不引 CDN。用户可能离线打开。
- **视觉（硬约束，动手前先读）**：**浅色毛玻璃高级感**——`backdrop-filter` 半透明卡片、圆角 12–16px、留白充足、
  克制光效、整片柔和渐变氛围层（禁止离散球体/散景光点）。强调色用沉静通透的 **靛蓝 `#4f46e5` / 紫罗兰 `#7c6cf5`**。
  - **禁用 magenta 色相系**（洋红、玫红及其明度变体），深底浅底皆然。
    权威判据见 `~/.workbuddy/MEMORY.md` 的「视觉配色铁律」节。
  - 单文件内置**浅/深双主题**切换（默认浅色、localStorage 记忆），并支持 `?theme=dark` URL 参数——便于 headless 截图验证两种主题。
  - 动效遵循 Taste 工程原则：自定义 `cubic-bezier(.23,1,.32,1)`、UI 时长 < 300ms、禁 `ease-in`、`:active{transform:scale(.94)}`、
    入场 stagger 40ms，并给 `prefers-reduced-motion` / `prefers-reduced-transparency` 降级。
- **必含板块**：一句话结论 → 视频论证脉络（带时间戳）→ 可迁移的判断 → 评论区看板（词频/点赞分层/时间衰减/高赞原文榜）→ 弹幕分析 → 争议焦点对照表 → 结论。
- **事实边界声明**：涉及当事人指控、私德、争议细节，一律标注「视频/网友所述」，不做事实裁决。
- 注入后校验：`node --check` 检查内嵌脚本语法 + 正则比对所有 `getElementById` 的 id 在 HTML 中真实存在。

### 6.1 第二数据源：配套课件 / PPT（视频是「讲课件」、课件才是本体时必做）

教学类、榜单类视频常配 PPT。**课件文字与口播互补而非重复**，只取其一都是残废：课件给出结构化表格（档位 / 数值 / 字段），
口播给出课件里没有的判断与勘误。两者都取，报告才有独家价值。

解析 PPTX 不必装 python-pptx，直接读 zip：

```python
import zipfile   # ns: a=drawingml/2006/main, r=officeDocument/2006/relationships
z = zipfile.ZipFile('x.pptx')
# 1) 按 a:p 段落切分 —— 别把整页文字拍平成一个字符串，否则字段全部错位
# 2) 图片映射走 rels：ppt/slides/_rels/slideN.xml.rels → rId → ppt/media/imageN.png
```

- **必踩坑：一个字段的「标签」与「值」常分属两个文本框**（`【上位替代】` 单独一个框、值在下一个框），
  顺序读下来会得到「有标签无值」。用 `pending` 状态变量跨行回填：

  ```python
  if t.startswith('【上位替代】'):
      v = t.replace('【上位替代】', '').strip()
      rec['up'] = v
      pending = None if v else 'up'      # 值为空 → 记下待回填字段
  elif pending and not rec.get(pending):
      rec[pending] = t; pending = None   # 下一段就是它的值
  ```

- **解析完必须对账**：与课件目录页声明的分档数量逐项比对（如 4/4/5/9/6/28/5），再断言零缺字段、零缺图。
  PPTX 解析的错永远是**静默丢字段**，不校验就发现不了。
- **口播能纠正课件错误**——最不可替代的增量。把「课件写错、UP 主亲口更正」单列成板块，
  并给对应条目打「课件有勘误」徽章（用**精确同名**匹配，别用子串，避免「阿修罗等 PVE 专精」这类非式神名误标）。
  同一对象在多个榜单重复出现（如既在 T2 又在 PVP 专精）是课件本意，不是解析 bug，不要「去重」。

#### 拿不到 pptx 原件时：从视频抽帧读课件

视频是「讲 PPT」，但 UP 主没给源文件——这时**不要退回只靠 ASR**。抽帧后当图片读，PPT 才是**数字与术语的第一权威**：
ASR 会把 `gem5` 听成「詹姆」、`kernel` 听成 `Carnal`、`Claude` 听成 `Cloud`、`PutnamBench` 听成 `Partnum Bench`，
而 PPT 上这些词**全是正确拼写**。本次报告里 72 道门、921→1121 行、118 份复盘、67.3%、19.08× 等数字**全部以帧为准**，ASR 只用来定时间轴。

```bash
# 定间隔抽帧（推荐）—— 别用场景检测
ffmpeg -i v1080.mp4 -vf "fps=1/15,scale=1280:-1" -q:v 3 kf/%03d.jpg
```

- **别用 `select='gt(scene,0.30)'`**：讲课件类视频画面高度静止、翻页是渐变淡入，场景分常常**一帧都不出**（本次实测 0 帧）。
  定间隔 `fps=1/15` 对 14 分钟视频得 59 帧，覆盖完整且可预期。
- **用 Pillow 拼九宫格再一次性读图**，别一张张 Read——59 张单独读既慢又烧上下文。拼图时文件名取
  `os.path.splitext(os.path.basename(f))[0]`，用 `f.split('/')[-1]` 在 Windows 上会带出 `kf\001` 这类脏串。
- 抽帧分辨率别只取 360p：**PPT 上的小字在 360p 下糊成一团**，必须抽 1080P（`-f bestvideo`）再缩到 1280 宽。
- 读到疑似关键数字的页，单独 `ffmpeg -ss <t> -frames:v 1` 高清单帧复核，别靠糊图猜。

> 判据：若视频里出现整页表格/代码/公式，就**必须**走这条路。纯口播配图型视频才可只靠 ASR。

#### 画面证据的标准姿势（2026-10-25 融入：联络表 + 融合抽帧）

吸收自 video-watch-skill（CFITCorporation）与 let-ai-read-video（xiaohui5206）。

**1) 联络表（contact sheet）——替代逐帧读图与手拼九宫格**：`scripts/contact_sheet.py`
把抽帧拼成带帧号 + 时间码烧录的网格图（5 列，ffmpeg `tile` 实现，**不需要 ImageMagick**），
同时产出 `mapping.json`（index/sheet/row/col → t）。读图姿势：读联络表 + mapping.json，
按 row/col 定位格子时间戳引用。

```bash
# 骨架模式：全片均匀 30 帧，附带「盲区上界」指标（= 时长/帧数，写进报告证据链）
python scripts/contact_sheet.py video.mp4 --out-dir sheets/ --skeleton 30
# 指定时刻模式：时刻表文件每行一个秒数（或 MM:SS）
python scripts/contact_sheet.py video.mp4 --out-dir sheets/ --times-file times.txt
```

- 启动即自检 ffmpeg 滤镜完整性（tile/drawtext/fps/scale），缺了**当场报错**——
  防「报错落在离根因很远的地方」（gyan full build 自带全部滤镜）。
- drawtext 的 text 里冒号必须转义（`01\:17`），否则 `01:17` 被截成 `01`（首测踩坑实录）。
- 盲区上界（blind_gap_sec）要写进报告证据链：「骨架采样 N 帧，最坏间隔 X 秒」。

**2) 融合抽帧——场景点优先 + 均匀补位**：`scripts/frames_fuse.py`
（思路来自 let-ai-read-video 的 auto 模式）。场景检测命中点最多占一半名额，
剩余名额均匀网格补位；**0 命中时自动退化为纯均匀**——PPT 类视频的救命分支
（纯 scene 模式在讲课件视频上实测一帧都不出，见上文 6.1）。

```bash
python scripts/frames_fuse.py video.mp4 --n 30 --out times.txt   # 产出时刻表
python scripts/contact_sheet.py video.mp4 --times-file times.txt --out-dir sheets/
```

- 镜头切换频繁的视频（教程/实机演示）→ 用融合；讲课件类 → 仍走 6.1 的定间隔 `fps=1/15`。

**3) 视听覆盖审查（可选审计步，吸收自 let-ai-read-video 的 review/refine 协议）**：
报告定稿前，把关键结论逐条对照「转写文本 + 联络表画面」标注五分类关系——
`supports`（画面/语音互证）/ `complements`（互补，不等于漏帧）/ `contradicts`（冲突，
需列出双方证据与时间差）/ `unrelated` / `insufficient`（证据不足）。只有
`insufficient` 或高置信 `contradicts` 才触发补帧（`ffmpeg -ss <t>` 单帧精确抽，
或 contact_sheet 追加一轮）；两轮为限，别无限加帧。

### 6.2 图片：先定交付形态，再决定内联还是托管

**这一步选错会白干一遍**，所以先问一句：产物是**本地双击看**，还是要**分享 / 上架**？

| 交付形态 | 图片策略 | 典型体积 |
|---|---|---|
| 本地单文件、发文件给对方 | **base64 内联**（自包含、离线可看） | 60 张 → 2.79 MB |
| 上架资料库 / 发链接 / 群里分享 | **托管直链**（`library` 技能的 `manage/upload_image.py`） | 同 60 张 → HTML 仅 128 KB |

压缩配方（两种形态共用，目视无损、体积降约 20 倍）：

```python
# PNG(RGBA 830×696, 60 张共 43.4 MB) → 宽 360 + WebP(q=76, alpha_quality=90, method=6)
im.thumbnail((360, 1440), Image.LANCZOS)
im.save(buf, 'WEBP', quality=76, alpha_quality=90, method=6)
# → 60 张共 2.01 MB WebP / 2.69 MB base64
```

**转托管直链的正确姿势——改数据层，不要改 HTML。** 图片地址存在 `report_data.json` 的 `media` 字段里，
把它从 `data:image/webp;base64,...` 换成直链后重新注入即可。直接对成品 HTML 做字符串替换是下策：
一旦再改模板重新注入，替换成果全丢。

这一步不用手写，技能自带脚本：

```bash
python "$SKILL/scripts/host_media.py" tmp/report_data.json          # 批量上传并就地改写
python "$SKILL/scripts/host_media.py" tmp/report_data.json --recover tmp/tmp_host/failed.json  # 回收
```

```python
# 反查 img_key → 式神名，让上传的文件名可辨认（"01_雪御前.webp" 而非 "image1"）
name_of = {}
for s in d["saints"]:
    k = s.get("img_key")
    if k and k not in name_of:
        name_of[k] = s.get("name", "")
```

- **解析上传结果时，`KS_IMAGE_UPLOAD_OK` 与 JSON 之间是空格分隔，不是 TAB**。按 `\t` 切分 → 索引越界 →
  被 `except Exception` 吞掉 → **60 张全部误判为失败**（实际全成功，白写一轮）。用正则抓整段：
  `re.search(r"KS_IMAGE_UPLOAD_OK\s+(\{.*\})", out)`。**宽 except 会吃掉真实错误，是这类误判的温床。**
- 万一误判也别重传：失败记录的 `stdout` 里存着 URL，回收即可（否则 COS 上留一堆孤儿对象）。
- 白色系立绘放浅色底上会「飘」，容器需加**径向渐变衬底**（`radial-gradient(58% 62% at 50% 104%, var(--accent-soft-2), transparent 74%)`）+ 发丝级 `drop-shadow` 才立得住。
- 表格内 34px 缩略图复用同一张图，不必另生成一套。

### 6.3 立绘版式：先量图片长宽比，再定卡片骨架

**图片形状决定容器形状，反过来必翻车。** 本次测得立绘原始比例 **360×302（近方形 1.19:1）**，
被塞进「立绘居左」的 196×628 窄长条后，只能缩到 172×144，仅占垂直空间 23% ——
视觉上就是「立绘孤零零飘在卡里」。

判断法：**图片长宽比 > 1.4 才适合左右分栏（窄列），否则必须给方形以上的容器**（顶部通栏 / 顶部横幅）。

| 图片形状 | 卡片骨架 | 效果 |
|---|---|---|
| 近方形（1.0–1.3） | **立绘顶部通栏 + 两列** | 立绘 258×216，舒展 |
| 竖长（< 0.8） | 立绘居左（窄列），文字在右 | 立绘撑满列高 |
| 横宽（> 1.6） | 立绘顶部通栏（矮），文字在下 | 避免左右分栏浪费高度 |

配套：卡片列数也要跟着降。三列 386px 宽时卡片会拉到 **823px 高（高宽比 2.13，竖条感）**；
改两列 584px 后高宽比降到 1.3 左右，才是舒服的比例。

### 6.4 排版调优：字号与布局必须成对改

用户说「字体大一点」时，**只动 `font-size` 一定会把布局搞散** —— 字撑大了、容器没跟上，于是行距挤、
卡片错位、表格断行。正确做法是两者成对推进：

```python
# 1) 字号：两阶段占位替换，防级联（12.5→14.5 之后 13→15 不会二次命中）
h = re.sub(r"font-size:(\d+(?:\.\d+)?)px", hold, h)   # 先换成 @v@ 占位符
h = re.sub(r"font-size:@([\d.]+)@", restore, h)        # 再统一还原
# 2) 布局：紧随其后按同一比例补偿，每项 assert count == 1
```

字号 +2px 时同步补偿的清单：卡片 `minmax` 下限、`grid-template-columns` 固定列宽、
`padding`、缩略图尺寸、`table min-width`、条形图轨道高度、`.stat .v` 数字字号。

**同时建立间距令牌，杜绝随手值**（这是「区域框架不协调」的常见根因）：

```css
--sp-1:4px; --sp-2:8px; --sp-3:12px; --sp-4:18px; --sp-5:26px; --sp-6:38px; --sp-7:56px;
--gap:20px;      /* 网格统一步长 */
--sec-pad:92px;  /* 分区纵向留白 */
--r-xl:20px; --r-lg:16px; --r:13px; --r-sm:10px;
```

把散落的 9/10/11/13/14/15px 全部换成令牌后，区块节奏立刻统一。

**可读性还有三件常被忽略的事：**

1. **辅助色对比度**要实测，别凭感觉。本次 `--ink-3` 在浅底上只有 **3.0:1**（WCAG AA 正文需 4.5:1），
   换成 `#646a8c` 提到 4.9:1；暗色主题 `#6d7396`(4.1:1) → `#8f96bb`(6.6:1)。
2. **中文断行**加 `text-wrap:pretty`（Chrome 121+），能避免「哪个 / 强」这类把一个词硬拆到两行。
3. **卡内层次收敛**：同一张卡里堆四种不同底色的容器（灰块 + 青块 + 蓝块 + pill）会造成视觉噪音。
   按语义分工——中性色只做分隔与次要信息，**主色只给真正要强调的那一块**，其余用左引线区分即可。

## 七、渲染验证（跳过这步 = 交半成品）

`node --check` 只查**语法**，查不出**运行时错误**；而运行时一挂，所有 `innerHTML` 容器会静默留空，
页面看起来「有骨架没内容」——极易被误判成样式问题。

**三步验证法（缺一不可）：**

1. **模板内置错误探针**（生产文件保留，平时不显示）：`window.onerror` 在左下角渲染一个报错条。
2. **导出渲染后 DOM 核对**（headless Chrome，无额外依赖）：

   ```
   chrome --headless=new --disable-gpu --virtual-time-budget=5000 --dump-dom "<file-url>" > dom.txt
   ```

   检查两件事：`<title>` 是否被探针改写成 `ERR|...`；各 `id` 容器内是否真有内容（字符数 > 50 为通过）。

3. **截图看视觉**（长篇报告用**两趟式定点截图**，别用整页超长图）：

   ```bash
   python "$SKILL/scripts/shot_section.py" <产物.html> "#t0a" out.png 1440 1100 [偏移px] [查询串]
   ```

   - **两趟式原理**：第一趟注入探针 dump 出目标锚点的文档 Y；第二趟把 `body{margin-top:-Ypx}` 写进静态 `<style>` 再截图。**零时序依赖**——比在 `load` 里设 `style.marginTop` 可靠（后者常与截图时机竞争而静默失效）。
   - **致命坑：两趟的 `--window-size` 必须完全一致**。探针趟若用默认窗口（800px），截图趟用 1440px，布局宽度不同 → Y 完全错位 → 截到毫不相干的区块，且看起来「像是截偏了」而不报错。
   - **`--force-prefers-reduced-motion` 有效的前提**是模板 CSS 里写了 `@media (prefers-reduced-motion:reduce){.rv{opacity:1!important;...}}`。若模板没有该降级，视口外元素会停在 `opacity:0` 截成空白。稳妥做法：截图趟额外注入 `.rv{opacity:1!important;transform:none!important;transition:none!important}` 双保险。
   - **Chrome headless 最小窗口宽度是 500px**：传 `--window-size=430,900` 实际仍按 500 渲染，输出图右侧被裁 —— **极易误判成「窄屏横向溢出」**。要测更窄宽度得用 CDP `Emulation.setDeviceMetricsOverride`。
   - 判断是否真溢出：探针读 `document.documentElement.scrollWidth` 与 `window.innerWidth` 对比，相等即无溢出。
   - `float` 之外的中文路径需 URL 编码：`python -c "import urllib.parse;print('file:///'+urllib.parse.quote(PATH))"`。
   - 确有整页需求时才用 `--window-size=1280,10000` 出高图，并用 Pillow 裁剪分段看，别整张硬读。

## 八、模板复用（改内容不改样式）

技能自带两个模板，按内容类型选：

| 模板 | 适用 | 结构 |
|---|---|---|
| `templates/bili_report_template_v2.html` | 观点 / 吃瓜 / 争议类 | 时间轴脉络 · 关键词 · 点赞分层 · 时间衰减 · 阵营对照 · 观点光谱 · 高赞榜 |
| `templates/bili_report_template_guide.html` | **攻略 / 教程 / 工具类** | 三十秒版 · 档位阶梯 · 逐项评定表 · 迷思对照 · 行动清单 · 内容密度 X 光 |

**通用注入 + 静态校验一条命令**（比手写注入可靠，会连带查禁色、id 绑定、标签闭合、JS 段导出）：

```bash
python "$SKILL/scripts/inject_report.py" <模板.html> <report_data.json> <输出.html>
node --check tmp/_check.js
```

模板内含占位符 `const D = __DATA__;`。

**做「工具/攻略类」内容时，值得加的两个特有板块：**

- **内容密度 X 光**：观众抱怨「车轱辘话」时，不要只写观感，用数据坐实——
  逐 3 分钟字数波动、关键词重复次数、「按话语功能分类」的句段计数（掉率自述 / 劝阻句式 / 纠错声明 / 反问 / 自我辩护），
  再配上弹幕里直接吐槽「讲法」的原话。这类量化是评论区和普通总结都给不出的独家价值。
- **术语对照表**：领域黑话（如魂本编号 10/11/12/13 vs 俗称魂十/魂土/魂王/魂玉）对非核心玩家是硬门槛，一张小表就能救回来。

```python
import json
d = json.load(open('report_data.json', encoding='utf-8'))
compact = json.dumps(d, ensure_ascii=False, separators=(',', ':')).replace('</', '<\/')
out = open('templates/bili_report_template_v2.html', encoding='utf-8').read().replace('__DATA__', compact)
open('报告.html', 'w', encoding='utf-8').write(out)
```

模板已含：hero 数据卡、11 段时间轴、可迁移判断卡、关键词条形、点赞分层、时间衰减 SVG、**阵营对照**、
观点光谱三栏、高赞评论榜、弹幕密度 SVG、争议对照表、浅/深主题、错误探针、滚动进度导航。

#### ⚠️⚠️ 换 body 不换 script 尾 = 交付一个空白页（本次最接近事故的坑）

模板末尾的 `<script>` **不只是渲染数据**，它还承载四件基础能力，换掉 body 时极易整块丢掉：

| 丢了会怎样 | 代码位置 |
|---|---|
| 全页 `.reveal` 停在 `opacity:0` → **真实浏览器打开是一片空白** | IntersectionObserver 给 `.reveal` 加 `.in` |
| 主题切换按钮失灵、`?theme=dark` 无效 | `data-theme` 初始化 + `themebtn` 点击绑定 |
| 导航进度条不动、`.nav.on` 不触发 | `scroll` 监听写 `prog.style.width` |
| 运行时错误不再可见 | `window.onerror` 探针 |

**为什么截图验证抓不到**：截图脚本会强制注入 `opacity:1!important`，所以截图上一切正常——
**只有真实浏览器里才是空白**。这是「截图全绿但交付物是坏的」的典型。

**正确做法**：只取模板 `</head>` 及之前的 CSS，body 自己写，但**必须把上述四块代码搬进自己的 IIFE**：

```js
/* 主题：URL 参数 > localStorage > 默认浅色 */
var q = new URLSearchParams(location.search).get('theme');
var saved = q || localStorage.getItem('bili-report-theme');
if (saved) document.documentElement.setAttribute('data-theme', saved);
/* reveal 观察器 + 进度条 + window.onerror 探针，照模板原样搬 */
```

**验收标准**：dump 出来的 DOM 里，`.reveal` 元素**有相当数量已带 `in` 类**（视口内的那批）。
若 `in` 类数为 0，说明观察器没跑——此时截图再好看也不能交付。

**别浪费 `camp` 数据**：`D.camp`（各立场条数 + 总获赞）藏着全篇最强的量化洞察——
本例中「为张雪峰辩护」的评论只有 103 条却拿到 14,250 赞（人均 138），批判方 114 条仅人均 46。
**人均获赞的错位比条数更能说明顶层舆论的真实倾斜**，务必做成对照表而不是闲置。

## 九、踩坑速查

| 现象 | 根因 | 处置 |
|---|---|---|
| `IncompleteSnapshotError: missing model.bin` | HF 断点残留 / 无网 | 设 `HF_ENDPOINT=https://hf-mirror.com` 后用 `snapshot_download` 补齐 |
| 弹幕 XML 满屏乱码 | 未解压 | `curl --compressed` |
| 评论解析 KeyError `member` | 实际是扁平结构 | 用 `uname / message / children` |
| `metadata.json` 取不到 `stat` | 外层套了 `data` | `raw.get("data", raw)` |
| 转写输出繁体 | whisper 中文默认 | `zhconv.convert(..., 'zh-cn')` |
| 视频无字幕且 AI 摘要为空 | 争议内容/未生成 | 只能走 ASR，不要硬写「无字幕故无法总结」 |
| **字幕轨看起来为空** | 未带登录态探测 | 带 Cookie 再探一次 `/x/player/wbi/v2`，常见 `ai-zh` 自动轨 |
| 条形图**只有灰底槽、没有填充色** | `.track` / `.fill` 写成 `span`，inline 元素 `width` 不生效 | 给两者加 `display:block`（grid item 会被 blockify，但它的**子** inline 元素不会） |
| SVG 某一根柱子渲染成**纯黑** | `fill="url(#x)"` 由 JS 拼接时，参数被拼到**闭合括号之外**（`url(#gd)' + '2'` → `url(#gd)2`） | 参数必须拼在括号内；失效的 `url()` 会静默回退黑 |
| 渐变在 SVG 里表现异常 | `stop-color` 引用了带 alpha 的 CSS 变量 | `stop-color` 只用 hex 变量（`--accent` / `--slate`），别用 `--x-soft` 一类 `rgba()` |
| 长页面不知道各区块在哪、截图总截偏 | 无绝对坐标 | 注入探针把 `scrollHeight` + 各 `section` 的 `offsetTop` 写进 `document.title`，再 `--dump-dom` 读出来 |
| 怀疑某个渲染属性没生效 | 靠肉眼猜 | 注入探针读 `getComputedStyle(el).fill` 一类**计算值**，一次定位，别猜 |
| 图表/评论容器**全空**、页面「有骨架没内容」 | 脚本**运行时**错误（`node --check` 查不出） | 内置 `window.onerror` 探针 + `--dump-dom` 看 `<title>` 是否被改写为 `ERR` |
| 截图整页空白、只剩背景 | 入场动效让视口外元素停在 `opacity:0` | 截图加 `--force-prefers-reduced-motion` |
| **改动丢失**：工具报成功但内容没变 | **同一文件在同一条消息里并行多个 Edit 互相覆盖**（后写覆盖前写，且两者均报成功） | 改同一文件一律**串行**；多处改动合成**一次脚本**原子替换，每处 `assert count == 1` |
| 数字卡数字换行、撑歪基线 | `font-size` 过大 / 卡片 `minmax` 过窄 | 数字加 `white-space:nowrap` + 降字号 + 提 `minmax`；百万级用一位小数 |
| **截到的区块完全不相干**，且不报错 | 定点截图两趟的 `--window-size` 不一致（探针趟默认 800、截图趟 1440）→ 布局宽度不同 → Y 错位 | 两趟必须同窗口尺寸；改用 `scripts/shot_section.py` |
| 截图右侧被裁，误判成「窄屏横向溢出」 | **Chrome headless 最小窗口宽 500px**，传 430 仍按 500 渲染 | 用探针比对 `documentElement.scrollWidth` 与 `innerWidth` 判定真假溢出；要更窄须走 CDP 设备模拟 |
| 截图整片空白 / 元素停在中途态 | 入场动画未触发（视口外 IntersectionObserver 不触发，`opacity` 恒为 0） | 加 `--force-prefers-reduced-motion`（前提是模板有该媒体查询），并额外注入 `.rv{opacity:1!important;transition:none!important}` |
| PPT 字段「有标签无值」 | 标签与值分属两个文本框 | `pending` 状态变量跨行回填（见 6.1） |
| 报告中同一数字前后不一致 | 同一概念存在两种口径（如「恰好 111」9 位 vs「≤114」11 位），各处各算 | **口径归一**：所有引用点统一读同一个计算源，并在文案里写清口径（`111 / 113 / 114 共 N 位`）|
| 正在跑的长任务（ASR 等）突然消失 | `taskkill /F /IM python.exe` 按**映像名**杀进程，连带杀掉所有 Python 任务 | 精确按 PID 杀（`tasklist` 取 PID 后 `taskkill /F /PID`），绝不按映像名批量杀 |
| 批量上传「全部失败」，但单张测试明明成功 | `KS_IMAGE_UPLOAD_OK` 与 JSON 之间是**空格**不是 TAB，按 `\t` 切分越界后被 `except` 吞成失败 | 正则抓整段 JSON；**别用裸 `except` 吞异常**，它会把真实错误伪装成业务失败 |
| 批量任务误判失败后不敢重跑 | 怕重复上传产生孤儿对象 | 从失败记录的 `stdout` 里回收 URL（本次 60/60 全回收，零重传） |
| 立绘在卡里「孤零零飘着」、四周大片空白 | 近方形图片（1.19:1）塞进窄长条容器，只能按宽度缩 | 先量 `naturalWidth/naturalHeight` 定长宽比；>1.4 才可左右分栏，否则改顶部通栏（见 6.3） |
| 卡片又高又窄、像竖条，读起来累 | 列数过多（3 列 386px）→ 卡片被撑到 823px 高（高宽比 2.13） | 降列数（2 列 584px）把高宽比压到 1.3 左右；同时用间距令牌统一节奏 |
| 正文字号调大后布局散了 | 只放大 `font-size`，没同步补偿容器尺寸 | 字号与布局成对改：字号 +2px 的同时，卡片 `minmax`、`grid-template-columns`、`padding`、缩略图尺寸一并放大（见 6.4） |
| **Chrome headless 在 Git Bash 下完全静默**：`--dump-dom` 输出 0 字节、`--screenshot` 连文件都不生成，且退出码 0 | Bash → Windows 的调用路径把参数/输出吞了 | **改用 PowerShell 工具跑 Chrome**，同样的命令立刻正常。这不是 Chrome 的问题，是 shell 层的问题 |
| Chrome 第一次调用正常，之后**全部静默空输出** | 复用同一个 `--user-data-dir`，上一次的进程锁/单例没释放 | **每次调用给独立 profile 目录**（`_c1` / `_d4` / `_e_seg_6` …），跑完即删。别图省事复用 |
| 整页截图命令 `--window-size=1440,9000` **静默失败**（文件未生成、无报错） | 超大视口超出 headless 渲染上限 | 放弃整页截图。改**分段**：生成 `body{margin-top:-Npx}` 的静态 `<style>` 副本，逐段 1440×1250 各拍一张 |
| 截图上半屏空白，`.reveal` 元素全不见 | 元素停在入场动画起始态 `opacity:0`（视口外 `IntersectionObserver` 不触发） | 注入 `.reveal{opacity:1!important;transform:none!important;transition:none!important;animation:none!important}`。**写进「仅供截图的副本」，绝不写进交付件**，否则交付件丢了动效 |
| `--force-prefers-reduced-motion` 加了没用 | 该 flag 只在模板写了 `@media (prefers-reduced-motion)` 时才生效 | 不要指望它。**两趟法**：一次生成带 `!important` 覆盖的截图专用 HTML，零时序依赖，比任何 flag 都稳 |
| 讲课件视频用场景检测抽帧，**一帧都抽不到** | PPT 翻页是渐变淡入、画面高度静止，`gt(scene,0.30)` 永不触发 | 改定间隔 `fps=1/15`；必须抽 1080P（360p 小字糊）；多帧拼九宫格一次读（见 6.1 补充） |
| PPT 上明明写着、ASR 却听成别的词 | 同音误字：gem5→"詹姆"、kernel→"Carnal"、Claude→"Cloud"、PutnamBench→"Partnum Bench" | **数字与术语一律以 PPT 帧为准**，ASR 只用于定时间轴；建一张术语校正表过一遍 |
| `pip` 从清华源装包 `SSLError(SSLEOFError)` | 镜像本身抖了 | 换源重试（aliyun 本次一次成功），配 `--trusted-host`；别在原地反复重试同一源 |
| `curl` 存到 `/tmp/x.json`，之后 Windows 的 Python **找不到** | Git Bash 的 `/tmp` 与 Windows Python 眼里的 `/tmp` **不是同一个目录** | 抓取与落盘**全在 Python 内完成**（`urllib.request` + 仓库相对路径），不跨 shell 传文件 |
| 评论 / 弹幕实测确实是 0，却想写点「观众反应」 | 想当然补内容 | **0 就写 0**，并在「数据源与证据链」里交代清楚：`page.count: 0`、弹幕 XML 无 `<d>` 标签。宁可承认缺一源，也不要编 |
| **换了模板 body、忘了搬 script 尾，真实浏览器打开是空白页**，而截图一切正常 | `.reveal{opacity:0}` 的解锁 IntersectionObserver、主题初始化、进度条、错误探针全在模板末尾的 `<script>` 里，随 body 一起被丢掉 | 只取模板 `</head>` 前的 CSS，但四块基础代码必须搬进自己的 IIFE。验收：dump 的 DOM 里 `.reveal` **有相当数量已带 `in` 类**（详见第八章新增小节） |
| **截图验证全绿，交付物却是坏的** | 截图脚本强制注入 `opacity:1!important`，把「空白页」缺陷掩盖了 | 截图通过≠交付合格。必须另做一次**不带注入**的 DOM dump，数 `.reveal` 的 `in` 类数量 |
| 评论接口 `/x/v2/reply/main` 取出来 `uname`/`message` **全是 None** | 该接口是**嵌套结构**（`member.uname` + `content.message`），而技能记载的扁平结构属于旧接口 `/x/v2/reply` | 写个 `norm()` 同时兼容两种形态；分页用旧接口更稳（`reply/main` 的 `next` 翻页常返回空） |
| Chrome `--dump-dom` 输出 0 字节，但 `Start-Process ... -RedirectStandardOutput` 就正常 | 除了 shell 路径问题，**file URL 用反斜杠也会静默失败** | URL 必须 `file:///` + 正斜杠（`$f -replace "\\\\","/"`）；`[Uri]::EscapeUriString` 对含反斜杠的路径同样不可靠 |
| `shot_section.py` 截图仍上半屏空白 | 脚本 QUIET 只注入 `.rv{opacity:1}`，而 guide 模板用的是 `.reveal` | 已修脚本为 `.rv,.reveal{...}`。用别的模板前先确认动画类名 |
| 自建校验报「ID 未绑定: __err」 | 探针元素是运行时 `createElement` + `.id =` 动态创建的，静态 HTML 里本来就没有 | 校验时把 `\.id\s*=\s*['"](\w+)['"]` 也收集为已定义 ID |
| grep DOM 判断「错误探针是否触发」，结果误判 | 探针源码里的字符串（如「脚本异常」）本身就在 `<script>` 中，dump 出来必然命中 | 查**元素是否存在**：`id="__err"` 是否出现在 DOM 里，而不是 grep 文案 |
| 软件教程类视频的术语一塌糊涂（UI 字段名全被听错） | ASR 按发音拟合，`Face Tracking`→「面补」、`Blendshapes Sets`→「blender set」 | **官方文档是术语权威**。WebSearch 找官方 release notes / 文档页，建「转写叫法 → 官方术语」对照表；抽帧读 UI 可作旁证 |

## 十、上架资料库（要分享 / 发链接时）

产物要**变成外链**时，走 `library` 技能，别用站点部署（站点部署是给有构建链或后端的项目的，单个 HTML 不适用）：

```bash
python "<library>/page/import_html.py" "<产物.html>"      # 省略 --file-name，自动从 <title> 取语义名
python "<library>/page/publish_page.py" --node-id "<node_block_id>"
```

两条硬规矩：

1. **导入前必须过图片托管自检**：`<img>` 的 `src` 不得残留第三方域名（`codebuddy` / `workbuddy` 域名的平台直链除外）。见 6.2。
2. **发布后回复要给两条链接**：编辑态（`workbuddy.cn/space/d/...`，可协作编辑）与发布态（`workbuddy.link/...`，直接发人看）。
   只给发布链接是交付不完整 —— 用户之后要改还得自己找入口。

导入产物落在用户个人空间，无需二次确认；目标若是团队空间，先说明再动手。
