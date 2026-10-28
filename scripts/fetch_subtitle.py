import json, os, sys, urllib.request, urllib.parse

BV, CID = sys.argv[1], sys.argv[2]
COOKIE = os.environ.get("BILI_COOKIE", "")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": "https://www.bilibili.com/", "Cookie": COOKIE})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")

# 1) 取 player 信息拿字幕列表
info = json.loads(get(f"https://api.bilibili.com/x/player/wbi/v2?bvid={BV}&cid={CID}"))
subs = info.get("data", {}).get("subtitle", {}).get("subtitles", [])
print("字幕轨:", [(s["lan"], s["lan_doc"]) for s in subs])
zh = [s for s in subs if s["lan"].startswith("ai-zh")]
assert zh, "无 ai-zh 字幕轨"
url = zh[0]["subtitle_url"]
if url.startswith("//"):
    url = "https:" + url
body = json.loads(get(url))
segs = body.get("body", [])
print("片段数:", len(segs))
os.makedirs("tmp_yys/transcript", exist_ok=True)
json.dump(segs, open("tmp_yys/transcript/subtitle_raw.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def fmt(t):
    m, s = divmod(int(t), 60)
    return f"{m:02d}:{s:02d}"

lines = [f"[{fmt(s['from'])}] {s['content'].strip()}" for s in segs if s.get("content", "").strip()]
open("tmp_yys/transcript/timeline.txt", "w", encoding="utf-8").write("\n".join(lines))
open("tmp_yys/transcript/full.txt", "w", encoding="utf-8").write("".join(s["content"].strip() for s in segs))
print("总字数:", sum(len(s["content"]) for s in segs))
print("首段:", lines[0][:120] if lines else "EMPTY")
print("末段:", lines[-1][:120] if lines else "")
