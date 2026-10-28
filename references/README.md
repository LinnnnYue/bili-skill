# references/ —— 历史文档与接口笔记

这个目录**不是**操作手册，`SKILL.md` 才是。这里放的是融合过程中的原始材料，留作溯源。

| 文件 | 是什么 | 现在还能用吗 |
|---|---|---|
| `bilibili-api-notes.md` | B 站接口笔记：各端点的参数、返回结构、已知坑 | **有用**。查接口细节时看它 |
| `deep-report.md` | 旧技能 `bili-deep-report` 的 SKILL.md 原文（41 KB） | 仅供参考。它的模板链已作废 |
| `note.md` | 旧技能 `bili-note` 的 SKILL.md 原文（22 KB） | 仅供参考。笔记流程已并入主流水线 |
| `summarizer.md` | 旧技能 `bilibili-video-summarizer` 的 SKILL.md 原文（18 KB） | 仅供参考。ASR 部分仍在用，但入口已变 `transcribe.py` |
| `fusion-test-report.md` | 四个旧技能在同一视频上的实测对照与缺陷清单 | 仅供参考。记录了为什么要融合 |

---

## 为什么保留这些

`bili` 是由四个旧技能融合而来：

```
bili-deep-report + bili-note + bilibili-video-summarizer + bilibili-subtitle-downloader
                              ↓  融合
                            bili
```

融合时承诺「旧文档一字不丢」——因为里面有些**踩坑记录**（接口字段、字幕登录态要求、
模板与数据配对关系）在新文档里未必写全，遇到怪问题时可能要靠它们溯源。

**但请只把 `SKILL.md` 当操作依据。** 上面三份旧文档描述的是已经不存在的脚本路径与流程，
照着做会失败。
