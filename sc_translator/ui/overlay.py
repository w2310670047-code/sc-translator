"""译文悬浮框（常驻置顶，两态：固定 / 未固定-鼠标穿透）。

数据来源：**按需截图翻译**（Shift+F9 → OCR → 翻译）的结果经 ``push_lines()``
累积到这里，按原文去重、受 ``settings.max_entries`` 限制；不依赖实时巡逻管线
（``pipeline.py`` / ``patrol.py`` 已删除）。

- 未固定（默认，游戏内友好）：**逐区域**鼠标穿透——译文滚动区与回话输入条仍可
  点/可滚/可输入，其余区域（标题栏、边距、提示条…）穿透给下面的游戏
  （实现见 ``nativeEvent``：自己回答 WM_NCHITTEST，非交互区域返回 HTTRANSPARENT）。
  窗边有一个永远可点的小手柄「☰ 固定」——点击即固定，拖动手柄即可移动窗口。
- 固定后：整窗可交互——拖动标题栏移动、右下角缩放、右键菜单、回话输入、
  点标题栏「取消固定」回到穿透态。
- 标题栏上有「穿透：开/关」按钮，与主窗口「鼠标穿透」勾选**双向同步**。
固定/穿透状态与主窗口“鼠标穿透”开关保持同步并持久化。

ctx 需要暴露：``settings``（含 ``save()``）、``mainwin.refresh_overlay_controls()``，
以及可选的 ``translate_reply_async(text, target, done)``（浮窗回话；缺了就提示不可用）。
"""

from __future__ import annotations

import ctypes
import html
import logging
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
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

from ..i18n import t
from .theme import palette, overlay_style

log = logging.getLogger(__name__)

WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1   # 返回给 Windows：这个点不归我，转给下面的窗口



