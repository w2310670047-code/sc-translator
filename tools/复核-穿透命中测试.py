"""鼠标穿透命中测试真机复核：验证"逐区域穿透"（修 bug：整窗穿透让回话/滚动一起失效）。

用法：
    python tools/复核-穿透命中测试.py <data_home>

为什么必须真机跑：逐区域穿透靠回答 Windows 的 WM_NCHITTEST 实现，离屏平台下
这条路径根本不执行（离屏只覆盖 is_interactive_point() 的纯逻辑）。

检查项（输出刻意用 ASCII，避免 GBK 控制台编码问题）：
1. 穿透态下，向浮窗直接发 WM_NCHITTEST：
   - 译文滚动区中心、回话输入框中心 -> 不得返回 HTTRANSPARENT(-1)
     （归浮窗处理 = 能滚动、能输入，这正是修好的两个问题）；
   - 左边缘空白处 -> 必须返回 HTTRANSPARENT(-1)（点击/滚轮交给下面的游戏）。
2. 固定态下：同样三个点都不得返回 HTTRANSPARENT（整窗可交互）。
3. 穿透状态本身要稳：设成穿透后 pinned() 必须立刻为 False（旧实现在回话条
   开着时会被 set_reply_enabled() 强制改回固定，表现为"穿透开关点了等于没点"）。
4. 附带观测 WindowFromPoint（仅供参考，不作为断言）。
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

# 直接用 `python tools/复核-穿透命中测试.py` 跑时，sys.path[0] 是 tools/，
# 找不到 sc_translator 包；这里把项目根补上（与用法说明保持一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from sc_translator.app import AppController
from sc_translator.ui.overlay import WM_NCHITTEST

HTTRANSPARENT = -1

user32 = ctypes.windll.user32
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def nchittest(hwnd: int, sx: int, sy: int) -> int:
    """把一个屏幕坐标点交给该窗口做命中测试，返回它给出的 HT* 码。"""
    lp = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
    return int(user32.SendMessageW(wintypes.HWND(hwnd), WM_NCHITTEST, 0, lp))


def center_global(w) -> tuple[int, int]:
    p = w.mapToGlobal(QPoint(w.width() // 2, w.height() // 2))
    return p.x(), p.y()


def pump(app, n: int = 12) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(0.05)


def main() -> int:
    home = sys.argv[1]
    os.environ["SC_TRANSLATOR_HOME"] = home

    app = QApplication(sys.argv[:1])
    ctrl = AppController(app)
    ctrl.init_ui()
    ctrl.mainwin.show()
    pump(app)

    ov = ctrl.ensure_overlay()
    s = ctrl.settings
    s.reply_enabled = True
    s.click_through = False          # 先固定，让回话条能装配
    ov.push_lines(
        [{"key": f"line {i}", "text": f"line {i}", "translated": f"tr {i}", "pending": False}
         for i in range(12)]
    )
    ov.set_reply_enabled(True)
    ov.show_overlay()
    pump(app)

    # 统计 nativeEvent 真的被调用（否则说明 Qt 没把 WM_NCHITTEST 转给控件）
    calls = {"n": 0}
    orig_native = ov.nativeEvent

    def counted(event_type, message):
        calls["n"] += 1
        return orig_native(event_type, message)

    ov.nativeEvent = counted

    hwnd = int(ov.winId())
    print("overlay hwnd:", hwnd, " visible:", ov.isVisible(),
          " size:", ov.size().width(), "x", ov.size().height(), flush=True)

    rows_pt = center_global(ov._scroll)
    reply_pt = center_global(ov._reply_input)
    corner = ov.mapToGlobal(QPoint(3, ov.height() // 2))
    empty_pt = (corner.x(), corner.y())
    named = [("rows-area", rows_pt), ("reply-input", reply_pt), ("empty-margin", empty_pt)]

    def probe_all(tag: str) -> dict[str, int]:
        out = {}
        print(f"[{tag}]", flush=True)
        for name, (x, y) in named:
            code = nchittest(hwnd, x, y)
            inner = ov.is_interactive_point(ov.mapFromGlobal(QPoint(x, y)))
            out[name] = code
            print(f"  {name:<13} screen({x},{y})  HT={code:<3} inner={inner}", flush=True)
        return out

    ov.set_pinned(False)             # 穿透态
    pump(app)
    print("[0] after set_pinned(False): pinned =", ov.pinned(),
          "| click_through =", s.click_through, "(expect False / True)", flush=True)
    state_ok = (ov.pinned() is False and s.click_through is True)

    passthrough = probe_all("1 passthrough")

    ov.set_pinned(True)              # 固定态
    pump(app)
    pinned = probe_all("2 pinned")

    print("[3] WindowFromPoint observation (not asserted)", flush=True)
    for name, (x, y) in named:
        pt = _POINT(x, y)
        got = int(user32.WindowFromPoint(pt))
        print(f"  {name:<13} -> hwnd={got} (overlay={hwnd}, same={got == hwnd})", flush=True)

    print("nativeEvent calls:", calls["n"], flush=True)

    ok = True
    if not state_ok:
        ok = False
        print("  FAIL: passthrough state did not stick (force-pin regression)", flush=True)
    if passthrough["rows-area"] == HTTRANSPARENT:
        ok = False
        print("  FAIL: rows area counts as transparent (scrolling would break)", flush=True)
    if passthrough["reply-input"] == HTTRANSPARENT:
        ok = False
        print("  FAIL: reply input counts as transparent (typing would break)", flush=True)
    if passthrough["empty-margin"] != HTTRANSPARENT:
        ok = False
        print("  FAIL: empty margin is not transparent (would block the game)", flush=True)
    for name, _ in named:
        if pinned[name] == HTTRANSPARENT:
            ok = False
            print(f"  FAIL: pinned state marked {name} transparent", flush=True)
    if calls["n"] == 0:
        ok = False
        print("  FAIL: nativeEvent never called (Qt does not forward WM_NCHITTEST)", flush=True)

    print("RESULT:", "PASS" if ok else "FAIL", flush=True)
    ctrl.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
