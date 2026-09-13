"""通用小控件。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .theme import palette


def make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """返回统一外观的卡片容器及其布局。"""
    card = QFrame()
    card.setObjectName("card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 10, 12, 12)
    lay.setSpacing(8)
    from PySide6.QtWidgets import QLabel

    if title:
        lbl = QLabel(title)
        lbl.setObjectName("cardTitle")
        lay.addWidget(lbl)
    return card, lay


class HotkeyEdit(QLineEdit):
    """热键录入框：点一下，直接按组合键即可（不接受手打文本）。

    为什么必须这样做：如果只是个普通文本框，用户"点进去按 F9"时代码看到的是
    文本框的按键，而**全局热键同时也会被系统触发**（于是去截图、甚至弹出框选把主窗口藏起来）。
    因此本控件：
    - 只读（禁止乱打字），按键事件自己接管；
    - 获得焦点时通过 ``on_edit_start`` 通知外部**临时注销全局热键**，失焦时 ``on_edit_done`` 恢复；
    - 只接受合法组合（纯字母/数字必须带修饰键，F1-F24 等命名键可单按）；
    - Esc 取消编辑，恢复原值。
    """

    captured = Signal(str)

    def __init__(self, spec: str = "", on_edit_start=None, on_edit_done=None, parent=None):
        super().__init__(parent)
        self.setText(spec)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按组合键")
        self.setToolTip("点击这里，然后按下你想用的组合键（Esc 取消）。")
        self._on_edit_start = on_edit_start
        self._on_edit_done = on_edit_done
        self._editing = False
        self._spec = spec

    def spec(self) -> str:
        return self._spec

    def setSpec(self, spec: str) -> None:
        self._spec = spec
        self.setText(spec)

    # -- 事件 --
    def focusInEvent(self, ev):  # noqa: N802
        super().focusInEvent(ev)
        if not self._editing:
            self._editing = True
            self.setStyleSheet("border:1px solid #46a6ff;")
            if self._on_edit_start:
                self._on_edit_start()

    def focusOutEvent(self, ev):  # noqa: N802
        super().focusOutEvent(ev)
        if self._editing:
            self._editing = False
            self.setStyleSheet("")
            cb = self._on_edit_done
            if cb:
                # 延后一拍再回调：关窗时控件/主窗口可能正在销毁，
                # 同步执行会拿到已析构的 C++ 对象（曾导致 RuntimeError）。
                from PySide6.QtCore import QTimer

                QTimer.singleShot(0, cb)

    def keyPressEvent(self, ev):  # noqa: N802
        from ..snapshot import spec_from_qt

        key = ev.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            ev.accept()
            return                      # 只按了修饰键：等待真正的键
        if key == Qt.Key.Key_Escape:
            self.setText(self._spec)
            self.clearFocus()
            ev.accept()
            return
        spec = spec_from_qt(key, ev.modifiers().value, ev.text())
        if spec is None:
            self.setToolTip("这个键不能作为热键：纯字母/数字请搭配 Ctrl/Shift/Alt/Win（如 Ctrl+S）；Esc 取消。")
            self.setText(self._spec)
            ev.accept()
            return
        self._spec = spec
        self.setText(spec)
        self.captured.emit(spec)
        self.clearFocus()               # 录入完成 -> 触发保存与重新注册
        ev.accept()


class KeyLine(QWidget):
    """带“显示/隐藏”切换的密码输入框。"""

    changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._edit = QLineEdit()
        self._edit.setEchoMode(QLineEdit.Password)
        self._edit.setPlaceholderText("sk-...")
        self._btn = QPushButton("显示")
        self._btn.setCheckable(True)
        self._btn.setFixedWidth(48)
        self._btn.setObjectName("ovBtn")
        self._btn.toggled.connect(self._toggle)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._btn)
        self._edit.textChanged.connect(self.changed)

    def _toggle(self, on: bool):
        self._edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
        self._btn.setText("隐藏" if on else "显示")

    def text(self) -> str:
        return self._edit.text()

    def setText(self, t: str) -> None:
        self._edit.setText(t)
