# bili — B 站视频一站式解析

把一支 B 站视频，变成一份**能直接读、能转发、能检索**的东西。

不是"下个字幕"那种单点工具，而是一条完整流水线：取数 → 补全信息 → 写叙事 → 出双产物。

---

## 它产出什么

| 产物 | 形态 | 用途 |
|---|---|---|
| **主产物** | 单文件 HTML（离线、可双击打开、可转发） | 8 板块长报告，视觉强，适合一眼看完 + 转发 |
| **副产物**（可选） | 同源 Markdown | 可检索、可二次编辑、可入库。默认不出，需要时说一声 |

两者**同源生成**（同一份叙事 + 同一份数据），不会各写一套。

报告结构：三十秒结论 / 适配度评估 / 学习笔记 / 数据画像 / 评论区 / 弹幕 / 逐句稿或画面文字 / 证据链。

---

## 快速开始

```bash
# 0) 先体检（强烈建议，尤其换机器 / 第一次用）
python scripts/check_env.py

# 1) 取元数据 + 评论
python scripts/extract_bilibili.py BV1xxxxxxxxx --out tmp_bili_extract --comments

# 2) 试字幕（有公开字幕轨就省掉 ASR）
python scripts/bili_probe.py BV1xxxxxxxxx <cid>

# 3) 弹幕（先试 list.so，拿不到再退 seg.so）
curl -s --compressed -A "Mozilla/5.0" -H "Referer: https://www.bilibili.com/" \
  "https://api.bilibili.com/x/v1/dm/list.so?oid=<cid>" -o tmp_bili_extract/danmaku2.xml

# 4) 拿文本：二选一
#    4a 有语音 → 下音频 + ASR
yt-dlp -f bestaudio --add-header "Referer: https://www.bilibili.com/" \
       -o "bili_audio/%(id)s.%(ext)s" "https://www.bilibili.com/video/BV1xxxxxxxxx"
python scripts/transcribe.py bili_audio/BV1xxxxxxxxx.m4a tmp_bili_extract/transcript

#    4b 无人声（宣传片/演示片）→ 下视频 + 画面 OCR
yt-dlp -f "bestvideo[height<=720]" --add-header "Referer: https://www.bilibili.com/" \
       -o "bili_video/%(id)s.%(ext)s" "https://www.bilibili.com/video/BV1xxxxxxxxx"
python scripts/frame_ocr.py bili_video/BV1xxxxxxxxx.mp4 --out tmp_bili_extract/frames_ocr.json

# 5) 聚合
python scripts/build_report_data.py --src tmp_bili_extract

# 6) 写叙事 narrative.json（这一步由 agent 完成，见 SKILL.md）
# 7) 出双产物
python scripts/build_report.py --data tmp_bili_extract/report_data.json \
       --narrative narrative.json --out report.html --transcript tmp_bili_extract/transcript_ts.txt
python scripts/build_note_md.py --data tmp_bili_extract/report_data.json \
       --narrative narrative.json --out note.md
```

---

## 依赖

**核心（缺了完全跑不了）**：`requests`、`ffmpeg`、`ffprobe`、`yt-dlp`

```bash
pip install -r requirements.txt          # requests
pip install -r requirements-ocr.txt      # 画面 OCR（rapidocr + Pillow）
pip install -r requirements-asr.txt      # 语音转写（faster-whisper + zhconv）
```

