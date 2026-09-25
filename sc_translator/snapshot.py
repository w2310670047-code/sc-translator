"""按需（一次性）截图翻译：热键 -> 抓屏 -> 本地 OCR -> 翻译 -> 展示。

与早期"实时巡逻翻译"的区别：**不按键完全不耗资源**，没有巡逻线程、没有定时采样，
每次只在用户按热键时抓一帧、识别一次、翻译一次。

流程::

    F9  ->  ScreenCapture.grab(记住的区域)  ->  OcrEngine.recognize()  ->  行文本
        ->  OpenAiCompatClient.translate_lines_batch()  ->  译文
        ->  浮窗 + 主窗口结果区

设计要点：
- 重依赖（onnxruntime / opencv / rapidocr）只在**首次识别时**导入，保证启动依然很快；
- 屏幕坐标换算复用 screen.py（多显示器 + 高 DPI）；区域由 ui/region_select.py 框选得到；
- 原文先过术语表（Stanton→斯坦顿星系）再送模型，与文字翻译一致；
- 识别结果做启发式过滤：纯数字/纯符号/过短且无字母的行直接丢弃，省 API 调用。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger(__name__)

# 常见的"噪声行"：纯数字、纯标点、单字符符号
_NOISE = re.compile(r"^[\W\d_]+$")
_HAS_WORD = re.compile(r"[A-Za-z\u3040-\u30ff\uac00-\ud7af\u4e00-\u9fff]{2,}")


@dataclass
class SnapLine:
    source: str
    translated: str = ""
    ok: bool = True


@dataclass
class SnapResult:
    lines: list[SnapLine] = field(default_factory=list)
    elapsed_ms: int = 0
    ocr_ms: int = 0
    translate_ms: int = 0
    error: str = ""
    vision: bool = False          # True = 由多模态模型直接读图（未走本地 OCR）

    @property
    def texts(self) -> list[str]:
        return [ln.source for ln in self.lines]

    def pairs(self) -> list[tuple[str, str]]:
        return [(ln.source, ln.translated) for ln in self.lines]


def filter_lines(texts: list[str]) -> list[str]:
    """丢掉明显没意义的 OCR 行；保留去重后的结果（保持原顺序）。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in texts:
        t = (raw or "").strip()
        if not t or len(t) > 300:
            continue
        if _NOISE.match(t):
            continue
        if not _HAS_WORD.search(t):
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


