"""端到端：假截图流 -> 真实 OCR -> 管线稳定确认 -> 翻译 -> 快照。验证线程协作。"""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from sc_translator.pipeline import Callbacks, Coordinator, PipelineSettings

_FONT = None


def _font():
    global _FONT
    if _FONT is None:
        from PIL import ImageFont

        for cand in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
            try:
                _FONT = ImageFont.truetype(cand, 24)
                break
            except Exception:
                continue
    return _FONT


def _frame(lines: list[str]) -> np.ndarray:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (760, 170), (15, 18, 24))
    d = ImageDraw.Draw(img)
    y = 12
    for ln in lines:
        d.text((14, y), ln, fill=(226, 232, 240), font=_font())
        y += 40
    return np.asarray(img)[:, :, ::-1].copy()


def _collect():
    """造一个假的截屏器：按步进返回帧，每步重复 n 次保证 OCR 稳定。"""
    steps = [
        ([ "Need a lift to Microtech?", "Anyone have cargo space?" ], 10),
        ([ "Need a lift to Microtech?", "Anyone have cargo space?", "Trading at Area18" ], 14),
    ]
    seq = []
    for lines, n in steps:
        f = _frame(lines)
        seq.extend([f] * n)

    class FakeCapture:
        def __init__(self):
            self._i = 0

        def grab(self, phys_rect: dict):
            if self._i < len(seq):
                f = seq[self._i]
                self._i += 1
                return f
            return seq[-1]  # 保持最后一帧

    return FakeCapture()


def test_end_to_end_threaded(tmp_home):
    from sc_translator.ocr import OcrEngine

    snaps: list[list[dict]] = []
    ev = threading.Event()
    lock = threading.Lock()
    ocr_ready = threading.Event()

    def on_snapshot(s: list[dict]) -> None:
        with lock:
            snaps.append(list(s))
            if len(s) == 3 and all(not e.get("pending") and e.get("translated") for e in s):
                ev.set()

    class CountingOcr:
        def __init__(self):
            self._inner = OcrEngine()

        def recognize(self, bgr):
            out = self._inner.recognize(bgr)
            ocr_ready.set()
            return out

    cap = _collect()
    engine = CountingOcr()
    ps = PipelineSettings(sample_ms=40, stable_frames=2, max_text_chars=800, ocr_interval_s=0.4, ocr_idle_s=0.4)
    translations: dict[str, str] = {
        "Need a lift to Microtech?": "需要搭便车去微科技吗？",
        "Anyone have cargo space?": "有人有货舱空间吗？",
        "Trading at Area18": "在18区交易",
    }

    def translate_call(norm: str, src: str) -> str:
        return translations.get(norm, f"译：{norm}")

    coord = Coordinator(ps, {"left": 0, "top": 0, "width": 760, "height": 170}, cap, engine,
                        translate_call, Callbacks(on_snapshot=on_snapshot))
    try:
        coord.start()
        # 等出现第三条译文（最多 ~30s，OCR 含模型加载）
        assert ocr_ready.wait(20), "OCR 未就绪"
        assert ev.wait(25), "3 行全部译文未在超时前出现"
        with lock:
            final = snaps[-1] if snaps else []
            texts = [e["text"] for e in final]
            assert len(final) == 3, texts
            assert all(not e["pending"] and e["translated"] for e in final)
            by_text = {e["text"]: e["translated"] for e in final}
            assert any("Microtech" in t for t in by_text), texts
            trading = [t for t in texts if "Trading" in t]
            assert trading and by_text[trading[0]] == "在18区交易", texts
    finally:
        coord.stop()
    # 停止后线程已退出
    assert coord.running is False
