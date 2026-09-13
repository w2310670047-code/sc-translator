"""跨屏区域框选：全屏半透明遮罩 + 鼠标拖拽，返回**全局逻辑像素**矩形。

坐标约定（重要）：selection 发出的是 Qt 全局逻辑坐标（与 settings.snap_region.logical 一致），
不是控件局部坐标——多显示器/虚拟桌面原点不为 0 时两者不同，混用会存下错误区域。
"""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

log = logging.getLogger(__name__)

MIN_SIZE = 24  # 小于该尺寸视为误触，忽略


class RegionSelect(QWidget):
    """拖拽选择屏幕区域的顶层窗口。selection(全局逻辑 QRect) 信号成功时发射。"""

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
        self.setAttribute(Qt.WA_DeleteOnClose, True)   # 关闭即销毁，保证 destroyed 一定发出
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        screen = QGuiApplication.primaryScreen()
        self._virtual = screen.virtualGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        self._origin_at = self._virtual.topLeft()      # 控件原点（全局坐标）
        self.setGeometry(self._virtual)
        self._origin: Optional[QPoint] = None          # 全局坐标
        self._cur: Optional[QPoint] = None             # 全局坐标

    # -- 事件 --
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._origin = ev.globalPosition().toPoint()
            self._cur = self._origin
            log.debug("框选起点(全局) %s", (self._origin.x(), self._origin.y()))
            self.update()
        elif ev.button() == Qt.RightButton:
            self._cancel()

    def mouseMoveEvent(self, ev):
        if self._origin is not None:
            self._cur = ev.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._origin is not None:
            rect = self._current_rect()
            self._origin = None
            self._cur = None
            if rect.width() >= MIN_SIZE and rect.height() >= MIN_SIZE:
                log.info(
                    "框选完成(全局逻辑坐标) x=%d y=%d w=%d h=%d",
                    rect.x(), rect.y(), rect.width(), rect.height(),
                )
                self.selection.emit(rect)
                self.close()
            else:
                log.info("框选过小被忽略: %dx%d", rect.width(), rect.height())
                self._cancel()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self._cancel()

    def _cancel(self):
        self._origin = None
        self._cur = None
        log.info("框选已取消")
        self.cancelled.emit()
        self.close()

    def _current_rect(self) -> QRect:
        """把两个全局坐标点整理成全局矩形（并裁到虚拟桌面范围内）。"""
        if self._origin is None or self._cur is None:
            return QRect()
        x0, y0 = self._origin.x(), self._origin.y()
        x1, y1 = self._cur.x(), self._cur.y()
        rect = QRect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        return rect.intersected(self._virtual) if not self._virtual.isNull() else rect

    def _local_rect(self) -> QRect:
        """把全局矩形换算成控件内部坐标（仅用于绘制）。"""
        rect = self._current_rect()
        if rect.isEmpty():
            return rect
        return rect.translated(-self._origin_at.x(), -self._origin_at.y())

    def moveEvent(self, ev):  # noqa: N802
        self._origin_at = self.geometry().topLeft()
        super().moveEvent(ev)

    def showEvent(self, ev):  # noqa: N802
        # 窗口管理器可能调整过几何，显示时以实际位置为准
        self._origin_at = self.geometry().topLeft()
        log.info("框选窗口显示：geometry=%s virtual=%s",
                 self.geometry().getRect(), self._virtual.getRect())
        super().showEvent(ev)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 外圈压暗
        shade = QColor(0, 0, 0, 150)
        p.fillRect(self.rect(), shade)
        rect = self._local_rect()
        if not rect.isEmpty():
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
    """显示框选窗口。cb(全局逻辑 QRect) 成功回调。返回窗口实例以便 show。"""
    win = RegionSelect()
    if cb:
        win.selection.connect(cb)
    win.show()
    win.raise_()
    win.activateWindow()
    win.setFocus(Qt.OtherFocusReason)   # Tool 窗口有时不会自动获得焦点，手动给一下
    return win