class SnapshotService:
    """一次性的抓屏/识别/翻译服务（懒加载重型依赖）。"""

    def __init__(self, app) -> None:
        self.app = app
        self._ocr = None
        self._capture = None

    # ---------------- 抓屏 ----------------
    @property
    def capture(self):
        if self._capture is None:
            from .screen import ScreenCapture

            self._capture = ScreenCapture()
        return self._capture

    @property
    def ocr(self):
        if self._ocr is None:
            from .ocr import OcrEngine

            use_gpu = bool(getattr(getattr(self.app, "settings", None), "ocr_use_gpu", False))
            self._ocr = OcrEngine(use_gpu=use_gpu)
        return self._ocr

    def close(self) -> None:
        for obj in (self._capture,):
            try:
                if obj is not None:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        self._capture = None
        # OCR 引擎也要真正释放：切 CPU/GPU 模式或退出时，GPU 会话占的显存靠它归还
        if self._ocr is not None:
            try:
                self._ocr.close()
            except Exception:  # noqa: BLE001
                pass
            self._ocr = None

    # ---------------- 主流程 ----------------
    def run(
        self,
        region: dict,
        on_done: Callable[[SnapResult], None],
        *,
        max_lines: int = 40,
        use_cache: bool = True,
        on_ocr: Optional[Callable[[list[str]], None]] = None,
    ) -> None:
        """在后台线程执行 抓屏 -> OCR -> 翻译，完成后回调 on_done（主线程）。

        ``on_ocr``：可选的分阶段回调，OCR 一结束就把识别到的原文送**回主线程**
        （译文还在路上时先让用户看到东西）。
        """
        self.app.run_in_thread(
            lambda: self._work(region, max_lines, use_cache, on_ocr),
            lambda ok, val: self._deliver(ok, val, on_done),
        )

    def _post_partial(self, on_ocr: Callable[[list[str]], None], texts: list[str]) -> None:
        """把"已识别的原文"送回主线程；替身/单测环境没有 post_to_main 就直接调。"""
        poster = getattr(self.app, "post_to_main", None)
        if poster is not None:
            poster(lambda: on_ocr(list(texts)))
        else:
            on_ocr(list(texts))

    def _deliver(self, ok: bool, val, on_done: Callable[[SnapResult], None]) -> None:
        if ok:
            on_done(val)  # type: ignore[arg-type]
        else:
            on_done(SnapResult(error=str(val)))

    def _grab(self, phys: dict, res: SnapResult):
        """抓一帧（多后端自动回退：DXGI 桌面复制 → GDI BitBlt → Qt）。

        失败时把可读原因写进 ``res.error`` 并返回 ``(None, None)``。
        """
        bgr, backend, cap_err = self.capture.grab_ex(phys)
        if bgr is None:
            res.error = (
                f"抓屏失败（区域 {phys.get('width')}×{phys.get('height')} @"
                f"({phys.get('left')},{phys.get('top')})）：{cap_err}\n"
                "常见原因：游戏开了 HDR、画面带 GPU 保护（DRM），或该后端抓不到此画面。\n"
                "可尝试：关闭 HDR；把游戏切到窗口化/无边框；若仍失败请把 data\\logs 里的这行发我。"
            )
            return None, None
        if backend != self.capture.BACKENDS[0]:
            log.info("抓屏使用回退后端：%s", backend)
        return bgr, backend

    @staticmethod
    def _phys_or_error(region: dict, res: SnapResult):
        phys = (region or {}).get("physical")
        if not phys:
            res.error = "还没有框选截图区域（先按 F10 框选一次）"
            return None
        return phys

    def _work_vision(self, region: dict, max_lines: int) -> SnapResult:
        """方案 C：把框选的小图**直接交给多模态模型**（识别+翻译一次完成，不做本地 OCR）。

        好处：不吃本机 CPU/显存，也不需要 OCR 模型；代价：一次网络往返 + 图片 token，
        且**截图会离开本机**（用户在主窗口显式打开该开关时才走这条路）。
        """
        t0 = time.time()
        res = SnapResult(vision=True)
        phys = self._phys_or_error(region, res)
        if phys is None:
            return res
        bgr, backend = self._grab(phys, res)
        if bgr is None:
            return res
        try:
            import cv2  # 随 OCR 栈一起懒加载；这里只用来编码 PNG

            ok, buf = cv2.imencode(".png", bgr)
            if not ok:
                raise RuntimeError("PNG 编码失败")
            png = buf.tobytes()
        except Exception as exc:  # noqa: BLE001
            res.error = f"截图编码失败：{exc}"
            return res

        t_v = time.time()
        try:
            client = self.app.make_client(use_cache=False)   # 图片结果不进文本缓存
            pairs = client.translate_image(png, target_lang="zh-CN", max_lines=max_lines)
            res.lines = [SnapLine(source=s, translated=d) for s, d in pairs]
        except Exception as exc:  # noqa: BLE001
            res.error = f"读图翻译失败：{exc}"
        res.translate_ms = int((time.time() - t_v) * 1000)
        res.elapsed_ms = int((time.time() - t0) * 1000)
        log.info(
            "读图翻译（模型直读，不走本地 OCR）：%d 行，抓屏后端 %s，图片 %dKB，耗时 %dms%s",
            len(res.lines), backend, len(png) // 1024, res.elapsed_ms,
            f"，错误：{res.error}" if res.error else "",
        )
        return res

    def _work(self, region: dict, max_lines: int, use_cache: bool,
              on_ocr: Optional[Callable[[list[str]], None]] = None) -> SnapResult:
        # 方案 C：设置里开了「模型直接读图」就整条走多模态，完全不碰本地 OCR 栈
        if bool(getattr(getattr(self.app, "settings", None), "ocr_vision", False)):
            return self._work_vision(region, max_lines)
        t0 = time.time()
        res = SnapResult()
        phys = self._phys_or_error(region, res)
        if phys is None:
            return res

        # 1) 抓屏
        bgr, backend = self._grab(phys, res)
        if bgr is None:
            return res

        # 2) 本地 OCR
        t_ocr = time.time()
        try:
            rows = self.ocr.recognize(bgr)
        except Exception as exc:  # noqa: BLE001
            res.error = f"OCR 初始化/识别失败：{exc}"
            return res
        res.ocr_ms = int((time.time() - t_ocr) * 1000)
        texts = filter_lines([r.text for r in rows])[:max_lines]
        if not texts:
            res.error = "没有识别到文字（区域可能不含文本，或画面被遮挡）"
            return res
        # 分阶段反馈：先让用户看到识别到的原文（译文还要等网络往返）
        if on_ocr is not None:
            try:
                self._post_partial(on_ocr, texts)
            except Exception as exc:  # noqa: BLE001
                log.debug("分阶段回调失败（忽略）: %s", exc)

        # 3) 翻译
        t_tr = time.time()
        try:
            client = self.app.make_client(use_cache=use_cache)
            outs = client.translate_lines_batch(
                texts, source_lang="auto", target_lang="zh-CN", keep_chat_prefix=True
            )
            if isinstance(outs, str):
                outs = [outs]
            for src, dst in zip(texts, outs):
                res.lines.append(SnapLine(source=src, translated=str(dst)))
            if len(outs) < len(texts):
                for src in texts[len(outs):]:
                    res.lines.append(SnapLine(source=src, translated="", ok=False))
        except Exception as exc:  # noqa: BLE001
            # 翻译失败也要把原文给用户看
            res.lines = [SnapLine(source=t, translated="", ok=False) for t in texts]
            res.error = f"翻译失败：{exc}"
        res.translate_ms = int((time.time() - t_tr) * 1000)
        res.elapsed_ms = int((time.time() - t0) * 1000)
        log.info(
            "截图翻译：%d 行，抓屏后端 %s，OCR %dms，翻译 %dms，合计 %dms%s",
            len(res.lines),
            backend,
            res.ocr_ms,
            res.translate_ms,
            res.elapsed_ms,
            f"，错误：{res.error}" if res.error else "",
        )
        return res


