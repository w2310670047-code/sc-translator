"""屏幕区域捕获与 Qt 逻辑坐标 <-> mss 物理坐标换算。

Qt6 默认按监视器 DPI 感知，主窗口/框选使用的坐标是“逻辑像素”；
mss 抓取的是物理像素。缩放显示器(125%/150%…)时必须换算，
否则框选区域会错位。区域本身只允许落在单个显示器内，
物理布局按“显示器按 (top,left) 排序后逐行累计宽度”重建，
可正确处理常见的单行/多行多显示器排列。
"""

from __future__ import annotations

import logging
import time
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
    """抓屏：多后端自动回退（DXGI 桌面复制 / GDI BitBlt / Qt），返回 BGR ndarray。

    为什么要多后端：mss 走 GDI BitBlt，遇到使用 DXGI 翻转模型（flip model）的游戏画面
    会直接失败（日志里是 `Windows graphics function failed: BitBlt`），
    这与"是否独占全屏"无关——无边框窗口同样会中招。dxcam 走 DXGI 桌面复制，
    正是为抓这种画面设计的。
    """

    #: 后端顺序：先用 DXGI（对游戏最可靠），失败再退 GDI、再退 Qt
    BACKENDS = ("dxcam", "mss", "qt")

    def __init__(self, backend: str = "auto") -> None:
        self._backend_pref = backend or "auto"
        self._last_good = ""          # 上次成功的后端，优先复用
        self._sct = None
        self._monitors: list[dict] = []
        self._cam = None
        self.last_backend = ""
        self.last_errors: dict[str, str] = {}
        self._init_mss()

    # ---------------- 初始化 ----------------
    def _init_mss(self) -> None:
        if mss is None:
            self.last_errors["mss"] = "mss 未安装"
            return
        try:
            factory = getattr(mss, "MSS", None) or mss.mss
            self._sct = factory()
            self._monitors = self._sct.monitors
            log.info("mss 就绪，显示器数量: %d", len(self._monitors) - 1)
        except Exception as exc:  # noqa: BLE001
            self._sct = None
            self.last_errors["mss"] = str(exc)
            log.warning("mss 初始化失败: %s", exc)

    def _ensure_dxcam(self):
        if self._cam is not None:
            return self._cam
        import dxcam  # 可选依赖；没有就抛 ImportError 由调用方记录

        self._cam = dxcam.create(output_idx=0, output_color="BGR")
        log.info("dxcam 就绪（DXGI 桌面复制）")
        return self._cam

    # ---------------- 抓屏 ----------------
    def virtual_rect(self) -> dict:
        """整个虚拟桌面的物理矩形（用于把请求裁进有效范围）。"""
        if self._monitors:
            m = self._monitors[0]
            return {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
        return {"left": 0, "top": 0, "width": 0, "height": 0}

    def _clamp(self, rect: dict) -> dict:
        v = self.virtual_rect()
        if not v["width"]:
            return rect
        left = max(v["left"], min(int(rect["left"]), v["left"] + v["width"] - 1))
        top = max(v["top"], min(int(rect["top"]), v["top"] + v["height"] - 1))
        right = min(v["left"] + v["width"], int(rect["left"]) + max(1, int(rect["width"])))
        bottom = min(v["top"] + v["height"], int(rect["top"]) + max(1, int(rect["height"])))
        return {"left": left, "top": top, "width": max(1, right - left), "height": max(1, bottom - top)}

    def grab(self, phys_rect: dict) -> Optional[np.ndarray]:
        """返回 BGR 图像（uint8），全部后端都失败则返回 None。"""
        img, _backend, _err = self.grab_ex(phys_rect)
        return img

    def grab_ex(self, phys_rect: dict) -> tuple[Optional[np.ndarray], str, str]:
        """抓屏并返回 (图像, 使用的后端, 错误说明)；成功时错误为空串。"""
        if not phys_rect:
            return None, "", "没有提供抓屏区域"
        rect = self._clamp(phys_rect)
        self.last_errors = {}
        order = list(self.BACKENDS)
        # 上次成功的后端优先（避免每次都先踩一次必失败的后端）；其次是用户指定的
        preferred = self._last_good or self._backend_pref
        if preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)

        for name in order:
            fn = getattr(self, f"_grab_{name}", None)
            if fn is None:
                continue
            for attempt in (1, 2):                 # 每个后端给两次机会（首次偶发失败很常见）
                try:
                    img = fn(rect)
                except Exception as exc:  # noqa: BLE001
                    self.last_errors[name] = f"{type(exc).__name__}: {exc}"
                    log.debug("抓屏后端 %s 第 %d 次失败: %s", name, attempt, exc)
                    img = None
                if img is not None:
                    if self._looks_blank(img):
                        self.last_errors[name] = "画面全黑（可能是 HDR / 受保护内容 / 该后端抓不到此画面）"
                        log.warning("抓屏后端 %s 返回全黑画面，尝试下一个后端", name)
                        break                      # 换后端，不重试本后端
                    self.last_backend = name
                    self._last_good = name
                    return img, name, ""
                time.sleep(0.06)
            if name not in self.last_errors:
                self.last_errors[name] = "返回空帧"

        detail = "；".join(f"{k}: {v}" for k, v in self.last_errors.items()) or "未知原因"
        log.warning("所有抓屏后端均失败 %s → %s", rect, detail)
        return None, "", detail

    @staticmethod
    def _looks_blank(img: np.ndarray) -> bool:
        """判断是否"全黑"（HDR / 受保护内容常见表现）。"""
        try:
            if img is None or img.size == 0:
                return True
            small = img[::8, ::8]
            return bool(float(small.mean()) < 2.0 and float(small.std()) < 1.0)
        except Exception:  # noqa: BLE001
            return False

    # ---------------- 各后端实现 ----------------
    def _grab_mss(self, rect: dict) -> Optional[np.ndarray]:
        if self._sct is None:
            self._init_mss()
        if self._sct is None:
            raise RuntimeError("mss 不可用")
        shot = self._sct.grab(rect)
        # mss 10 返回 bytes；必须用 frombuffer（np.asarray 会把 bytes 当字符串解析）
        buf = np.frombuffer(shot.bgra, dtype=np.uint8)
        return buf.reshape(shot.height, shot.width, 4)[:, :, :3].copy()   # BGR

    def _grab_dxcam(self, rect: dict) -> Optional[np.ndarray]:
        cam = self._ensure_dxcam()
        # dxcam 的区域是 (left, top, right, bottom)，坐标相对主输出
        frame = cam.grab(region=(rect["left"], rect["top"],
                                 rect["left"] + rect["width"], rect["top"] + rect["height"]))
        if frame is None:
            frame = cam.grab()             # 没有新帧时先整屏拿一帧再裁
            if frame is None:
                raise RuntimeError("dxcam 未返回帧")
            frame = frame[rect["top"]:rect["top"] + rect["height"],
                          rect["left"]:rect["left"] + rect["width"]]
        return np.ascontiguousarray(frame[:, :, :3])

    def _grab_qt(self, rect: dict) -> Optional[np.ndarray]:
        """Qt 抓屏兜底：走另一条 Windows 抓屏路径。"""
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("没有可用显示器")
        dpr = float(screen.devicePixelRatio() or 1.0)
        lx, ly = int(rect["left"] / dpr), int(rect["top"] / dpr)
        lw, lh = max(1, int(round(rect["width"] / dpr))), max(1, int(round(rect["height"] / dpr)))
        pm = screen.grabWindow(0, lx, ly, lw, lh)
        if pm.isNull():
            raise RuntimeError("QScreen.grabWindow 返回空图")
        img = pm.toImage()
        if img.width() != rect["width"] or img.height() != rect["height"]:
            img = img.scaled(rect["width"], rect["height"])
        img = img.convertToFormat(img.Format.Format_BGR888)
        ptr = img.constBits()
        arr = np.frombuffer(ptr, dtype=np.uint8).reshape(img.height(), img.bytesPerLine())[:, : img.width() * 3]
        return arr.reshape(img.height(), img.width(), 3).copy()

    def monitor_count(self) -> int:
        return max(0, len(self._monitors) - 1)

    def close(self) -> None:
        try:
            if self._sct is not None:
                self._sct.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._cam is not None:
                del self._cam        # dxcam 没有显式 close，释放引用即可停止复制会话
            self._cam = None
        except Exception:  # noqa: BLE001
            pass

def dxcam_available() -> bool:
    """DXGI 桌面复制后端是否可用（抓游戏画面主要靠它）。"""
    try:
        import dxcam  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False