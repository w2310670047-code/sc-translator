"""框选区域真机复核：直接走 on_snap_select_hotkey() 路径，截图取证 + 断言。

用法：
    python tools/复核-框选区域.py <data_home> [select|cancel]

检查项：
1. 调用后主窗口隐藏、全屏选择器出现（截图人工可看）；
2. 选中：区域按"全局逻辑坐标 + 物理像素"保存，主窗口恢复；
3. 取消：主窗口恢复（这是曾经的 bug：取消后主窗口再也不回来）。
"""

import json
import os
import sys
import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sc_translator.app import AppController
from sc_translator.ui.region_select import RegionSelect


def find_picker(app) -> RegionSelect | None:
    for w in app.topLevelWidgets():
        if isinstance(w, RegionSelect):
            return w
    return None


def shot(screen, path: str) -> None:
    pm = screen.grabWindow(0)
    pm.save(path)
    print(f"  截图 {path} ({pm.width()}x{pm.height()})", flush=True)


def main() -> int:
    home = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "select"
    out = os.path.join(os.environ["TEMP"], "sc_region_check")
    os.makedirs(out, exist_ok=True)
    os.environ["SC_TRANSLATOR_HOME"] = home

    app = QApplication(sys.argv[:1])
    ctrl = AppController(app)
    ctrl.init_ui()
    win = ctrl.mainwin
    win.show()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)
    print("主窗口可见:", win.isVisible(), flush=True)

    print("[1] 调用 on_snap_select_hotkey()", flush=True)
    win.on_snap_select_hotkey()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    picker = find_picker(app)
    print("  主窗口可见:", win.isVisible(), "（期望 False）", flush=True)
    print("  选择器存在:", picker is not None, flush=True)
    if picker is not None:
        print("  选择器几何:", picker.geometry().getRect(), "可见:", picker.isVisible(),
              "置顶:", bool(picker.windowFlags() & Qt.WindowStaysOnTopHint), flush=True)
    shot(QGuiApplication.primaryScreen(), os.path.join(out, "picker.png"))

    if mode == "cancel":
        print("[2] 按 Esc 取消", flush=True)
        if picker is not None:
            QTest.keyClick(picker, Qt.Key.Key_Escape)
        for _ in range(20):
            app.processEvents()
            time.sleep(0.05)
    else:
        print("[2] 模拟拖拽 (600,400)->(1000,600)", flush=True)
        if picker is not None:
            QTest.mousePress(picker, Qt.MouseButton.LeftButton, pos=QPoint(600, 400))
            for step in range(1, 9):
                QTest.mouseMove(picker, QPoint(600 + step * 50, 400 + step * 25))
                app.processEvents()
                time.sleep(0.03)
            QTest.mouseRelease(picker, Qt.MouseButton.LeftButton, pos=QPoint(1000, 600))
        for _ in range(30):
            app.processEvents()
            time.sleep(0.05)

    print("[3] 主窗口可见:", win.isVisible(), "（期望 True）", flush=True)
    shot(QGuiApplication.primaryScreen(), os.path.join(out, "after.png"))

    with open(os.path.join(home, "settings.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    region = cfg.get("snap_region")
    print("[4] snap_region =", json.dumps(region, ensure_ascii=False), flush=True)

    ok = True
    if mode == "cancel":
        ok = win.isVisible() and region is None
    else:
        ok = win.isVisible() and bool(region) and region.get("physical", {}).get("width", 0) > 0
    print("结论:", "通过" if ok else "未通过", flush=True)
    ctrl.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
