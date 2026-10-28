#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用浏览器 CDP Cookie 提取器。

从已开启调试端口（--remote-debugging-port=9222）的 Chromium 内核浏览器里，
把目标站点的明文会话 Cookie 取出来，供命令行工具/下游脚本使用。
支持 Chrome / Edge / 星愿浏览器(Twinkstar) 等。
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

import websocket


def list_page_targets(port: int):
    url = f"http://127.0.0.1:{port}/json/list"
    with urllib.request.urlopen(url, timeout=5) as r:
        return json.loads(r.read().decode("utf-8"))


def get_cookies_from_target(ws_url: str, origin: str):
    ws = websocket.create_connection(
        ws_url,
        header=[f"Origin: {origin}"],
        timeout=8,
    )
    ws.send(json.dumps({"id": 1, "method": "Network.enable", "params": {}}))
    ws.recv()
    ws.send(json.dumps({"id": 2, "method": "Network.getCookies", "params": {}}))
    raw = ws.recv()
    ws.close()
    resp = json.loads(raw)
    return resp.get("result", {}).get("cookies", [])


def extract_cookies(domain: str, port: int = 9222, verbose: bool = False):
    origin = f"http://127.0.0.1:{port}"
    targets = list_page_targets(port)
    collected = {}

    for t in targets:
        if t.get("type") != "page":
            continue
        url = t.get("url", "")
        if domain not in url:
            continue
        ws_url = t.get("webSocketDebuggerUrl")
        if not ws_url:
            continue
        try:
            for c in get_cookies_from_target(ws_url, origin):
                cdom = c.get("domain", "")
                if domain not in cdom:
                    continue
                key = (c.get("name"), cdom)
                collected[key] = c
        except Exception as e:
            if verbose:
                print(f"[warn] target {url[:60]}... fail: {e}", file=sys.stderr)

    return list(collected.values())


def format_header(cookies: list) -> str:
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def format_netscape(cookies: list) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    for c in cookies:
        domain = c.get("domain", "")
        flag = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure") else "FALSE"
        # getCookies 不返回 expires；按会话 Cookie 处理
        exp = str(int(c.get("expires", 0))) if c.get("expires") else "0"
        lines.append("\t".join([domain, flag, path, secure, exp, c["name"], c["value"]]))
    return "\n".join(lines)


def parse_cookie_header(text: str) -> dict:
    out = {}
    for part in text.strip().split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main():
    p = argparse.ArgumentParser(description="从 Chromium 浏览器 CDP 提取目标站点 Cookie")
    p.add_argument("--domain", required=True, help="目标域名，如 bilibili.com / booth.pm")
    p.add_argument("--port", type=int, default=9222, help="调试端口（默认 9222）")
    p.add_argument("--out", help="输出文件路径；省略则 stdout")
    p.add_argument("--format", choices=["header", "netscape"], default="header",
                   help="输出格式：header 单行 k=v 串 或 netscape cookies.txt")
    p.add_argument("--verbose", action="store_true", help="打印调试信息")
    args = p.parse_args()

    cookies = extract_cookies(args.domain, args.port, args.verbose)
    if not cookies:
        print(f"[error] 未提取到 domain 含 '{args.domain}' 的 Cookie。", file=sys.stderr)
        print("        请检查：1) 浏览器已带 --remote-debugging-port=9222 --remote-allow-origins=* 启动",
              file=sys.stderr)
        print("              2) 目标站点标签页已打开且处于登录态", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        print(f"[info] 提取到 {len(cookies)} 条 {args.domain} Cookie:", file=sys.stderr)
        for c in cookies:
            print(f"       {c['name']} (domain={c.get('domain')})", file=sys.stderr)

    if args.format == "netscape":
        text = format_netscape(cookies)
    else:
        text = format_header(cookies)

    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"[ok] 已写入 {args.out}：{len(cookies)} 条 {args.domain} Cookie")
    else:
        print(text)


if __name__ == "__main__":
    main()
