"""把 B站 seg.so protobuf 弹幕转成经典 XML（<d p="t,mode,size,color,ctime,pool,rowid,uid">text</d>）。

用途：comment.bilibili.com/xml.bilibili.com/{cid}.xml 现已返回反爬 HTML，
只有 api.bilibili.com/x/v2/dm/web/seg.so（protobuf）可用，而
bili-deep-report 的 parse_danmaku.py 只吃经典 XML。本脚本补这道缺口。

用法：python dm_pb2xml.py <seg.so文件> <输出.xml>
"""
import sys
from pathlib import Path


def read_varint(buf: bytes, i: int):
    shift = 0
    val = 0
    while True:
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not (b & 0x80):
            return val, i
        shift += 7


def walk(buf: bytes, start: int, end: int):
    """遍历一段 protobuf，返回 [(field_no, wire_type, value_bytes_or_int)]。"""
    i = start
    out = []
    while i < end:
        key, i = read_varint(buf, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            v, i = read_varint(buf, i)
            out.append((field, wire, v))
        elif wire == 2:
            ln, i = read_varint(buf, i)
            out.append((field, wire, buf[i:i + ln]))
            i += ln
        elif wire == 5:
            out.append((field, wire, buf[i:i + 4]))
            i += 4
        elif wire == 1:
            out.append((field, wire, buf[i:i + 8]))
            i += 8
        else:
            break
    return out


def parse_elems(blob: bytes):
    """DanmakuElem 真实字段布局（B站 proto）：
    1=id 2=progress(ms) 3=mode 4=fontsize 5=color 6=midHash 7=content 8=ctime 11=pool 12=idStr
    （初版误按 4=content/6=progress 解出 0 条，已订正）
    """
    elems = []
    for field, wire, val in walk(blob, 0, len(blob)):
        if field == 1 and wire == 2:
            d = {"id": 0, "progress": 0, "mode": 1, "fontsize": 25,
                 "color": 16777215, "content": "", "ctime": 0, "pool": 0}
            for f2, w2, v2 in walk(val, 0, len(val)):
                if w2 == 0:
                    if f2 == 1:
                        d["id"] = v2
                    elif f2 == 2:
                        d["progress"] = v2
                    elif f2 == 3:
                        d["mode"] = v2
                    elif f2 == 4:
                        d["fontsize"] = v2
                    elif f2 == 5:
                        d["color"] = v2
                    elif f2 == 8:
                        d["ctime"] = v2
                    elif f2 == 11:
                        d["pool"] = v2
                elif f2 == 7 and w2 == 2:
                    d["content"] = v2.decode("utf-8", "replace")
            if d["content"]:
                elems.append(d)
    return elems


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    blob = src.read_bytes()
    elems = parse_elems(blob)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<i>"]
    for d in elems:
        t = d["progress"] / 1000.0
        mode = 1 if d["pool"] == 0 else 4
        p = f"{t:.3f},{mode},{d['fontsize']},{d['color']},{d['ctime']},{d['pool']},0,{d['id']}"
        text = (d["content"].replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))
        lines.append(f'<d p="{p}">{text}</d>')
    lines.append("</i>")
    dst.write_text("\n".join(lines), encoding="utf-8")
    print(f"danmaku elements: {len(elems)} -> {dst}")


if __name__ == "__main__":
    main()
