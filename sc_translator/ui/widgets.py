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