class GripHandle(QWidget):
    """未固定时窗边的小手柄：点击=固定，拖动=移动悬浮窗。"""

    def __init__(self, overlay: "OverlayWindow") -> None:
        super().__init__(None)
        self._ov = overlay
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_QuitOnClose, False)   # 与浮窗一起，不阻止关主窗口时退出
        self.setFixedSize(64, 24)
        self._press: Optional[QPoint] = None
        self._moved = False
        self.setCursor(Qt.OpenHandCursor)

        self._label = QLabel(t("ov.grip"), self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setGeometry(2, 2, 60, 20)
        self._label.setStyleSheet(
            "border-radius:9px; background:rgba(24,29,38,235); color:#46a6ff; font-size:12px; font-weight:600;"
        )
        self.setToolTip(t("ov.grip.tip"))

    def _style_refresh(self) -> None:
        c = palette(self._ov.ctx.settings.theme)
        self._label.setStyleSheet(
            f"border-radius:9px; background:rgba(14,18,24,235); color:{c['accent']}; font-size:12px; font-weight:600;"
        )

    def retranslate(self) -> None:
        """切换界面语言后刷新本手柄文案。"""
        self._label.setText(t("ov.grip"))
        self.setToolTip(t("ov.grip.tip"))

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
        # 浮窗是独立顶层窗口：显式声明它不参与"最后一个窗口关闭"的判定，
        # 这样关掉主窗口时程序照常退出（Qt 对 Tool 窗口默认不加 WA_QuitOnClose）
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self._user_hidden = False
        self._rows: dict[str, QWidget] = {}
        self._row_data: dict[str, dict] = {}                 # 行数据（供「显示原文」等即时重渲染）
        self._exchanges: list[tuple[str, str, str]] = []   # (原文, 译文, 目标语言)
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
        self._title = QLabel(t("ov.title"))
        self._title.setObjectName("ovTitle")
        self._count = QLabel("")
        self._count.setObjectName("ovCount")
        hlay.addWidget(self._title)
        hlay.addWidget(self._count)
        hlay.addStretch(1)
        self._spicy_btn = QPushButton("", self._header)
        self._spicy_btn.setObjectName("ovBtn")
        self._spicy_btn.setToolTip(t("ov.spicy.tip"))
        self._spicy_btn.clicked.connect(lambda: self.set_spicy_mode(not bool(self.ctx.settings.spicy_mode)))
        # 鼠标穿透开关（与主窗口那个勾选同一个设置，双向同步）：
        # 放在标题栏上，这样在浮动窗里就能直接切穿透/固定，不必回主窗口
        self._ct_btn = QPushButton("", self._header)
        self._ct_btn.setObjectName("ovBtn")
        self._ct_btn.setToolTip(t("ovc.click_through.tip"))
        self._ct_btn.clicked.connect(self._toggle_click_through)
        self._pin_btn = QPushButton(t("ov.unpin"), self._header)
        self._pin_btn.setObjectName("ovBtn")
        self._pin_btn.setToolTip(t("ov.pin.tip"))
        self._pin_btn.clicked.connect(lambda: self.set_pinned(False))
        btn_hide = QPushButton("✕", self._header)
        btn_hide.setObjectName("ovBtn")
        btn_hide.setFixedSize(20, 18)
        self._btn_hide = btn_hide
        btn_hide.setToolTip(t("ov.hide.tip"))
        btn_hide.clicked.connect(self._on_hide_clicked)
        hlay.addWidget(self._spicy_btn)
        hlay.addWidget(self._ct_btn)
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
        self._reply_input.setPlaceholderText(t("ov.reply.ph"))
        self._reply_target = QComboBox(top)
        self._reply_target.setObjectName("ovInput")
        self._reply_target.addItems(["English", "Japanese", "Korean"])
        self._reply_target.setFixedWidth(86)
        self._reply_btn = QPushButton(t("ov.reply.btn"), top)
        self._reply_btn.setObjectName("ovBtn")
        self._reply_btn.setToolTip(t("ov.reply.btn.tip"))
        self._reply_clear = QPushButton(t("ov.reply.clear"), top)
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
        # 新行插入后 QScrollArea 的滚动范围是**稍后**才更新的：只靠 singleShot(0) 贴底会拿到
        # 旧 maximum，表现就是"永远差一屏"（实测：推 30 行后 value=0，再推 30 行才跳到上一批的底）。
        # rangeChanged 在范围真的变了时触发，用它兜底才能贴到最新一行。
        self._scroll.verticalScrollBar().rangeChanged.connect(self._on_scroll_range_changed)

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

    def _toggle_click_through(self) -> None:
        """标题栏「穿透」按钮：开=未固定（逐区域穿透），关=固定（整窗可交互）。"""
        self.set_pinned(not self.pinned())

    def _apply_pin_state(self) -> None:
        pinned = self.pinned()
        # 不再用整窗 WA_TransparentForMouseEvents / WS_EX_TRANSPARENT：
        # 那会把回话输入条与译文滚动区一起废掉。穿透改由 nativeEvent 逐区域判定，
        # 所以这里始终让本窗口能收到鼠标事件。
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        # 标题栏/手柄/缩放柄只在固定态需要
        self._header.setVisible(pinned)
        self._grip.setVisible(pinned)
        self._pin_btn.setText(t("ov.unpin") if pinned else t("ov.pin"))
        self._refresh_ct_btn()
        self._floating_grip._style_refresh()
        self._sync_grip_visibility()
        self._floating_grip.place()

    def _refresh_ct_btn(self) -> None:
        """刷新标题栏「穿透」按钮文案/配色（与设置保持一致）。"""
        on = not self.pinned()
        c = palette(self.ctx.settings.theme)
        self._ct_btn.setText(t("ov.click_through.on") if on else t("ov.click_through.off"))
        self._ct_btn.setStyleSheet(
            f"background:transparent;border:none;color:{c['accent'] if on else c['muted']};"
            f"font-size:12px;font-weight:{'700' if on else '400'};"
        )

    # ---------------------------------------------------------- 穿透命中测试
    def _interactive_rects(self) -> list[QRect]:
        """穿透态下仍然接收鼠标的区域：译文滚动区 + 回话输入条。

        其余区域（标题栏、边距、提示条…）继续穿透给下面的游戏。
        """
        rects: list[QRect] = []
        for w in (self._scroll, self._reply_panel):
            if w is None or not w.isVisibleTo(self):
                continue
            rects.append(QRect(w.mapTo(self, QPoint(0, 0)), w.size()))
        return rects

    def is_interactive_point(self, pos: QPoint) -> bool:
        """浮窗本地坐标 ``pos`` 是否该归浮窗处理（False = 穿透给下面的窗口）。"""
        if self.pinned():
            return True
        return any(r.contains(pos) for r in self._interactive_rects())

    def nativeEvent(self, eventType, message):  # noqa: N802 (Qt 命名)
        """穿透态下自己回答 WM_NCHITTEST，实现**逐区域**穿透（仅 Windows）。

        用户实测旧行为的问题：整窗穿透时"回话功能失效、无法滚动"。
        现在可交互区域正常接收鼠标，其余区域返回 HTTRANSPARENT，
        让下面的游戏照常拿到点击与滚轮。
        """
        if self.isVisible() and not self.pinned():
            try:
                if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_NCHITTEST:
                        x = ctypes.c_short(msg.lParam & 0xFFFF).value
                        y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                        if not self.is_interactive_point(self.mapFromGlobal(QPoint(x, y))):
                            return True, HTTRANSPARENT
            except Exception as exc:  # noqa: BLE001
                log.debug("穿透命中测试跳过: %s", exc)
        return super().nativeEvent(eventType, message)

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
        self._show_toast(t("ov.toast.spicy_on") if on else t("ov.toast.spicy_off"), 2500)

    def _refresh_spicy_btn(self) -> None:
        on = bool(self.ctx.settings.spicy_mode)
        danger = palette(self.ctx.settings.theme)["danger"]
        muted = palette(self.ctx.settings.theme)["muted"]
        self._spicy_btn.setText(t("ov.spicy.on") if on else t("ov.spicy.off"))
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
        region = self.ctx.settings.snap_region or {}
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

    def retranslate(self) -> None:
        """切换界面语言后刷新悬浮框内文案（问答记录一并重建以刷新按钮文案）。"""
        self._title.setText(t("ov.title"))
        self._spicy_btn.setToolTip(t("ov.spicy.tip"))
        self._ct_btn.setToolTip(t("ovc.click_through.tip"))
        self._pin_btn.setToolTip(t("ov.pin.tip"))
        self._btn_hide.setToolTip(t("ov.hide.tip"))
        self._reply_input.setPlaceholderText(t("ov.reply.ph"))
        self._reply_btn.setText(t("ov.reply.btn"))
        self._reply_btn.setToolTip(t("ov.reply.btn.tip"))
        self._reply_clear.setText(t("ov.reply.clear"))
        self._floating_grip.retranslate()
        self._refresh_spicy_btn()
        self._apply_pin_state()
        self._rebuild_exchanges()
        self._update_count()

    def clear_all(self) -> None:
        for w in list(self._rows.values()):
            w.setParent(None)
            w.deleteLater()
        self._rows.clear()
        self._row_data.clear()
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

    def set_reply_enabled(self, on: bool) -> None:
        """显示/隐藏回话输入条（受 settings.reply_enabled 控制）。

        **不再**在这里强制切回固定态：旧实现是"回话条一开就固定"，于是用户在
        主窗口勾上「鼠标穿透」（或点浮窗的穿透/取消固定按钮）后，同步路径又会
        调用本函数把它立刻改回去——表现为"穿透开关点了等于没点"（真机复核抓到）。
        现在穿透态下回话条本身就归浮窗处理（见 nativeEvent），输入不受影响。
        """
        self._reply_panel.setVisible(on)

    # ---------------------------------------------------------- 数据
    def push_lines(self, rows: list[dict]) -> None:
        """推入一批译文行（按需截图翻译的结果）。

        每行：``{"key": 行身份, "text": 原文, "translated": 译文, "pending": bool}``。
        **同 key 原地更新、不新增行**（同文去重）；累计行数受 ``settings.max_entries``
        限制，超出时淘汰最早的行。旧版 ``apply_snapshot`` 是"整屏快照、消失即删"，
        那是实时巡逻的语义，与按需截图的历史累积不符，故改写为 upsert。
        """
        s = self.ctx.settings
        # 有新内容时唤醒（用户手动隐藏过就不打扰）
        if not self.isVisible() and not self._user_hidden:
            self.show_overlay()
        for d in rows:
            key = str(d.get("key") or d.get("text") or "").strip()
            if not key:
                continue
            row = self._rows.get(key)
            if row is None:
                row = self._make_row()
                self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)  # 末尾 stretch 之前
                self._rows[key] = row
            self._row_data[key] = d
            self._update_row(row, d, s)
        self._evict_over_max()
        self._update_count()
        # 有新结果就把视图带回最新一行（按需翻译：用户按一次热键就想看最新那几条）
        self._auto_scroll = True
        self._scroll_to_bottom()
        self._bump_idle()

    def _scroll_to_bottom(self) -> None:
        """把译文列表滚到最底部（立即一次 + 布局完成后再补一次）。"""
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())
        QTimer.singleShot(0, lambda: sb.setValue(sb.maximum()))

    def _on_scroll_range_changed(self, _minimum: int, maximum: int) -> None:
        """滚动范围变化（新行布局完成）时贴底——修掉"差一屏"的老毛病。"""
        if self._auto_scroll:
            self._scroll.verticalScrollBar().setValue(maximum)

    def _evict_over_max(self) -> None:
        """超过 settings.max_entries 时淘汰最早的行（dict 保序 = 插入顺序）。"""
        limit = int(self.ctx.settings.max_entries or 0)
        if limit <= 0:
            return
        while len(self._rows) > limit:
            key = next(iter(self._rows))
            row = self._rows.pop(key)
            self._row_data.pop(key, None)
            row.setParent(None)
            row.deleteLater()

    def rerender_rows(self) -> None:
        """按当前设置重渲染已有行（「显示原文」等开关要立即生效，而不是等到下次截图）。"""
        s = self.ctx.settings
        for key, row in self._rows.items():
            d = self._row_data.get(key)
            if d:
                self._update_row(row, d, s)

    def refresh_idle_policy(self) -> None:
        """按当前设置重新评估空闲淡出（「常驻显示」「空闲淡出秒数」改动后调用）。"""
        self._bump_idle()

    def trim_to_limit(self) -> None:
        """立即按 max_entries 裁剪多余行（把上限调小时要马上生效，而不是等下次截图）。"""
        self._evict_over_max()
        self._update_count()

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
            # 「识别中」行必须**总是**带上原文：它是"先出原文、译文稍后替换"的分阶段反馈，
            # 若跟随「显示原文」开关隐藏，这一行就只剩"识别中…"，对用户毫无信息。
            body = f'<span style="color:{pend_color}">{t("ov.pending")}</span>'
            if text:
                body += f'<br/><span style="color:{orig_color}">{html.escape(text)}</span>'
        else:
            shown = translated or text
            body = f'<span style="color:{trans_color}">{html.escape(shown)}</span>'
            if s.show_original and translated and translated != text:
                body += f'<br/><span style="color:{orig_color}">{html.escape(text)}</span>'
        if label.text() != body:
            label.setText(body)

    def _update_count(self) -> None:
        n = len(self._rows)
        region = self.ctx.settings.snap_region
        info = t("ov.lines", n=n)
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
        act_pin = menu.addAction(t("ov.menu.unpin") if self.pinned() else t("ov.menu.pin"))
        act_spicy = menu.addAction(t("ov.menu.spicy_off") if spicy_on else t("ov.menu.spicy_on"))
        menu.addSeparator()
        act_copy = menu.addAction(t("ov.menu.copy"))
        act_clear = menu.addAction(t("ov.menu.clear"))
        act_hide = menu.addAction(t("ov.menu.hide"))
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
            self._show_toast(t("ov.toast.nothing"), 3000)
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._show_toast(t("ov.toast.copied_rows", n=len(lines)), 3000)

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
        self._reply_input.setPlaceholderText(t("ov.reply.busy"))
        handler = getattr(self.ctx, "translate_reply_async", None)
        if handler is None:
            self._reply_input.setPlaceholderText(t("ov.reply.unavailable"))
            self._reply_busy = False
            self._reply_btn.setEnabled(True)
            return

        def done(ok: bool, result: str):
            self._reply_busy = False
            self._reply_btn.setEnabled(True)
            self._reply_input.setPlaceholderText(t("ov.reply.ph"))
            if ok:
                self._add_exchange(text, result, target)
                if self.ctx.settings.auto_copy_reply:
                    self._copy_to_clipboard(result)
                    self._show_toast(t("ov.toast.reply_copied"), 5000)
            else:
                self._show_toast(t("ov.toast.reply_fail", msg=str(result)[:80]), 5000)

        handler(text, target, done)

    # ---- 问答记录 ----
    MAX_EXCHANGES = 8

    def clear_exchanges(self) -> None:
        self._exchanges.clear()
        self._rebuild_exchanges()

    def _rebuild_exchanges(self) -> None:
        """按 self._exchanges 重建问答记录区（切换语言时也要重建以刷新按钮文案）。"""
        while self._exch_lay.count() > 1:  # 保留末尾 stretch
            item = self._exch_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for original, reply, target in self._exchanges:
            card = self._make_exchange_row(original, reply, target)
            self._exch_lay.insertWidget(self._exch_lay.count() - 1, card)

    def _add_exchange(self, original: str, reply: str, target: str) -> None:
        """记录一条问答对；超过 MAX_EXCHANGES 时丢弃最早一条。"""
        self._exchanges.append((original, reply, target))
        while len(self._exchanges) > self.MAX_EXCHANGES:
            self._exchanges.pop(0)
        self._rebuild_exchanges()
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
        b_copy = QPushButton(t("ov.exch.copy_reply"), card)
        b_copy.setObjectName("ovBtn")
        b_copy.setToolTip(t("ov.exch.copy_reply.tip"))
        b_copy.clicked.connect(lambda: self._copy_to_clipboard(reply, t("ov.toast.copied_reply")))
        b_orig = QPushButton(t("ov.exch.copy_orig"), card)
        b_orig.setObjectName("ovBtn")
        b_orig.clicked.connect(lambda: self._copy_to_clipboard(original, t("ov.toast.copied_orig")))
        brow.addWidget(b_orig)
        brow.addWidget(b_copy)
        lay.addLayout(brow)
        return card

    def _copy_to_clipboard(self, text: str, toast: str | None = None) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        if toast:
            self._show_toast(toast, 3000)
