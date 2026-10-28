"""Fetch Bilibili official AI conclusion (video summary) with WBI signing."""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

COOKIE = os.environ.get("BILI_COOKIE", "")
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Cookie": COOKIE,
}


def get_json(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> str:
    mixin_key = get_mixin_key(img_key + sub_key)
    params = dict(params)
    params["wts"] = int(time.time())
    params = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in params.items()}
    query = urllib.parse.urlencode(sorted(params.items()))
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return urllib.parse.urlencode(sorted(params.items()))


def main():
    bvid, cid, up_mid = sys.argv[1], sys.argv[2], sys.argv[3]
    nav = get_json("https://api.bilibili.com/x/web-interface/nav")
    wbi = nav["data"]["wbi_img"]
    img_key = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    qs = enc_wbi({"bvid": bvid, "cid": cid, "up_mid": up_mid}, img_key, sub_key)
    url = f"https://api.bilibili.com/x/web-interface/view/conclusion/get?{qs}"
    data = get_json(url)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
