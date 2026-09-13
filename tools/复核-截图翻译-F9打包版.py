"""打包版 F9 端到端探针：

1. 在屏幕上显示一个英文"游戏 UI"窗口（置顶，位置与配置里的截图区域一致）；
2. 用 ctypes 注入一次真实的 F9 按键（全局热键会收到）；
3. 等待打包版完成 OCR + 翻译。

配合已启动的 SCTranslator.exe --home=<准备好的目录> 使用。
"""

import ctypes
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

VK_F9 = 0x78
KEYEVENTF_KEYUP = 0x0002

app = QApplication(sys.argv[:1])
win = QWidget()
win.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
win.setStyleSheet("background:#0d1117;")
lay = QVBoxLayout(win)
for i, s in enumerate([
    "QUANTUM TRAVEL",
    "Destination: Area18, Stanton System",
    "Bounty hunting is available nearby.",
    "Press F to pay respects, then jump to Pyro.",
]):
    lb = QLabel(s)
    f = QFont("Segoe UI")
    f.setPointSize(15 if i == 0 else 13)
    f.setBold(i == 0)
    lb.setFont(f)
    lb.setStyleSheet("color:#e6edf3;")
    lay.addWidget(lb)
win.setGeometry(320, 430, 620, 200)
win.show()
win.raise_()
win.activateWindow()
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)

print("窗口 frame:", win.frameGeometry().getRect(), "可见:", win.isVisible(), flush=True)
time.sleep(1.5)

print("注入 F9 ...", flush=True)
u32 = ctypes.windll.user32
u32.keybd_event(VK_F9, 0, 0, 0)
time.sleep(0.05)
u32.keybd_event(VK_F9, 0, KEYEVENTF_KEYUP, 0)

# 保持窗口在屏幕上，等打包版完成抓屏 + OCR + 翻译
end = time.time() + 20
while time.time() < end:
    app.processEvents()
    time.sleep(0.05)
print("探针结束", flush=True)
