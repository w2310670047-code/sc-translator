"""屏幕区域捕获与 Qt 逻辑坐标 <-> mss 物理坐标换算。

Qt6 默认按监视器 DPI 感知，主窗口/框选使用的坐标是“逻辑像素”；
mss 抓取的是物理像素。缩放显示器(125%/150%…)时必须换算，
否则框选区域会错位。区域本身只允许落在单个显示器内，
物理布局按“显示器按 (top,left) 排序后逐行累计宽度”重建，
可正确处理常见的单行/多行多显示器排列。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

try:
    import mss
except Exception as exc:  # noqa: BLE001
    mss = None
    log.warning("mss 不可用: %s", exc)


@dataclass
class ScreenInfo:
    """一个显示器的逻辑信息（来自 Qt 或测试替身）。"""
    index: int
    logical: tuple[int, int, int, int]   # x, y, w, h（逻辑像素，虚拟桌面全局）
    dpr: float

    @property
    def x(self): return self.logical[0]
    @property
    def y(self): return self.logical[1]
    @property
    def w(self): return self.logical[2]
    @property
    def h(self): return self.logical[3]


@dataclass
class ScreenLayout:
    info: ScreenInfo
    phys_origin: tuple[int, int]  # 该显示器在物理桌面上的左上角
    phys_size: tuple[int, int]    # 物理宽高

    def phys_rect(self) -> dict:
        x, y = self.phys_origin
        w, h = self.phys_size
        return {"left": x, "top": y, "width": w, "height": h}


def build_layouts(screens: list[ScreenInfo]) -> list[ScreenLayout]:
    """重建显示器在物理桌面上的坐标布局。"""
    if not screens:
        return []
    ordered = sorted(screens, key=lambda s: (round(s.y / 20.0), s.x))  # 按行优先
    layouts: list[ScreenLayout] = []
    cursor_x, cursor_y = 0, 0
    row_top = None
    row_max_h = 0
    for s in ordered:
        w_px = max(1, round(s.w * s.dpr))
        h_px = max(1, round(s.h * s.dpr))
        if row_top is None or abs(s.y - row_top) > 40:  # 新的一行显示器
            if row_top is not None:
                cursor_y += row_max_h
            cursor_x = 0
            row_top = s.y
            row_max_h = h_px
        row_max_h = max(row_max_h, h_px)
        layouts.append(ScreenLayout(info=s, phys_origin=(cursor_x, cursor_y), phys_size=(w_px, h_px)))
        cursor_x += w_px
    return layouts


def find_screen_for_point(screens: list[ScreenInfo], lx: int, ly: int) -> Optional[ScreenInfo]:
    for s in screens:
        x, y, w, h = s.logical
        if x <= lx < x + w and y <= ly < y + h:
            return s
    return None


def logical_rect_to_physical(layouts: list[ScreenLayout], rect: tuple[int, int, int, int]) -> Optional[dict]:
    """逻辑矩形 (lx, ly, lw, lh) -> mss 物理矩形 dict。

    若横跨多个显示器则以中心所在显示器为准（返回 None 表示中心不在任何显示器）。
    """
    lx, ly, lw, lh = rect
    cx, cy = lx + lw / 2, ly + lh / 2
    for lay in layouts:
        s = lay.info
        sx, sy, sw, sh = s.logical
        if sx <= cx < sx + sw and sy <= cy < sy + sh:
            dpr = s.dpr
            ox, oy = lay.phys_origin
            left = ox + round((lx - sx) * dpr)
            top = oy + round((ly - sy) * dpr)
            width = max(1, round(lw * dpr))
            height = max(1, round(lh * dpr))
            return {"left": left, "top": top, "width": width, "height": height}
    return None


def physical_rect_to_logical(layouts: list[ScreenLayout], phys: dict) -> Optional[dict]:
    """mss 物理矩形 -> 逻辑矩形（用于定位悬浮窗）。"""
    left, top = phys["left"], phys["top"]
    w, h = phys["width"], phys["height"]
    cx, cy = left + w / 2, top + h / 2
    for lay in layouts:
        ox, oy = lay.phys_origin
        pw, ph = lay.phys_size
        if ox <= cx < ox + pw and oy <= cy < oy + ph:
            s = lay.info
            dpr = s.dpr
            return {
                "x": s.x + round((left - ox) / dpr),
                "y": s.y + round((top - oy) / dpr),
                "w": max(1, round(w / dpr)),
                "h": max(1, round(h / dpr)),
            }
    return None


class ScreenCapture:
    """封装 mss：从给定物理矩形抓屏，返回 BGR ndarray。"""

    def __init__(self) -> None:
        if mss is None:
            raise RuntimeError("mss 未安装，无法抓屏")
        factory = getattr(mss, "MSS", None) or mss.mss
        self._sct = factory()
        self._monitors = self._sct.monitors  # [0]=整体,[1..]=各显示器
        log.info("mss 就绪，显示器数量: %d", len(self._monitors) - 1)

    def grab(self, phys_rect: dict) -> Optional[np.ndarray]:
        """返回 BGR 图像（uint8），失败返回 None。"""
        try:
            shot = self._sct.grab(phys_rect)
            # mss 10 返回 bytes；必须用 frombuffer（np.asarray 会把 bytes 当字符串解析）
            buf = np.frombuffer(shot.bgra, dtype=np.uint8)
            return buf.reshape(shot.height, shot.width, 4)[:, :, :3].copy()  # BGR
        except Exception as exc:  # noqa: BLE001
            log.warning("抓屏失败 %s: %s", phys_rect, exc)
            return None

    def monitor_count(self) -> int:
        return len(self._monitors) - 1

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:  # noqa: BLE001
            pass
