"""跨屏区域框选：全屏半透明遮罩 + 鼠标拖拽，返回逻辑像素矩形。"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

MIN_SIZE = 24  # 小于该尺寸视为误触，忽略


class RegionSelect(QWidget):
    """拖拽选择屏幕区域的顶层窗口。selection(logical QRect) 信号成功时发射。"""

    selection = Signal(QRect)
    cancelled = Signal()

    def __init__(self, screens=None):
        super().__init__(None)
        # 注意：Qt6 已移除 WindowFullScreenButtonHint；跨屏覆盖只需把几何设为
        # 虚拟桌面范围 + Frameless + 置顶 + Tool(不进任务栏)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setCursor(Qt.CrossCursor)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self._virtual = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(self._virtual)
        self._origin: Optional[QPoint] = None
        self._cur: Optional[QPoint] = None

    # -- 事件 --
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._origin = ev.position().toPoint()
            self._cur = self._origin
            self.update()
        elif ev.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, ev):
        if self._origin is not None:
            self._cur = ev.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._origin is not None:
            rect = self._current_rect()
            self._origin = None
            self._cur = None
            if rect.width() >= MIN_SIZE and rect.height() >= MIN_SIZE:
                self.selection.emit(rect)
                self.close()
            else:
                self._cancel()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self._cancel()

    def _cancel(self):
        self._origin = None
        self._cur = None
        self.cancelled.emit()
        self.close()

    def _current_rect(self) -> QRect:
        if self._origin is None or self._cur is None:
            return QRect()
        x0, y0 = self._origin.x(), self._origin.y()
        x1, y1 = self._cur.x(), self._cur.y()
        return QRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)).intersected(self._virtual)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 外圈压暗
        shade = QColor(0, 0, 0, 150)
        p.fillRect(self.rect(), shade)
        rect = self._current_rect()
        if not rect.isEmpty():
            # 把选中区域“挖”出来：用合成清空整块比较繁琐，
            # 简单做法：浅色高亮框 + 四边描边（半透明遮罩覆盖选中区本身不碍事）
            border = QColor(70, 170, 255, 235)
            pen = QPen(border, 2)
            p.setPen(pen)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            fill = QColor(70, 170, 255, 26)
            p.fillRect(rect, fill)
            # 尺寸标签
            p.setPen(QColor(255, 255, 255))
            label = f"{rect.width()} × {rect.height()}"
            p.drawText(rect.x(), max(10, rect.y() - 8), label)
        p.end()


def pick_region(parent=None, cb=None) -> RegionSelect:
    """显示框选窗口。cb(logical QRect) 成功回调。返回窗口实例以便 show。"""
    win = RegionSelect()
    if cb:
        win.selection.connect(cb)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
