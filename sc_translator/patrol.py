"""像素变化巡逻：以低成本截图签名判断区域是否变化，避免每帧都跑 OCR。"""

from __future__ import annotations

from typing import Optional

import numpy as np

_SIG_WIDTH = 96  # 签名宽度(px)，高度按比例缩放


def to_signature(bgr: np.ndarray) -> np.ndarray:
    """BGR 图 -> 缩小灰度 uint8 数组。

    优先用 OpenCV（C 级缩放），大幅低于纯 Python 逐像素灰度计算的 CPU 开销；
    无 cv2 时回退到最近邻切片近似。
    """
    if bgr is None or bgr.size == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    h, w = bgr.shape[:2]
    nh = max(1, int(round(h * _SIG_WIDTH / w)))
    try:
        import cv2

        small = cv2.resize(bgr, (_SIG_WIDTH, nh), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    except Exception:  # noqa: BLE001
        pass
    # 纯 numpy 回退：行/列抽样灰度（近似亮度）
    ys = (np.linspace(0, h - 1, nh)).astype(np.int32)
    xs = (np.linspace(0, w - 1, _SIG_WIDTH)).astype(np.int32)
    sampled = bgr[ys][:, xs].astype(np.float32)
    gray = sampled[:, :, 0] * 0.114 + sampled[:, :, 1] * 0.587 + sampled[:, :, 2] * 0.299
    return gray.astype(np.uint8)


def diff_score(a: np.ndarray, b: np.ndarray) -> float:
    """两张签名图的平均像素差，范围 0..1。两张同尺寸。"""
    if a.shape != b.shape:
        return 1.0
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean() / 255.0)


def changed_fraction(a: np.ndarray, b: np.ndarray, pixel_thr: int = 12) -> float:
    """强变化像素占比（0..1）。比平均差更适合“新出现了一行文字”这类局部变化。"""
    if a is None or b is None or a.shape != b.shape:
        return 1.0
    d = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float((d > pixel_thr).mean())


class ChangeDetector:
    """连续采样时的变化判定状态机。

    用法：每帧调用 update(sig) -> True 表示“与上一帧相比发生了值得 OCR 的变化”。
    min_fraction: 强变化像素占比阈值；低于视为无变化。
    """

    def __init__(self, min_fraction: float = 0.002, pixel_thr: int = 12) -> None:
        self.min_fraction = min_fraction
        self.pixel_thr = pixel_thr
        self._prev: Optional[np.ndarray] = None
        self._same_run = 0  # 连续“无变化”帧数

    def update(self, sig: np.ndarray) -> bool:
        changed = False
        if self._prev is not None:
            frac = changed_fraction(self._prev, sig, self.pixel_thr)
            if frac >= self.min_fraction:
                changed = True
                self._same_run = 0
            else:
                self._same_run += 1
        self._prev = sig
        return changed

    def unchanged_frames(self) -> int:
        return self._same_run
