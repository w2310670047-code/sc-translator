"""真实端到端：显示一个英文窗口 -> 抓屏 -> RapidOCR -> 真实 API 翻译。"""
import os
import sys
import time

HOME = os.path.join(os.environ["TEMP"], "sc_snap_e2e", "data")
os.makedirs(HOME, exist_ok=True)
# 借用真实设置与 Key（不污染真实 data\）
import shutil
for n in ("api_key.bin", "settings.json"):
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", n)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(HOME, n))
os.environ["SC_TRANSLATOR_HOME"] = HOME
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from sc_translator.app import AppController
from sc_translator.screen import ScreenInfo, build_layouts, logical_rect_to_physical
from sc_translator.settings import Settings

app = QApplication(sys.argv[:1])

# 1) 造一个"游戏 UI"样子的窗口，放在固定位置
win = QWidget()
win.setWindowTitle("SC test UI")
win.setStyleSheet("background:#0d1117;")
lay = QVBoxLayout(win)
txts = [
    "QUANTUM TRAVEL",
    "Destination: Area18, Stanton System",
    "Bounty hunting is available nearby.",
    "Press F to pay respects, then jump to Pyro.",
]
for i, s in enumerate(txts):
    lb = QLabel(s)
    f = QFont("Segoe UI")
    f.setPointSize(15 if i == 0 else 13)
    f.setBold(i == 0)
    lb.setFont(f)
    lb.setStyleSheet("color:#e6edf3;")
    lay.addWidget(lb)
win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
win.setGeometry(320, 430, 620, 200)
win.show()
for _ in range(12):
    app.processEvents()
    time.sleep(0.05)
win.raise_()
win.activateWindow()
for _ in range(10):
    app.processEvents()
    time.sleep(0.05)

# 2) 用同一套屏幕换算得出物理矩形（模拟框选）
screens = []
for idx, sc in enumerate(QGuiApplication.screens()):
    g = sc.geometry()
    screens.append(ScreenInfo(index=idx, logical=(g.x(), g.y(), g.width(), g.height()), dpr=float(sc.devicePixelRatio())))
layouts = build_layouts(screens)
g = win.geometry()
phys = logical_rect_to_physical(layouts, (g.x(), g.y() - 30, g.width(), g.height() + 30))
print("物理区域:", phys, "DPR:", screens[0].dpr)

# 3) 走真实流水线
settings = Settings().load()
ctrl = AppController(app, settings=settings)
print("API key 已配置:", bool(settings.load_api_key()), "| 模型:", settings.model)
region = {"logical": {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()},
          "physical": phys, "label": "屏幕1"}
res = ctrl.snapshot._work(region, max_lines=20, use_cache=True)
print("\n=== 结果 ===")
print("OCR 用时 %dms，翻译 %dms，合计 %dms，错误=%r" % (res.ocr_ms, res.translate_ms, res.elapsed_ms, res.error))
for src, dst in res.pairs():
    print("  原文: %s" % src)
    print("  译文: %s" % dst)
ctrl.shutdown()
win.hide()
print("\n断言：", "通过" if (len(res.lines) >= 3 and all(l.translated for l in res.lines)) else "未通过（见上）")
