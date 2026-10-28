"""Probe Bilibili player endpoint for subtitle tracks using a logged-in cookie."""
import json
import os
import sys
import urllib.parse
import urllib.request

BVID = sys.argv[1] if len(sys.argv) > 1 else "BV1Gx7n6ZEv8"
CID = sys.argv[2] if len(sys.argv) > 2 else "39446842444"
COOKIE = os.environ.get("BILI_COOKIE", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": f"https://www.bilibili.com/video/{BVID}/",
    "Origin": "https://www.bilibili.com",
    "Cookie": COOKIE,
}


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    url = f"https://api.bilibili.com/x/player/wbi/v2?bvid={BVID}&cid={CID}"
    data = get(url)
    print("code:", data.get("code"), "message:", data.get("message"))
    payload = data.get("data") or {}
    sub = payload.get("subtitle") or {}
    print("allow_submit:", sub.get("allow_submit"))
    print("subtitles:", json.dumps(sub.get("subtitles"), ensure_ascii=False, indent=2))
    print("view_points:", len((payload.get("view_points") or [])))
    print("is_owner:", payload.get("is_owner"), "login_mid:", (payload.get("login_mid") or 0))


if __name__ == "__main__":
    main()
