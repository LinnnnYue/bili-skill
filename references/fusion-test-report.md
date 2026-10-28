# 四路实测对照：BV1ZJpg6UE21《为了不再剪视频，我做了这个...》

- UP：riverisbuilding｜时长 103 秒｜2026-10-28 实测
- 目标：判定 4 个平行 B 站技能的真实产出能力，作为融合裁决依据

## 一、结果总表

| 技能 | 结果 | 产出物 | 实测细节 |
|---|---|---|---|
| bilibili-video-summarizer | ✅ 通 | `info.json` `transcript.txt` `transcript_full.txt` `summary.md` + 质量门禁 JSON | 无字幕自动 GPU ASR（cuda/float16）50 句；门禁 ok=true（字/分 209.7、繁体 0%、拉丁碎片 16.7%）；CDN 首连失败回落一次成功；全程约 1 分钟 |
| bili-note | ✅ 通 | 归档目录 + `评论全集.md` + `证据索引.jsonl`(191 行) + `评论全集.jsonl`(191 行) + `note_budget.json` | metadata/comments 均取到；`public_subtitle_tracks=0`（该视频无公开字幕轨）、`browser_ai_subtitles=SKIP`（需 CDP，属正常） |
| bilibili-subtitle-downloader | ❌ 暴毙 | 无 | `ImportError: cannot import name 'login_v2' from 'bilibili_api'`——库升级后该函数已删，脚本连启动都做不到 → **判定退役** |
| bili-deep-report | ⚠️→✅ | `report.html` 61,707 B（v2 模板） | **guide 模板 + report_data → 白屏**（JS `Cannot read properties of undefined`，底部红色探针）；换 v2 模板 → 渲染正常（标题/一句话结论/评论区 39 条/论坛记录/UP 动态）。且其 `build_report_data.py` 硬依赖 **bili-note** 产出的 `tmp_bili_extract/`——两技能存在隐藏耦合 |

## 二、本次实测暴露的三个真缺陷（已修）

1. **弹幕端点已死**：`comment.bilibili.com/xml.bilibili.com/{cid}.xml` 现返回反爬 HTML。
   可用：`api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid={cid}&segment_index=1`（protobuf，带 Cookie+Referer）。
   新增 `scripts/dm_pb2xml.py` 转经典 XML；DanmakuElem 字段号 **1=id 2=progress 3=mode
   4=fontsize 5=color 6=midHash 7=content 8=ctime 11=pool**（初版猜错 content/progress 位置，
   解析出 0 条）。本视频实测 3 条（"入股了"×1、"OptiFine（幻视）"×2）。
2. **模板与数据形状必须配对**：v2 ↔ report_data（8 键）；guide ↔ 结论数据链（terms/tiers/
   myths/dungeons/actions/verdict/nin/density/cmts）。`inject_report.py` 已改为**写盘前**校验
   缺键并打印症状提示，不再"写完文件才 KeyError 崩掉"。
3. **质量门禁误报**：未跑 ASR（`--no-asr`）时转写为空，门禁误判「字/分钟=0 异常」。
   已改为：空转写直接跳过探针（ok + skipped 标记）。

## 三、融合裁决（2026-10-28 执行）

- 新技能 **`bili`**（B 站一站式）：SKILL.md 只做路由；三条流水线
  ①速览（bili_video.py）②笔记（run_bili_note.py）③深度报告（extract→dm_pb2xml→
  build_report_data→inject_report→截图验证）；工艺细节移入 `references/`。
- 脚本 30 个、模板 2 套、references 4 份合并入 `bili`。
- 旧四技能**移入归档**（非删除，可回滚）：
  - `<你的工作目录>\.workbuddy\skills-archive\`
  - `<你的工作目录>\.dsh\skills-archive\`
  - `./archive/`
- 旧三份 SKILL.md 原文保留为 `bili/references/{deep-report,note,summarizer}.md`——41 KB/22 KB/18 KB
  的实战知识一字不丢。
