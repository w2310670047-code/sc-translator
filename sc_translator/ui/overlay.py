"""置顶悬浮译文框（两态：固定 / 未固定-鼠标穿透）。

- 未固定（默认，游戏内友好）：整窗鼠标穿透不挡操作；
  窗边有一个永远可点的小手柄「☰ 固定」——点击即固定，拖动手柄即可移动窗口。
- 固定后：整窗可交互——拖动标题栏移动、右下角缩放、右键菜单、回话输入、
  点标题栏「取消固定」回到穿透态。
固定/穿透状态与主窗口“鼠标穿透”开关保持同步并持久化。
"""

from __future__ import annotations

import ctypes
import html
import logging
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QMouseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import palette, overlay_style

log = logging.getLogger(__name__)

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20

_user32 = ctypes.windll.user32


def _set_click_through(hwnd: int, on: bool) -> None:
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if on:
        style |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        style &= ~WS_EX_TRANSPARENT
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class GripHandle(QWidget):
    """未固定时窗边的小手柄：点击=固定，拖动=移动悬浮窗。"""

    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__(None)
        self._ov = overlay
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(64, 24)
        self._press: Optional[QPoint] = None
        self._moved = False
        self.setCursor(Qt.OpenHandCursor)

        self._label = QLabel("☰ 固定", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setGeometry(2, 2, 60, 20)
        self._label.setStyleSheet(
            "border-radius:9px; background:rgba(24,29,38,235); color:#46a6ff; font-size:12px; font-weight:600;"
        )
        self.setToolTip("点击：固定悬浮框（可交互/拖动）；按住拖动：移动悬浮框")

    def _style_refresh(self) -> None:
        c = palette(self._ov.ctx.settings.theme)
        self._label.setStyleSheet(
            f"border-radius:9px; background:rgba(14,18,24,235); color:{c['accent']}; font-size:12px; font-weight:600;"
        )

    # ---- 拖动/点击 ----
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self._press = ev.globalPosition().toPoint()
            self._moved = False
            self._win0 = self._ov.pos()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._press is None:
            return
        delta = ev.globalPosition().toPoint() - self._press
        if delta.manhattanLength() > 3:
            self._moved = True
            self._ov.move(self._win0 + delta)
            self.move(self._ov.x() + self._ox(), self._ov.y() + self._oy())
            self._ov._position_dirty()

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self.setCursor(Qt.OpenHandCursor)
        if self._press is None:
            return
        was_moved = self._moved
        self._press = None
        if not was_moved and ev.button() == Qt.LeftButton:
            self._ov.set_pinned(True)   # 点击 -> 固定（可交互）
        else:
            self._ov._save_geometry()

    # 手柄相对悬浮窗的偏移（右上角）
    def _ox(self) -> int:
        return self._ov.width() - self.width() - 6

    def _oy(self) -> int:
        screen = QGuiApplication.screenAt(self._ov.frameGeometry().center())
        avail = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        if self._ov.y() - self.height() + 4 >= avail.y():
            return -self.height() + 4    # 悬浮在窗上方
        return 4                         # 屏幕顶边附近时贴窗内右上角

    def place(self) -> None:
        ov = self._ov
        self.move(ov.x() + self._ox(), ov.y() + self._oy())
        self.raise_()


class OverlayWindow(QWidget):
    """ctx 需要暴露：settings、settings.save()、on_reply_send(text, target) 回调。"""

    cleared = Signal()
    visible_changed = Signal(bool)

    def __init__(self, ctx) -> None:
        super().__init__(None)
        self.ctx = ctx
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # 初始即穿透，按设置覆盖
        self._user_hidden = False
        self._rows: dict[str, QWidget] = {}
        self._pending_show = False

        # ------- 结构 -------
        self._wrap = QFrame(self)
        self._wrap.setObjectName("ovWrap")
        self._wrap.setContextMenuPolicy(Qt.CustomContextMenu)
        self._wrap.customContextMenuRequested.connect(self._show_menu)

        wlay = QVBoxLayout(self._wrap)
        wlay.setContentsMargins(10, 8, 10, 8)
        wlay.setSpacing(6)

        # 标题栏（固定态拖动用；未固定态隐藏）
        self._header = QFrame(self._wrap)
        self._header.setObjectName("ovHeader")
        hlay = QHBoxLayout(self._header)
        hlay.setContentsMargins(2, 0, 0, 0)
        hlay.setSpacing(4)
        self._title = QLabel("★ SC 译文")
        self._title.setObjectName("ovTitle")
        self._count = QLabel("")
        self._count.setObjectName("ovCount")
        hlay.addWidget(self._title)
        hlay.addWidget(self._count)
        hlay.addStretch(1)
        self._spicy_btn = QPushButton("", self._header)
        self._spicy_btn.setObjectName("ovBtn")
        self._spicy_btn.setToolTip("嘴臭模式：开=译文用嘴臭提示词；关=用正常提示词（随开关即时生效）")
        self._spicy_btn.clicked.connect(lambda: self.set_spicy_mode(not bool(self.ctx.settings.spicy_mode)))
        self._pin_btn = QPushButton("取消固定", self._header)
        self._pin_btn.setObjectName("ovBtn")
        self._pin_btn.setToolTip("回到鼠标穿透状态（游戏内不挡操作）")
        self._pin_btn.clicked.connect(lambda: self.set_pinned(False))
        btn_hide = QPushButton("✕", self._header)
        btn_hide.setObjectName("ovBtn")
        btn_hide.setFixedSize(20, 18)
        btn_hide.setToolTip("隐藏悬浮框（内容更新时自动重现）")
        btn_hide.clicked.connect(self._on_hide_clicked)
        hlay.addWidget(self._spicy_btn)
        hlay.addWidget(self._pin_btn)
        hlay.addWidget(btn_hide)
        wlay.addWidget(self._header)

        # 行列表
        self._scroll = QScrollArea(self._wrap)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rows_host = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 0, 0, 0)
        self._rows_lay.setSpacing(4)
        self._rows_lay.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        wlay.addWidget(self._scroll, 1)

        # ---------- 回话面板：问答对（原文+回复）同时显示，可一键/手动复制 ----------
        self._reply_panel = QFrame(self._wrap)
        rplay = QVBoxLayout(self._reply_panel)
        rplay.setContentsMargins(0, 2, 0, 0)
        rplay.setSpacing(4)

        # 顶部一行：标题 + 输入
        top = QFrame(self._reply_panel)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        self._reply_input = QLineEdit(top)
        self._reply_input.setObjectName("ovInput")
        self._reply_input.setPlaceholderText("输入中文回话，Enter 翻译…")
        self._reply_target = QComboBox(top)
        self._reply_target.setObjectName("ovInput")
        self._reply_target.addItems(["English", "Japanese", "Korean"])
        self._reply_target.setFixedWidth(86)
        self._reply_btn = QPushButton("翻译", top)
        self._reply_btn.setObjectName("ovBtn")
        self._reply_btn.setToolTip("翻译输入的中文并加入下方问答记录")
        self._reply_clear = QPushButton("清空记录", top)
        self._reply_clear.setObjectName("ovBtn")
        tl.addWidget(self._reply_input, 1)
        tl.addWidget(self._reply_target)
        tl.addWidget(self._reply_btn)
        tl.addWidget(self._reply_clear)
        rplay.addWidget(top)

        # 问答记录区（原文 / 回复 同时可见，文本可选中，一键复制按钮）
        self._exch_scroll = QScrollArea(self._reply_panel)
        self._exch_scroll.setWidgetResizable(True)
        self._exch_scroll.setFrameShape(QFrame.NoFrame)
        self._exch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._exch_scroll.setMaximumHeight(170)
        self._exch_host = QWidget()
        self._exch_lay = QVBoxLayout(self._exch_host)
        self._exch_lay.setContentsMargins(0, 0, 0, 0)
        self._exch_lay.setSpacing(4)
        self._exch_lay.addStretch(1)
        self._exch_scroll.setWidget(self._exch_host)
        rplay.addWidget(self._exch_scroll)

        self._reply_panel.hide()
        wlay.addWidget(self._reply_panel)

        # 模式切换提示条（嘴臭开关/复制等状态变更时短暂显示）
        self._counter_toast = QLabel("", self._wrap)
        self._counter_toast.setObjectName("ovCount")
        self._counter_toast.setWordWrap(True)
        self._counter_toast.setAlignment(Qt.AlignLeft)
        self._counter_toast.hide()
        wlay.addWidget(self._counter_toast)
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: self._counter_toast.hide())

        self._reply_input.returnPressed.connect(self._send_reply)
        self._reply_btn.clicked.connect(self._send_reply)
        self._reply_clear.clicked.connect(self.clear_exchanges)

        # 右下角缩放手柄（固定态用）
        self._grip = QFrame(self._wrap)
        self._grip.setFixedSize(14, 14)
        self._grip.setCursor(Qt.SizeFDiagCursor)
        self._grip.mousePressEvent = self._grip_press
        self._grip.mouseMoveEvent = self._grip_move
        self._grip.mouseReleaseEvent = self._grip_release

        # 空闲淡出定时器
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._on_idle_timeout)

        self._auto_scroll = True
        self._scroll.verticalScrollBar().valueChanged.connect(self._track_scroll)

        # 未固定时的拖动手柄（独立小窗，可点可拖）
        self._floating_grip = GripHandle(self)

        self._style_refresh()
        self._restore_geometry()

        # 拖拽
        self._drag_offset: Optional[QPoint] = None
        self._header.mousePressEvent = self._header_press
        self._header.mouseMoveEvent = self._header_move
        self._header.mouseReleaseEvent = self._header_release

        # 回复异步完成
        self._reply_busy = False

    # ---------------------------------------------------------- 状态
    def pinned(self) -> bool:
        return not bool(self.ctx.settings.click_through)

    def set_pinned(self, pinned: bool, notify_main: bool = True) -> None:
        """pinned=True 固定（可交互）；False 回到穿透态。"""
        self.ctx.settings.click_through = not pinned
        self.ctx.settings.save()
        self._apply_pin_state()
        if notify_main and self.ctx.mainwin is not None:
            self.ctx.mainwin.refresh_overlay_controls()

    def _apply_pin_state(self) -> None:
        pinned = self.pinned()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not pinned)
        # 标题栏/手柄/缩放柄只在固定态需要
        self._header.setVisible(pinned)
        self._grip.setVisible(pinned)
        self._pin_btn.setText("取消固定" if pinned else "固定")
        self._floating_grip._style_refresh()
        if self.isVisible():
            hwnd = int(self.winId())
            _set_click_through(hwnd, not pinned)
        self._sync_grip_visibility()
        self._floating_grip.place()

    def _sync_grip_visibility(self) -> None:
        show_grip = self.isVisible() and not self.pinned() and not self._user_hidden
        if show_grip:
            self._floating_grip.place()
            self._floating_grip.show()
            self._floating_grip.raise_()
        else:
            self._floating_grip.hide()

    def set_spicy_mode(self, on: bool, notify_main: bool = True) -> None:
        """嘴臭模式开关（与主窗口同步）。开启=译文用嘴臭提示词；关闭=正常提示词。"""
        self.ctx.settings.spicy_mode = bool(on)
        self.ctx.settings.save()
        self._refresh_spicy_btn()
        if notify_main and self.ctx.mainwin is not None:
            self.ctx.mainwin.refresh_overlay_controls()
        self._show_toast("嘴臭模式已开启：译文用嘴臭提示词" if on else "嘴臭模式已关闭：恢复正常翻译", 2500)

    def _refresh_spicy_btn(self) -> None:
        on = bool(self.ctx.settings.spicy_mode)
        danger = palette(self.ctx.settings.theme)["danger"]
        muted = palette(self.ctx.settings.theme)["muted"]
        self._spicy_btn.setText("😤 嘴臭：开" if on else "😶 嘴臭：关")
        self._spicy_btn.setStyleSheet(
            f"background:transparent;border:none;color:{danger if on else muted};"
            f"font-size:12px;font-weight:{'700' if on else '400'};"
        )

    def _show_toast(self, text: str, ms: int = 8000) -> None:
        self._counter_toast.setText(text)
        self._counter_toast.show()
        self._toast_timer.start(ms)

    # ---------------------------------------------------------- 样式/几何
    def _style_refresh(self) -> None:
        s = self.ctx.settings
        theme = s.theme
        self.setStyleSheet(overlay_style(theme, s.opacity, s.font_size))
        c = palette(theme)
        self._title.setStyleSheet(f"color:{c['accent']};")
        self._floating_grip._style_refresh()
        if getattr(self, "_spicy_btn", None) is not None:
            self._refresh_spicy_btn()

    def _restore_geometry(self) -> None:
        g = self.ctx.settings.overlay_geometry
        if g:
            geo = self.geometry()
            geo.setRect(g.get("x", geo.x()), g.get("y", geo.y()), g.get("w", 420), g.get("h", 320))
            self.setGeometry(geo)
        else:
            self._default_geometry()

    def _default_geometry(self) -> None:
        region = self.ctx.settings.region or {}
        screen = QGuiApplication.screenAt(QGuiApplication.primaryScreen().geometry().center())
        avail = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        lg = region.get("logical")
        if lg:
            x = min(lg["x"] + lg["w"] + 14, avail.right() - 420)
            y = lg["y"]
        else:
            x, y = avail.x() + 60, avail.y() + 60
        self.setGeometry(max(x, avail.x()), max(y, avail.y()), 420, 300)

    def _save_geometry(self) -> None:
        g = self.geometry()
        self.ctx.settings.overlay_geometry = {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()}
        self.ctx.settings.save()

    def _position_dirty(self) -> None:
        # 拖动期间跟随（几何变化时已会触发 moveEvent 同步手柄）
        pass

    # ---------------------------------------------------------- 外部接口
    def apply_theme(self) -> None:
        self._style_refresh()

    def apply_click_through(self) -> None:
        """兼容旧调用：按当前设置同步穿透/固定态。"""
        self._apply_pin_state()

    def clear_all(self) -> None:
        for w in list(self._rows.values()):
            w.setParent(None)
            w.deleteLater()
        self._rows.clear()
        self._update_count()
        self.cleared.emit()

    def show_overlay(self) -> None:
        self._user_hidden = False
        self.show()
        self.raise_()
        self._apply_pin_state()
        self.visible_changed.emit(True)
        self._bump_idle()

    def hide_overlay(self) -> None:
        self._floating_grip.hide()
        self.hide()
        self.visible_changed.emit(False)

    def pipeline_started(self) -> None:
        self.clear_all()
        self._user_hidden = False
        self.show_overlay()

    def pipeline_stopped(self) -> None:
        self._idle.stop()
        self.setWindowOpacity(1.0)

    def set_reply_enabled(self, on: bool) -> None:
        self._reply_panel.setVisible(on)
        if on:
            # 回话需要键盘输入，自动切到固定态
            if not self.pinned():
                self.set_pinned(True)

    # ---------------------------------------------------------- 数据
    def apply_snapshot(self, snaps: list[dict]) -> None:
        s = self.ctx.settings
        # 新内容时唤醒
        if not self.isVisible() and not self._user_hidden:
            self.show_overlay()
        order: list[str] = []
        for i, d in enumerate(snaps):
            key = d["key"]
            order.append(key)
            row = self._rows.get(key)
            if row is None:
                row = self._make_row()
                self._rows_lay.insertWidget(i, row)
                self._rows[key] = row
            else:
                cur = self._rows_lay.indexOf(row)
                if cur != i:
                    self._rows_lay.removeWidget(row)
                    self._rows_lay.insertWidget(i, row)
            self._update_row(row, d, s)
        # 移除已消失的行
        for key in list(self._rows):
            if key not in order:
                row = self._rows.pop(key)
                row.setParent(None)
                row.deleteLater()
        self._update_count()
        if self._auto_scroll:
            sb = self._scroll.verticalScrollBar()
            QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))
        self._bump_idle()

    def _make_row(self) -> QFrame:
        row = QFrame()
        row.setObjectName("ovRow")
        lay = QVBoxLayout(row)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(2)
        label = QLabel(row)
        label.setWordWrap(True)
        label.setObjectName("ovRowTrans")
        lay.addWidget(label)
        return row

    def _update_row(self, row: QFrame, d: dict, s) -> None:
        label = row.findChild(QLabel)
        if label is None:
            return
        text = (d.get("text") or "").strip()
        translated = (d.get("translated") or "").strip()
        pending = bool(d.get("pending"))
        c = palette(s.theme)
        orig_color, trans_color, pend_color = c["muted"], c["text"], c["warn"]
        if pending:
            body = (
                f'<span style="color:{pend_color}">… 翻译中 …</span>'
                + (f'<br/><span style="color:{orig_color}">{html.escape(text)}</span>' if s.show_original else "")
            )
        else:
            shown = translated or text
            body = f'<span style="color:{trans_color}">{html.escape(shown)}</span>'
            if s.show_original and translated and translated != text:
                body += f'<br/><span style="color:{orig_color}">{html.escape(text)}</span>'
        if label.text() != body:
            label.setText(body)

    def _update_count(self) -> None:
        n = len(self._rows)
        region = self.ctx.settings.region
        info = f"{n} 行"
        if region and region.get("label"):
            info += f" · {region['label']}"
        self._count.setText(info)

    # ---------------------------------------------------------- 交互
    def _on_hide_clicked(self) -> None:
        self._user_hidden = True
        self.hide_overlay()

    def _bump_idle(self) -> None:
        s = self.ctx.settings
        if s.auto_hide_sec > 0 and not s.always_show:
            self._idle.start(int(s.auto_hide_sec * 1000))

    def _on_idle_timeout(self) -> None:
        if self.isVisible() and self.ctx.settings.auto_hide_sec > 0 and not self.ctx.settings.always_show:
            self.hide_overlay()
            self._user_hidden = False  # 淡出后由新内容唤醒

    def _track_scroll(self, _v) -> None:
        sb = self._scroll.verticalScrollBar()
        self._auto_scroll = sb.value() >= sb.maximum() - 4

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._wrap.setGeometry(self.rect())
        self._grip.move(self._wrap.width() - 22, self._wrap.height() - 22)
        self._grip.raise_()
        if self._floating_grip.isVisible():
            self._floating_grip.place()

    def moveEvent(self, ev) -> None:
        super().moveEvent(ev)
        if self._floating_grip.isVisible():
            self._floating_grip.place()

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        self._wrap.setGeometry(self.rect())
        self._grip.move(self._wrap.width() - 22, self._wrap.height() - 22)
        self._grip.raise_()
        # show 之后 winId 有效再应用扩展样式
        QTimer.singleShot(0, self._apply_pin_state)

    # --- 标题栏拖拽（固定态） ---
    def _header_press(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton:
            self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _header_move(self, ev: QMouseEvent):
        if self._drag_offset is not None:
            self.move(ev.globalPosition().toPoint() - self._drag_offset)

    def _header_release(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._save_geometry()

    # --- 缩放 ---
    def _grip_press(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton:
            self._grip._start = ev.globalPosition().toPoint()
            self._grip._geo = self.geometry()

    def _grip_move(self, ev: QMouseEvent):
        st = getattr(self._grip, "_start", None)
        if st is not None:
            delta = ev.globalPosition().toPoint() - st
            geo = self._grip._geo
            self.setGeometry(geo.x(), geo.y(), max(240, geo.width() + delta.x()), max(120, geo.height() + delta.y()))

    def _grip_release(self, ev: QMouseEvent):
        self._grip._start = None
        self._save_geometry()

    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        spicy_on = bool(self.ctx.settings.spicy_mode)
        act_pin = menu.addAction("回到穿透/未固定" if self.pinned() else "固定（可交互拖动）")
        act_spicy = menu.addAction("关闭嘴臭模式(恢复正常)" if spicy_on else "开启嘴臭模式")
        menu.addSeparator()
        act_copy = menu.addAction("复制全部译文")
        act_clear = menu.addAction("清空")
        act_hide = menu.addAction("隐藏悬浮框")
        act = menu.exec(self._wrap.mapToGlobal(pos))
        if act == act_pin:
            self.set_pinned(not self.pinned())
        elif act == act_spicy:
            self.set_spicy_mode(not spicy_on)
        elif act == act_copy:
            self._copy_all()
        elif act == act_clear:
            self.clear_all()
        elif act == act_hide:
            self._on_hide_clicked()

    @staticmethod
    def _html_to_plain(html_text: str) -> str:
        """去掉富文本标签，转成纯文本（复制用）。"""
        import re

        text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.I)
        text = re.sub(r"<[^>]+>", "", text)
        return html.unescape(text)

    def _copy_all(self) -> None:
        lines = []
        for row in self._rows.values():
            label = row.findChild(QLabel)
            if label and label.text():
                t = self._html_to_plain(label.text()).strip()
                if t:
                    lines.append(t)
        text = "\n".join(lines)
        if not text:
            self._show_toast("没有可复制的内容（当前无译文行）", 3000)
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._show_toast(f"✅ 已复制 {len(lines)} 行译文", 3000)

    # ---------------------------------------------------------- 回话（问答对）
    def _send_reply(self) -> None:
        """把输入的中文翻译为外文，生成一条【原文+回复】问答对显示在悬浮窗。
        自动复制开关开启时复制译文；否则可点该问答对的复制按钮或手动选中文本复制。"""
        text = self._reply_input.text().strip()
        if not text or self._reply_busy:
            return
        target = self._reply_target.currentText()
        self._reply_busy = True
        self._reply_btn.setEnabled(False)
        self._reply_input.clear()
        self._reply_input.setPlaceholderText("翻译中…")
        handler = getattr(self.ctx, "translate_reply_async", None)
        if handler is None:
            self._reply_input.setPlaceholderText("回话功能不可用")
            self._reply_busy = False
            self._reply_btn.setEnabled(True)
            return

        def done(ok: bool, result: str):
            self._reply_busy = False
            self._reply_btn.setEnabled(True)
            self._reply_input.setPlaceholderText("输入中文回话，Enter 翻译…")
            if ok:
                self._add_exchange(text, result, target)
                if self.ctx.settings.auto_copy_reply:
                    self._copy_to_clipboard(result)
                    self._show_toast("✅ 回复已生成并复制到剪贴板，回游戏 Ctrl+V 粘贴发送", 5000)
            else:
                self._show_toast(f"翻译失败：{result[:80]}", 5000)

        handler(text, target, done)

    # ---- 问答记录 ----
    MAX_EXCHANGES = 8

    def clear_exchanges(self) -> None:
        while self._exch_lay.count() > 1:  # 保留末尾 stretch
            item = self._exch_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _add_exchange(self, original: str, reply: str, target: str) -> None:
        # 超过上限移除最早一条
        widgets = [self._exch_lay.itemAt(i).widget() for i in range(self._exch_lay.count() - 1)]
        widgets = [w for w in widgets if w is not None]
        while len(widgets) >= self.MAX_EXCHANGES:
            w = widgets.pop(0)
            self._exch_lay.removeWidget(w)
            w.setParent(None)
            w.deleteLater()

        card = self._make_exchange_row(original, reply, target)
        self._exch_lay.insertWidget(self._exch_lay.count() - 1, card)
        sb = self._exch_scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))
        self._bump_idle()

    def _make_exchange_row(self, original: str, reply: str, target: str) -> QFrame:
        c = palette(self.ctx.settings.theme)
        card = QFrame()
        card.setStyleSheet(
            f"QFrame#x{{background:{c['row_bg']};border-radius:6px;}}"
            f"QLabel#xo{{color:{c['muted']};}}"
            f"QLabel#xr{{color:{c['text']};}}"
        )
        card.setObjectName("x")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(2)

        # 原文（可选中，手动复制）——纯文本，避免把 ' 等转义成 &#x27; 实体显示
        orig_lbl = QLabel(original, card)
        orig_lbl.setObjectName("xo")
        orig_lbl.setWordWrap(True)
        orig_lbl.setTextFormat(Qt.PlainText)
        orig_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(orig_lbl)
        # 回复（可选中）——同上纯文本
        reply_lbl = QLabel(reply, card)
        reply_lbl.setObjectName("xr")
        reply_lbl.setWordWrap(True)
        reply_lbl.setTextFormat(Qt.PlainText)
        reply_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(reply_lbl)

        brow = QHBoxLayout()
        brow.setContentsMargins(0, 0, 0, 0)
        brow.setSpacing(6)
        tag = QLabel(f"→ {target}", card)
        tag.setStyleSheet(f"color:{c['accent']};font-size:11px;")
        brow.addWidget(tag)
        brow.addStretch(1)
        b_copy = QPushButton("一键复制译文", card)
        b_copy.setObjectName("ovBtn")
        b_copy.setToolTip("把生成的回复复制到剪贴板")
        b_copy.clicked.connect(lambda: self._copy_to_clipboard(reply, "✅ 已复制译文"))
        b_orig = QPushButton("复制原文", card)
        b_orig.setObjectName("ovBtn")
        b_orig.clicked.connect(lambda: self._copy_to_clipboard(original, "✅ 已复制原文"))
        brow.addWidget(b_orig)
        brow.addWidget(b_copy)
        lay.addLayout(brow)
        return card

    def _copy_to_clipboard(self, text: str, toast: str | None = None) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        if toast:
            self._show_toast(toast, 3000)
