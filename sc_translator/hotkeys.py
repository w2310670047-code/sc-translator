"""全局热键（RegisterHotKey + Qt 原生消息过滤）。

热键即使游戏在前台也生效（需同用户会话）。注册失败只记日志，不影响运行。
"""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Callable, Optional

from PySide6.QtCore import QAbstractNativeEventFilter

log = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

_k32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None


def register(hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
    if _k32 is None:
        return False
    return bool(_k32.RegisterHotKey(wintypes.HWND(hwnd), hotkey_id, modifiers, vk))


def unregister(hwnd: int, hotkey_id: int) -> None:
    if _k32 is None:
        return
    _k32.UnregisterHotKey(wintypes.HWND(hwnd), hotkey_id)


class QtHotkeyFilter(QAbstractNativeEventFilter):
    """捕获 WM_HOTKEY 并把回调投递到 GUI 线程。"""

    def __init__(self) -> None:
        super().__init__()
        self.handlers: dict[int, Callable[[], None]] = {}
        self._seen_msgs = 0

    def nativeEventFilter(self, eventType, message):  # noqa: N802 (Qt 命名)
        try:
            self._seen_msgs += 1
            if self._seen_msgs == 1:
                log.debug("原生事件过滤器已启用（eventType=%r）", eventType)
            if eventType != b"windows_generic_MSG" and eventType != "windows_generic_MSG":
                return False, 0
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                handler = self.handlers.get(int(msg.wParam))
                log.info("收到 WM_HOTKEY id=%s（已注册: %s）", msg.wParam, sorted(self.handlers))
                if handler is not None:
                    try:
                        handler()
                    except Exception as exc:  # noqa: BLE001
                        log.warning("热键回调异常: %s", exc)
                    return True, 0
        except Exception as exc:  # noqa: BLE001
            log.debug("热键消息解析跳过: %s", exc)
        return False, 0


class HotkeyService:
    """注册/注销一组全局热键。"""

    def __init__(self, hwnd: int) -> None:
        self._hwnd = hwnd
        self._filter = QtHotkeyFilter()
        self._ids: list[int] = []

    def install(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.instance().installNativeEventFilter(self._filter)

    def add(self, hotkey_id: int, modifiers: int, vk: int, handler: Callable[[], None]) -> bool:
        if not register(self._hwnd, hotkey_id, modifiers, vk):
            log.warning("热键注册失败 id=%s vk=0x%02X（可能被其它程序占用）", hotkey_id, vk)
            return False
        self._filter.handlers[hotkey_id] = handler
        self._ids.append(hotkey_id)
        return True

    def remove(self) -> None:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            try:
                app.removeNativeEventFilter(self._filter)
            except Exception:  # noqa: BLE001
                pass
        for hid in self._ids:
            unregister(self._hwnd, hid)
        self._ids.clear()
