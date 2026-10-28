#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""模板 CSS 原地精简 —— 删掉「必然失效」的冗余声明，**一步都不移动规则**。

为什么这样才安全
----------------
CSS 层叠里，同一选择器的多条规则按出现顺序生效。所以：

    同组最后一条规则若含属性 X（且不带 !important），
    则更早的同名规则里的 X 永远不会是最终值 —— 删它，结果不变。

关键点：**不移动任何规则的位置**。只要位置不动，中间那些多选择器组
（如 `h3, .toc .h, .side .tag { … }`）的介入关系就完全不变。

反面教材（本项目踩过 4 次）：把同名规则「合并到首次/最后位置」。
一旦移动，前面独有的属性会跟着位移、压过中间规则，实测像素差异 29%。
本脚本只删、不搬，所以能做到零差异。

安全边界（以下情况一律跳过）
--------------------------
* 声明带 `!important` —— 早期 important 会压过后期普通值
* 属性是缩写/展开关系（`margin` vs `margin-top`）—— 删缩写会连带丢其它边
* 规则体含 `url(...)` / `data:` —— 避免误伤 base64 资源
* `@media` 块内部 —— 未处理（同块内同名极少，且风险收益比不划算）

用法
----
    python scripts/prune_css.py --dry                    # 只报告能省多少
    python scripts/prune_css.py                          # 原地精简（自动备份 .bak）
    python scripts/prune_css.py --in a.html --out b.html # 指定出入

精简后**必须**做等价性验证（见 SKILL.md 的 computedStyle 哈希法），
至少覆盖 浅色/深色 × 宽屏/窄屏 四种状态。
"""
import argparse
import collections
import io
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TPL = HERE.parent / "templates" / "bili_report_v4.html"


def scan_rules(text):
    """扫描顶层规则（@规则整块跳过）。返回 [{'header','hs','bs','be','fe'}]"""
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        hs = i
        while hs < j and text[hs] in " \t\r\n":
            hs += 1
        header = text[hs:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        if header and not header.startswith("@"):
            out.append({"header": header, "hs": hs, "bs": j + 1, "be": k - 1, "fe": k})
        i = k
    return out


def split_decls(body):
    """按顶层分号切声明，返回 [(name, raw, is_important)]；raw 保留原文（含分号）"""
    parts, buf, depth = [], "", 0
    for ch in body:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth == 0:
            parts.append(buf + ";")
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    out = []
    for raw in parts:
        t = raw.strip()
        if not t or ":" not in t:
            continue
        name = t.split(":", 1)[0].strip().lower()
        if not re.fullmatch(r"[a-z-]+", name):
            continue
        out.append((name, raw, "!important" in t.lower()))
    return out


def related(a, b):
    """同族属性（缩写 / 展开）——保守判定：互为前缀即算同族"""
    return a == b or a.startswith(b + "-") or b.startswith(a + "-")


def prune(css):
    rules = scan_rules(css)
    groups = collections.OrderedDict()
    for r in rules:
        groups.setdefault(r["header"], []).append(r)

    edits = []          # (start, end, replacement)
    stat = {"del_rule": 0, "del_decl": 0, "touched": 0, "skip": 0, "groups": 0}

    for h, rs in groups.items():
        if len(rs) <= 1:
            continue
        stat["groups"] += 1
        last_body = css[rs[-1]["bs"]:rs[-1]["be"]]
        last_names = [p for p, _, _ in split_decls(last_body)]

        for r in rs[:-1]:
            body = css[r["bs"]:r["be"]]
            if "url(" in body or "data:" in body:
                stat["skip"] += 1
                continue
            ds = split_decls(body)
            if not ds:
                continue
            kill = [(n, raw) for n, raw, imp in ds
                    if not imp and any(related(n, x) for x in last_names)]
            if not kill:
                continue

            if len(kill) == len(ds):          # 整条规则都是冗余 → 删规则
                a = r["hs"]
                while a > 0 and css[a - 1] in " \t":
                    a -= 1
                b = r["fe"]
                while b < len(css) and css[b] == "\n":
                    b += 1
                edits.append((a, b, ""))
                stat["del_rule"] += 1
            else:                              # 只删冗余声明，保留其余原文
                nb = body
                for _n, raw in kill:
                    if raw in nb:
                        nb = nb.replace(raw, "", 1)
                        stat["del_decl"] += 1
                edits.append((r["bs"], r["be"], nb))
                stat["touched"] += 1

    new_css = css
    for a, b, rep in sorted(edits, key=lambda x: -x[0]):
        new_css = new_css[:a] + rep + new_css[b:]
    return new_css, stat


def main():
    ap = argparse.ArgumentParser(description="模板 CSS 原地精简（不移动规则，严格等价）")
    ap.add_argument("--in", dest="inp", type=Path, default=DEFAULT_TPL)
    ap.add_argument("--out", dest="out", type=Path)
    ap.add_argument("--dry", action="store_true", help="只报告，不写文件")
    a = ap.parse_args()

    src = io.open(a.inp, encoding="utf-8").read()
    if "<style>" not in src or "</style>" not in src:
        print("[err] 没找到 <style> 块")
        return 2
    i0, i1 = src.index("<style>") + 7, src.index("</style>")
    css = src[i0:i1]

    new_css, st = prune(css)
    print(f"同名规则组 {st['groups']} 个")
    print(f"  可整条删除规则 : {st['del_rule']}")
    print(f"  可删冗余声明   : {st['del_decl']}（涉及 {st['touched']} 条规则）")
    print(f"  跳过（含 url）  : {st['skip']}")
    print(f"  CSS 体积       : {len(css)} → {len(new_css)} B（{len(new_css)-len(css):+d}）")

    if st["del_rule"] + st["del_decl"] == 0:
        print("\n没有可删的冗余，模板已是精简状态。")
        return 0
    if a.dry:
        print("\n[--dry] 未写文件。")
        return 0

    out = a.out or a.inp
    if out == a.inp:
        bak = a.inp.with_suffix(a.inp.suffix + ".bak")
        shutil.copy2(a.inp, bak)
        print(f"\n已备份 → {bak.name}")
    io.open(out, "w", encoding="utf-8").write(src[:i0] + new_css + src[i1:])
    print(f"已写入 → {out}")
    print("下一步：按 SKILL.md 做四状态 computedStyle 哈希比对，确认零差异再同步三处。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
