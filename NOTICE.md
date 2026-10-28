# 第三方资源与许可声明

本仓库**代码**以 MIT 许可发布（见 `LICENSE`）。但仓库内含第三方资源与外部内容，
它们各自的授权与归属如下。

---

## 内嵌字体

`templates/bili_report_v4.html` 与 `templates/bili_opus.html` 以 base64 内嵌了两款字体，
目的是让产出的报告**单文件离线可用**（不联网也不掉字体）。

| 字体 | 用途 | 许可 | 版权 |
|---|---|---|---|
| **Anton** | 章节编号、指标数字、巨型水印等纯拉丁/数字元素 | SIL Open Font License 1.1 | © Vernon Adams |
| **Archivo**（可变字体，latin 子集） | 数字的字重呼吸 | SIL Open Font License 1.1 | © Omnibus-Type |

SIL OFL 1.1 允许嵌入、再分发与商用，条件是**保留版权声明**（本文件即为该声明），
且不得单独售卖字体本身。许可证全文：<https://scripts.sil.org/OFL>

如果你要替换字体，请确保新字体同样允许嵌入与再分发。

---

## 视频内容与元数据

本工具抓取的视频标题、简介、评论、弹幕、字幕、画面文字，
**版权归原视频作者与哔哩哔哩所有**。

- 生成的报告仅供**个人学习、研究与评论**使用
- 公开转载报告时，请注明原视频链接与作者
- 不要用本工具批量抓取、二次分发他人内容或用于商业用途

---

## 数据来源

| 来源 | 说明 |
|---|---|
| B 站 Web 接口 | `api.bilibili.com` 公开接口（部分需登录态 Cookie） |
| 弹幕 | `x/v1/dm/list.so`（XML）或 `x/v2/dm/web/seg.so`（protobuf） |
| 语音转写 | 本地 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)（MIT） |
| 画面 OCR | 本地 [RapidOCR](https://github.com/RapidAI/RapidOCR)（Apache-2.0） |
| 音视频下载 | [yt-dlp](https://github.com/yt-dlp/yt-dlp)（Unlicense） |

抓取行为请遵守哔哩哔哩用户协议与相关法律法规。接口随时可能变更，
本项目不保证长期可用。
