#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把报告数据层里内联的 base64 图片批量转为平台托管直链。

用途：报告要上架资料库 / 发链接分享时，内联 base64 会让 HTML 膨胀到数 MB
（首屏阻塞、移动端慢）。转直链后同内容 HTML 可从 2.8 MB 降到 128 KB。

关键设计——**改数据层，不改成品 HTML**：
    图片地址存在 report_data.json 的 media 字段里。直接对成品做字符串替换是下策，
    一旦再改模板重新注入，替换成果全丢。

用法：
    python host_media.py ../report_data.json
    python host_media.py ../report_data.json --key media --uploader "/path/to/upload_image.py"
    python host_media.py ../report_data.json --recover failed.json   # 从未成功的失败记录里回收 URL

注意（本脚本已处理，改代码时别改回去）：
    KS_IMAGE_UPLOAD_OK 与 JSON 之间是【空格】分隔，不是 TAB。
    按 "\\t" 切分会导致索引越界，被宽 except 吞成「失败」——曾因此把 60 张已成功的图全判为失败。
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys

DEFAULT_UPLOADER = (
    "D:/Lin_Agent/WorkBuddy/resources/app.asar.unpacked/resources/plugins/"
    "workbuddy-builtin/skills/library/manage/upload_image.py"
)


def parse_url(out: str):
    """从上传脚本输出里取直链。正则抓整段 JSON —— 分隔符是空格，不是 TAB。"""
    mo = re.search(r"KS_IMAGE_UPLOAD_OK\s+(\{.*\})", out)
    if mo:
        try:
            return json.loads(mo.group(1)).get("url")
        except Exception:
            pass
    mo2 = re.search(r"https://[^\s]+\.(?:webp|png|jpg|jpeg|gif|bmp|svg)", out)
    return mo2.group(0) if mo2 else None


def key_num(k):
    return int("".join(ch for ch in str(k) if ch.isdigit()) or 0)


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "")).strip("_")[:24]


def recover(failed_path, media, out_path):
    """从失败记录的 stdout 里回收已上传成功的 URL（避免重复上传产生孤儿对象）。"""
    failed = json.load(open(failed_path, encoding="utf-8"))
    n = 0
    for x in failed:
        u = parse_url(x.get("stdout", ""))
        if u and x.get("key") in media:
            media[x["key"]] = u
            n += 1
    print("从失败记录回收: %d / %d" % (n, len(failed)))
    json.dump(media, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data", help="report_data.json 路径")
    ap.add_argument("--key", default="media", help="图片字段名，默认 media")
    ap.add_argument("--uploader", default=DEFAULT_UPLOADER, help="upload_image.py 路径")
    ap.add_argument("--recover", help="只做回收：传入 failed.json，不重新上传")
    ap.add_argument("--tmp", default=None, help="临时 webp 目录，默认 <data目录>/tmp_host")
    args = ap.parse_args()

    d = json.load(open(args.data, encoding="utf-8"))
    media = d[args.key]

    if args.recover:
        out = os.path.join(os.path.dirname(os.path.abspath(args.data)), "_recovered.json")
        recover(args.recover, media, out)
        print("已写出:", out, "（确认无误后替换原 media 字段）")
        return

    # 反查图片键 → 实体名，让上传文件名可辨认（"01_雪御前.webp" 而非 "image1"）
    name_of = {}
    for s in d.get("saints", []):
        k = s.get("img_key")
        if k and k not in name_of:
            name_of[k] = s.get("name", "")

    tmp = args.tmp or os.path.join(os.path.dirname(os.path.abspath(args.data)), "tmp_host")
    os.makedirs(tmp, exist_ok=True)

    items = sorted(media.items(), key=lambda kv: key_num(kv[0]))
    print("待上传: %d" % len(items), flush=True)

    ok, failed = 0, []
    for i, (k, v) in enumerate(items, 1):
        if not (isinstance(v, str) and v.startswith("data:")):
            ok += 1
            continue  # 已是直链，跳过
        b64 = v.split(",", 1)[1]
        nm = safe(name_of.get(k, "")) or str(k)
        fp = os.path.join(tmp, "%02d_%s.webp" % (i, nm))
        if not os.path.exists(fp):
            with open(fp, "wb") as f:
                f.write(base64.b64decode(b64))
        r = subprocess.run([sys.executable, args.uploader, fp], capture_output=True)
        out = r.stdout.decode("utf-8", "replace")
        u = parse_url(out)
        if u:
            media[k] = u
            ok += 1
            print("[%2d/%d] %-10s %s OK" % (i, len(items), k, nm), flush=True)
        else:
            failed.append({"key": k, "name": nm, "file": fp,
                           "stdout": out[:400],
                           "stderr": r.stderr.decode("utf-8", "replace")[:400]})
            print("[%2d/%d] %-10s %s FAIL" % (i, len(items), k, nm), flush=True)

    shutil.copyfile(args.data, args.data + ".bak_inline")
    json.dump(d, open(args.data, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    if failed:
        fp = os.path.join(tmp, "failed.json")
        json.dump(failed, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n失败 %d 条，已记录到 %s（可用 --recover 回收）" % (len(failed), fp))
    print("完成 %d / %d   数据层体积: %.2f MB"
          % (ok, len(items), os.path.getsize(args.data) / 1024 / 1024))


if __name__ == "__main__":
    main()