外部命令：`ffmpeg` / `ffprobe`（[官方下载](https://ffmpeg.org) 或 `winget install Gyan.FFmpeg`）、`yt-dlp`（`pip install yt-dlp`）。

**随时体检**：

```bash
python scripts/check_env.py           # 只缺核心项才返回 1
python scripts/check_env.py --strict  # 缺任何功能项都返回 1（CI 用）
```

自检会逐项打印「有什么 / 缺什么 / 缺了会怎样 / 怎么装」。

---

## 目录结构

```
bili/
├── SKILL.md                 # 给 agent 的执行手册（流水线 / 数据契约 / 踩坑）
├── README.md                # 你在看的这份（给人看）
├── LICENSE                  # MIT
├── NOTICE.md                # 第三方字体与内容归属
├── requirements*.txt        # 三档依赖：核心 / OCR / ASR
├── scripts/
│   │  ── 核心（跑通主流程只需要这 11 个）──
│   ├── check_env.py         # 环境自检
│   ├── prepublish_check.py  # 发布前自检（凭证 / 个人路径）
│   ├── extract_bilibili.py  # 元数据 + 评论
│   ├── bili_probe.py        # 字幕轨探测
│   ├── transcribe.py        # 语音转写（唯一 ASR 入口）
│   ├── frame_ocr.py         # 画面文字提取（无人声视频）
│   ├── dm_pb2xml.py         # 弹幕 protobuf → XML
│   ├── build_report_data.py # 聚合数据
│   ├── build_report.py      # 数据 + 叙事 → HTML
│   ├── build_note_md.py     # 同源 → Markdown
│   ├── build_opus.py        # 图文（opus）分支
│   ├── prune_css.py         # 模板 CSS 精简（改模板后用）
│   │  ── 可选 / 历史（按需查阅，主流程不依赖）──
│   └── …                    # bili_video.py、analyze_comments.py、extract_bilibili_opus.py 等
├── templates/
│   ├── bili_report_v4.html  # 报告模板（唯一入口，白名单强制）
│   └── bili_opus.html       # 图文模板（含灯箱）
└── references/              # 历史文档与接口笔记（仅供溯源，勿照做）
```

> `scripts/` 里脚本多于主流程需要的——这是融合四个旧技能留下的家底。
> 上面「核心」11 个是主链路，其余属可选能力或历史产物，**不要按名字猜用法**，
> 以 `SKILL.md` 的流水线为准。

---

## 已知限制（不隐瞒）

- **无人声视频靠画面 OCR**：艺术字/装饰字会认错（如「任务队列」可能识别成「任努认列」）。OCR 用于**提取线索**，写进正文前需结合上下文判断。
- **弹幕端点不稳定**：`list.so` 与 `seg.so` 都可能对某些视频失效，脚本按「先 list 后退 seg」处理，仍可能 0 条。
- **评论/弹幕有抽样上限**：报告里的条数是「实际取到」的数量，不是视频总量。
- **叙事由 agent 撰写**：脚本只供数据。同一份数据不同人写，报告质量会差很多。
- **CSS 不做自动合并**：模板里的同名规则靠层叠生效，用脚本合并必然改变样式（实测三次全败）。改样式请人工按段重写。

---

## 许可

**代码：MIT**（见 `LICENSE`）——随便用、改、商用都行，保留版权声明即可。

但有两件事请注意：

1. **内嵌字体**是 SIL OFL 1.1（Anton / Archivo），允许嵌入与再分发，需保留版权声明
   —— 详见 `NOTICE.md`。
2. **视频内容版权归原作者与哔哩哔哩**。工具是 MIT，但你抓下来的标题、评论、弹幕、字幕不是。
   公开转载报告请注明原视频链接与作者；不要用它批量抓取或二次分发他人内容。

抓取行为请遵守哔哩哔哩用户协议与相关法律法规。

---

## 发布前自检

要把仓库推到公开平台，先跑：

```bash
python scripts/prepublish_check.py
```

它会扫三类东西，发现就拦下：

- **登录凭证**：B 站 Cookie（SESSDATA / bili_jct / DedeUserID）、各类 API Key、私钥
- **个人环境**：`C:/Users/<你>/`、`/home/<你>/` 这类绝对路径
- **不该提交的文件**：`cookies.txt`、`.env`、`*.pem`

`.gitignore` 已把 `cookies*.txt` / `cookie*.txt` / `*cookie*` 全挡掉
（`scripts/extract_cookies.py` 例外——脚本要发布，它产出的 cookie 文件不发布）。