# ------------------------------------------------------------------ 热键
_VK_F: dict[str, int] = {f"F{i}": 0x6F + i for i in range(1, 25)}   # F1=0x70
_VK_NAMED = {
    "PRINTSCREEN": 0x2C, "SCROLLLOCK": 0x91, "PAUSE": 0x13, "INSERT": 0x2D,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B, "ESCAPE": 0x1B,
}
_MODS = {"CTRL": 0x0002, "CONTROL": 0x0002, "SHIFT": 0x0004, "ALT": 0x0001, "WIN": 0x0008}


def parse_hotkey(spec: str) -> Optional[tuple[int, int]]:
    """``"F9"`` / ``"Ctrl+Shift+S"`` -> (modifiers, vk)。无法解析返回 None。"""
    if not spec:
        return None
    mods = 0
    key = ""
    for part in str(spec).replace(" ", "").split("+"):
        if not part:
            continue
        up = part.upper()
        if up in _MODS:
            mods |= _MODS[up]
        else:
            key = up
    if not key:
        return None
    if key in _VK_F:
        return mods, _VK_F[key]
    if key in _VK_NAMED:
        return mods, _VK_NAMED[key]
    if len(key) == 1 and (key.isalnum()):
        return mods, ord(key)
    return None


def hotkey_label(spec: str) -> str:
    """给界面显示用的规范化文本。"""
    parsed = parse_hotkey(spec)
    if parsed is None:
        return spec
    mods, vk = parsed
    parts = []
    for name, val in (("Ctrl", 0x0002), ("Shift", 0x0004), ("Alt", 0x0001), ("Win", 0x0008)):
        if mods & val:
            parts.append(name)
    for name, val in _VK_F.items():
        if val == vk:
            parts.append(name)
            return "+".join(parts)
    for name, val in _VK_NAMED.items():
        if val == vk:
            parts.append(name.title())
            return "+".join(parts)
    parts.append(chr(vk).upper() if 32 < vk < 127 else f"0x{vk:02X}")
    return "+".join(parts)


