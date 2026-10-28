# bili 技能 · 本轮 bug 修复报告

日期：2026-10-29
修复者：DSH（Raphael）
触发场景：实际跑 BV1A8H56vEHi 全流程时暴露

---

## 一、修复清单

### BUG-1 · 逐句稿静默变空态（严重）

**现象**：传入 `--transcript tmp_bili_extract/transcript/BV1A8H56vEHi.txt` 后，报告第 07 节只剩 30 字空态文案，538 句逐句稿全部丢失。页面不报错。

**根因**：`scripts/build_report.py` 的 `parse_transcript()` 只认一种格式：

```python
m = re.match(r"\[(\d{2}:\d{2}(?::\d{2})?)\]\s*(.*)", line.strip())
```

即 `[MM:SS] 文本`。而 `scripts/transcribe.py` 产出的 `.txt` 是**纯文本每行一句，无时间戳**，`.srt` 是标准 SRT。两者都不匹配 → rows 为空 → 模板走空态分支。

**修法**：扩展为自动识别三种格式：

| 格式 | 来源 | 处理 |
|---|---|---|
| `[MM:SS] 文本` | 简化稿 / `frame_ocr.py` | 原逻辑保留 |
| SRT（`HH:MM:SS,mmm --> ...`） | `transcribe.py` 的 `.srt` | 新增解析 + 时间码归一化 `_mmss()` |
| 纯文本（一行一句） | `transcribe.py` 的 `.txt` | 新增兜底，`t` 置空但**句子保留** |

新增 `_mmss()`：`00:01:23,456` → `01:23`；超 1 小时保留 `HH:MM:SS`。

**验证**：同一份素材，修复前 07 节 30 字（空态）；修复后 9520 字 / 539 行。产物 212 KB → 241 KB。

**影响面**：任何走 ASR 路线的视频都会中招（字幕缺失 → ASR → .txt/.srt → 逐句稿丢失）。这是主线路径，不是边缘情况。

---

### BUG-2 · 结论粗体被当字面文本显示（中）

**现象**：`narrative.json` 的 `call` 字段按 SKILL.md 契约写入 `<b>可沉淀的工作流</b>`，页面上显示出字面的 `<b>` `</b>` 标签。

**根因**：`templates/bili_report_v4.html` 第 912 行用 `esc()` 全量转义：

```js
$('call').innerHTML = D.call ? esc(D.call) : '…';
```

而 SKILL.md 明确写「call：一句话结论（可含粗体强调）」——**契约与实现不一致**。

**修法**：新增 `richEsc()`，只放行 `<b>`/`<strong>`，其余标签一律仍被转义（不放开 XSS 面）：

```js
const richEsc = s => esc(s).replace(/&lt;(b|strong)&gt;([\s\S]*?)&lt;\/\1&gt;/g, '<$1>$2</$1>');
```

并应用到 5 个渲染点：`call` / `points.text` / `env_fit.summary` / `env_fit.reasons+requirements` / `env_fit.unknown` / `note_sections.items.text`。

**安全验证**：

```
输入: 一套<b>可沉淀的工作流</b>：<script>alert(1)</script>
输出: 一套<b>可沉淀的工作流</b>：&lt;script&gt;alert(1)&lt;/script&gt;
```

粗体生效，脚本仍被转义。

---

### BUG-3 · 模板 JS 语法改动需逐块校验（流程补强）

本轮两次改了模板 JS，两次都是靠浏览器打开才发现问题。补上**提交前强制校验**流程：

```bash
node --check <每个 <script> 块>
```

本轮 4 个 script 块全部通过（356 / 632 / 17526 / 5591 字符）。

---

## 二、一个必须记录的运维事实

**技能目录有双向同步，会覆盖手改。**

本轮修复过程中发现：对 `C:\Users\19388\.dsh\skills\bili` 的两次写入，事后都被回退（mtime 回到 `18:45`/`18:52`，内容里 `richEsc` 与 `_mmss` 消失）。主源 `G:\Lin_File\Documents\Skills\bili` 同样不含这两处改动。

**这意味着**：
1. 上一轮交付的报告是**修复生效时**生成的（含 richEsc、553 条时间戳数据），交付物本身没问题；
2. 但**技能源码已被回退**——下次跑同类视频，BUG-1 会原样复现。

**结论**：修复必须落到主源仓库 `G:\Lin_File\Documents\Skills\bili` 并提交，否则会被同步覆盖。这也是为什么需要这份报告 + 一次真正的 git commit。

---

## 三、待办

- [ ] 把 BUG-1 / BUG-2 的修复重新应用到主源并 `git commit`
- [ ] 决定是否 push 到 `github.com/LinnnnYue/bili-skill`（远端已配好，分支 main）
- [ ] 在 SKILL.md 补一句：`--transcript` 支持 .txt / .srt / 方括号三种格式

---

## 四、证据

| 项 | 修复前 | 修复后 |
|---|---|---|
| 07 逐句稿字数 | 30（空态） | 9520 |
| 07 逐句稿行数 | 0 | 539 |
| 产物大小 | 212,430 B | 241,637 B |
| 结论粗体 | 字面显示 | 正常渲染 |
| `<script>` 转义 | — | 仍转义 ✔ |
| 模板 script 语法 | 未校验 | 4/4 通过 |
