"""截图翻译结果浮窗：鼠标旁半透明置顶小窗，显示原文 + 译文。

行为：
- 无边框、置顶、半透明；出现在鼠标附近并自动避开屏幕边缘；
- 默认 8 秒后自动淡出（可设置），鼠标移入时暂停倒计时；
- 可拖动、可固定（固定后不自动淡出）；「复制全部」把"原文 → 译文"写进剪贴板；
- 内容只读但可选中，方便只复制某一行。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t

log = logging.getLogger(__name__)


class SnapPopup(QWidget):
    """一次性截图翻译结果浮窗。"""

    copyRequested = Signal(str)
    closed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.96)
        self._pinned = False
        self._drag_from: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "#card{background:rgba(16,20,27,0.94);border:1px solid #2a3342;border-radius:10px;}"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        self._title = QLabel(t("snap.popup_title"))
        self._title.setStyleSheet("color:#e3e9f2;font-size:13px;font-weight:600;")
        head.addWidget(self._title)
        head.addStretch(1)
        self._btn_pin = QPushButton(t("snap.popup_pin"))
        self._btn_pin.setFixedHeight(22)
        self._btn_pin.clicked.connect(self._toggle_pin)
        head.addWidget(self._btn_pin)
        self._btn_copy = QPushButton(t("snap.popup_copy"))
        self._btn_copy.setFixedHeight(22)
        self._btn_copy.clicked.connect(self._copy_all)
        head.addWidget(self._btn_copy)
        self._btn_close = QPushButton("✕")
        self._btn_close.setFixedSize(24, 22)
        self._btn_close.clicked.connect(self.hide_popup)
        head.addWidget(self._btn_close)
        lay.addLayout(head)

        self._body = QPlainTextEdit()
        self._body.setReadOnly(True)
        self._body.setMinimumSize(360, 120)
        self._body.setMaximumHeight(460)
        self._body.setStyleSheet(
            "QPlainTextEdit{background:#0d1116;color:#e3e9f2;border:1px solid #2a3342;"
            "border-radius:6px;font-size:13px;padding:6px;}"
        )
        lay.addWidget(self._body)

        self._hint = QLabel("")
        self._hint.setStyleSheet("color:#93a0b0;font-size:11px;")
        lay.addWidget(self._hint)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._auto_hide)
        self._auto_hide_sec = 8

    # ---------------- 展示 ----------------
    def show_result(self, pairs: list[tuple[str, str]], note: str = "", auto_hide_sec: int = 8) -> None:
        """pairs = [(原文, 译文), ...]；note 会显示在底部（错误/耗时等）。"""
        self._auto_hide_sec = max(0, int(auto_hide_sec))
        chunks: list[str] = []
        for src, dst in pairs:
            if dst and dst != src:
                chunks.append(f"{src}\n→ {dst}")
            else:
                chunks.append(src)
        self._body.setPlainText("\n\n".join(chunks))
        self._body.moveCursor(self._body.textCursor().MoveOperation.Start)
        self._hint.setText(note)
        self._title.setText(t("snap.popup_title") + f" ({len(pairs)})")
        self._place_near_cursor()
        self.show()
        self.raise_()
        self._restart_timer()

    def show_message(self, text: str, auto_hide_sec: int = 5) -> None:
        self._body.setPlainText(text)
        self._hint.setText("")
        self._title.setText(t("snap.popup_title"))
        self._place_near_cursor()
        self.show()
        self.raise_()
        self._restart_timer(auto_hide_sec)

    def _restart_timer(self, sec: int | None = None) -> None:
        self._timer.stop()
        if self._pinned:
            return
        s = self._auto_hide_sec if sec is None else max(0, int(sec))
        if s > 0:
            self._timer.start(s * 1000)

    def _auto_hide(self) -> None:
        if self._pinned or self.underMouse():
            self._restart_timer()
            return
        self.hide_popup()

    def hide_popup(self) -> None:
        self._timer.stop()
        self.hide()
        self.closed.emit()

    # ---------------- 交互 ----------------
    def _toggle_pin(self) -> None:
        self._pinned = not self._pinned
        self._btn_pin.setText(t("snap.popup_unpin") if self._pinned else t("snap.popup_pin"))
        if self._pinned:
            self._timer.stop()
        else:
            self._restart_timer()

    def _copy_all(self) -> None:
        self.copyRequested.emit(self._body.toPlainText())

    def enterEvent(self, ev) -> None:  # noqa: N802
        self._timer.stop()
        super().enterEvent(ev)

    def leaveEvent(self, ev) -> None:  # noqa: N802
        self._restart_timer()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_from = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag_from is not None and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_from)
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        self._drag_from = None
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev) -> None:  # noqa: N802
        if ev.key() == Qt.Key.Key_Escape:
            self.hide_popup()
            return
        super().keyPressEvent(ev)

    # ---------------- 定位 ----------------
    def _place_near_cursor(self) -> None:
        self.adjustSize()
        pos = QCursor.pos()
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = pos.x() + 16
        y = pos.y() + 16
        if x + w > area.right():
            x = max(area.left(), pos.x() - w - 16)
        if y + h > area.bottom():
            y = max(area.top(), pos.y() - h - 16)
        self.move(x, y)
