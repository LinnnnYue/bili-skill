#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bili · opus 图文构建器

把 opus_data.json 注入 bili_opus.html，产出单文件 HTML 图文页。

两种打包形态（对应主上 2026-10-29 的裁定）：
  · 本地版（默认）    图片走相对路径，体积小，适合自己阅读
  · 单文件版 --embed  图片转 base64 内联，可独立转发，体积显著变大

  技能在交付前 **应主动询问宿主/用户** 要哪一种，并把本脚本报出的两个体积一起给出：
  ```
  python build_opus.py --data opus_data.json --template .../bili_opus.html \
      --out out.html [--embed]
  ```
  脚本会同时算出两种形态的体积，供 agent 直接引用，不必自己估。

退出码：0 成功 / 2 参数或数据错误 / 3 引用的图片缺失（--embed 时）
"""
import argparse
import base64
import json
import mimetypes
import re
import sys
from pathlib import Path


def human(n: int) -> str:
    return f"{n/1024:.1f} KB" if n < 1024 * 1024 else f"{n/1024/1024:.2f} MB"


def iter_imgs(data: dict):
    for sec in data.get("sections", []):
        for b in sec.get("blocks", []):
            if b.get("type") == "img" and b.get("src"):
                yield b


def main() -> int:
    ap = argparse.ArgumentParser(description="opus 图文 → 单文件 HTML")
    ap.add_argument("--data", required=True, type=Path, help="opus_data.json")
    ap.add_argument("--template", required=True, type=Path, help="bili_opus.html")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base-dir", type=Path, default=None,
                    help="解析图片相对路径的基准目录（默认=data 所在目录）")
    ap.add_argument("--embed", action="store_true",
                    help="图片转 base64 内联，产出可独立转发的单文件版")
    a = ap.parse_args()

    if not a.data.exists():
        print(f"[err] 数据不存在: {a.data}", file=sys.stderr)
        return 2
    if not a.template.exists():
        print(f"[err] 模板不存在: {a.template}", file=sys.stderr)
        return 2

    data = json.loads(a.data.read_text(encoding="utf-8"))
    if "meta" not in data or "sections" not in data:
        print("[err] opus_data.json 必须含 meta 与 sections", file=sys.stderr)
        return 2

    base = a.base_dir or a.data.parent
    imgs = list(iter_imgs(data))
    assets_bytes = 0
    missing = []
    for b in imgs:
        p = (base / b["src"]).resolve()
        if p.exists():
            assets_bytes += p.stat().st_size
        else:
            missing.append(b["src"])

    if a.embed:
        if missing:
            print(f"[err] --embed 需要全部图片就位，缺 {len(missing)} 张：{missing}", file=sys.stderr)
            return 3
        for b in imgs:
            p = (base / b["src"]).resolve()
            mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
            b["src"] = f"data:{mime};base64,{b64}"

    tpl = a.template.read_text(encoding="utf-8")
    title = (data.get("meta") or {}).get("title", "图文")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if "__DATA__" not in tpl:
        print("[err] 模板缺少 __DATA__ 占位符", file=sys.stderr)
        return 2
    html = tpl.replace("__TITLE__", title).replace("__DATA__", payload)

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html, encoding="utf-8")

    out_bytes = len(html.encode("utf-8"))
    # 另一种形态的估算：base64 约为原始字节的 1.37 倍
    if a.embed:
        local_est = out_bytes - int(assets_bytes * 1.37)
        print(f"OK {a.out} · 单文件版 {human(out_bytes)} · 图 {len(imgs)} 张已内联")
        print(f"     若改走本地版可缩到约 {human(max(local_est, 0))}（图片外链 {human(assets_bytes)}）")
    else:
        single_est = out_bytes + int(assets_bytes * 1.37)
        print(f"OK {a.out} · 本地版 {human(out_bytes)} · 图 {len(imgs)} 张外链 {human(assets_bytes)}")
        print(f"     若需单文件转发，加 --embed 约 {human(single_est)}（+{human(single_est - out_bytes)}）")
    if missing:
        print(f"[warn] 有 {len(missing)} 张图未找到（报告里会显示断图）：{missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
