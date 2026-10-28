"""Transcribe a local audio file with faster-whisper (CPU int8) and write txt/srt/json."""
import json
import os
import sys
import time

from faster_whisper import WhisperModel

AUDIO = sys.argv[1]
OUTDIR = sys.argv[2] if len(sys.argv) > 2 else "tmp_bili_extract/transcript"
MODEL = os.environ.get("WHISPER_MODEL", "small")

os.makedirs(OUTDIR, exist_ok=True)
stem = os.path.splitext(os.path.basename(AUDIO))[0]


def _fmt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

from whisper_device import pick_and_prepare
_dev, _ct = pick_and_prepare(verbose=True)
if _dev == "cpu":
    print(f"[asr] loading model={MODEL} device=cpu compute=int8", flush=True)
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4)
else:
    print(f"[asr] loading model={MODEL} device=cuda compute=float16", flush=True)
    model = WhisperModel(MODEL, device="cuda", compute_type="float16")

print("[asr] transcribing...", flush=True)
t0 = time.time()
segments, info = model.transcribe(
    AUDIO,
    language="zh",
    beam_size=5,
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 500},
    condition_on_previous_text=False,
)

rows = []
with open(os.path.join(OUTDIR, f"{stem}.txt"), "w", encoding="utf-8") as ftxt, open(
    os.path.join(OUTDIR, f"{stem}.srt"), "w", encoding="utf-8"
) as fsrt:
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text:
            continue
        rows.append({"index": i, "start": round(seg.start, 2), "end": round(seg.end, 2), "text": text})
        ftxt.write(text + "\n")
        fsrt.write(f"{i}\n{_fmt(seg.start)} --> {_fmt(seg.end)}\n{text}\n\n")
        if i % 100 == 0:
            print(f"[asr] {i} segments elapsed={time.time() - t0:.0f}s", flush=True)


def _fmt(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


with open(os.path.join(OUTDIR, f"{stem}.json"), "w", encoding="utf-8") as f:
    json.dump({"audio": AUDIO, "model": MODEL, "segments": rows}, f, ensure_ascii=False, indent=1)

total_chars = sum(len(r["text"]) for r in rows)
print(f"[asr] done segments={len(rows)} chars={total_chars} elapsed={time.time() - t0:.0f}s", flush=True)

# 转出 0 段不等于「成功」——多半是无人声（宣传片 / 演示片 / 纯 BGM），
# 这类视频的信息全在画面上，必须转画面 OCR，否则报告会被迫只靠评论撑着。
if not rows:
    print("[asr] 0 段：本视频可能没有语音轨（纯演示 / BGM）。"
          "画面信息请走 OCR：", flush=True)
    print("      yt-dlp -f \"bestvideo[height<=720]\" "
          "--add-header \"Referer: https://www.bilibili.com/\" "
          "-o \"bili_video/%(id)s.%(ext)s\" <视频URL>", flush=True)
    print("      python scripts/frame_ocr.py bili_video/<id>.mp4 "
          "--out tmp_bili_extract/frames_ocr.json", flush=True)