# ------------------------------------------------------------------ 键盘录入辅助
# Qt 键码 -> 我们的键名（用于"点一下直接按组合键"的录入控件；按**键码**匹配，
# 因为很多命名键（Print/Insert/Home…）在 keyPressEvent 里 ev.text() 是空串）
# 注意：右侧数值取自 Qt 实际枚举值（tests 里有一条断言防止写错）
_QT_NAMED_BY_CODE: dict[int, str] = {
    0x01000000: "ESC",           # Qt.Key_Escape
    0x01000001: "TAB",           # Qt.Key_Tab
    0x01000004: "ENTER",         # Qt.Key_Return
    0x01000005: "ENTER",         # Qt.Key_Enter
    0x01000006: "INSERT",        # Qt.Key_Insert
    0x01000008: "PAUSE",         # Qt.Key_Pause
    0x01000009: "PRINTSCREEN",   # Qt.Key_Print
    0x0100000A: "PRINTSCREEN",   # Qt.Key_SysReq
    0x01000010: "HOME",          # Qt.Key_Home
    0x01000011: "END",           # Qt.Key_End
    0x01000016: "PAGEUP",        # Qt.Key_PageUp
    0x01000017: "PAGEDOWN",      # Qt.Key_PageDown
    0x20: "SPACE",               # Qt.Key_Space
}
_QT_NAMED_BY_TEXT: dict[str, str] = {
    "Print": "PRINTSCREEN", "ScrollLock": "SCROLLLOCK", "Pause": "PAUSE",
    "Insert": "INSERT", "Home": "HOME", "End": "END",
    "PageUp": "PAGEUP", "PageDown": "PAGEDOWN", "Space": "SPACE",
    "Tab": "TAB", "Return": "ENTER", "Enter": "ENTER", "Escape": "ESC",
    " ": "SPACE",
}

# Qt 修饰键掩码 -> 我们的修饰键名
# 注意：Qt.ShiftModifier = 0x02000000、Qt.ControlModifier = 0x04000000（别写反！）
_MODIFIER_NAMES = {
    0x04000000: "Ctrl",   # Qt.ControlModifier
    0x02000000: "Shift",  # Qt.ShiftModifier
    0x08000000: "Alt",    # Qt.AltModifier
    0x10000000: "Win",    # Qt.MetaModifier
}


def spec_from_qt(key: int, modifiers: int, key_text: str = "") -> Optional[str]:
    """把 Qt 的 (键码, 修饰键) 转成热键字符串；无法作为热键时返回 None。

    - F1-F24 / Print / Insert / Home / PageUp 等命名键：可单独使用；
    - 字母与数字：必须搭配 Ctrl/Shift/Alt/Win（否则会抢走整个键盘的该键）。
    """
    parts: list[str] = []
    for mask, name in _MODIFIER_NAMES.items():
        if modifiers & mask:
            parts.append(name)

    name: Optional[str] = None
    if 0x01000030 <= key <= 0x01000047:          # Qt.Key_F1 .. Qt.Key_F24
        name = f"F{key - 0x01000030 + 1}"
    if name is None:
        name = _QT_NAMED_BY_CODE.get(key) or _QT_NAMED_BY_TEXT.get((key_text or "").strip())
    if name is None:
        text = (key_text or "").strip()
        if len(text) == 1 and text.isascii() and text.isalnum():
            if not parts:
                return None                       # 纯字母/数字不单独作为热键
            name = text.upper()
    if name is None and (0x41 <= key <= 0x5A or 0x30 <= key <= 0x39):
        if not parts:
            return None
        name = chr(key)
    if name is None:
        return None
    parts.append(name)
    spec = "+".join(parts)
    return spec if parse_hotkey(spec) is not None else None
