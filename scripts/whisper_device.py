"""共享的 Whisper 设备选择助手（bilibili-video-summarizer 与 bili-deep-report 通用）。

策略（2026-10-25 实测沉淀）：
- 默认 auto：探测到 CUDA 设备即用 GPU（float16），初始化失败回退 CPU（int8）。
- BILI_WHISPER_DEVICE=cpu|cuda 可强制。
- GPU 依赖 nvidia-cublas-cu12 / nvidia-cudnn-cu12 两个 pip 包；ctranslate2 的
  依赖链解析不认 os.add_dll_directory（实测无效），必须把 nvidia/*/bin 目录
  前置到 PATH 环境变量。
- CUDA 错误可能延迟到消费 segments 生成器时才爆发（cuDNN 惰性加载），调用方
  需对生成器迭代做 try/except 并在 GPU 模式下整体回退 CPU 重跑（见 bili_video.py
  asr_transcribe 的样板）。实测：RTX 3080 上 9 分钟音轨 CPU 266s → GPU 47s。
"""
import os


def pick_and_prepare(verbose: bool = False):
    """返回 (device, compute_type)。GPU 可用时已把 DLL 目录前置到 PATH。"""
    forced = os.environ.get("BILI_WHISPER_DEVICE", "").strip().lower()
    if forced == "cpu":
        return "cpu", "int8"
    try:
        import ctranslate2 as _ct2
        if _ct2.get_cuda_device_count() > 0:
            _sp = os.path.dirname(
                os.path.dirname(os.path.abspath(_ct2.__file__)))
            for _sub in (os.path.join("nvidia", "cublas", "bin"),
                         os.path.join("nvidia", "cudnn", "bin")):
                _p = os.path.join(_sp, _sub)
                if os.path.isdir(_p):
                    os.environ["PATH"] = _p + os.pathsep + os.environ["PATH"]
            return "cuda", "float16"
    except Exception as e:
        if verbose:
            print(f"[asr] GPU 探测失败（{type(e).__name__}），用 CPU", flush=True)
    return "cpu", "int8"
