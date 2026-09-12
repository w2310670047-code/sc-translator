"""日志初始化：文件 + 可选内存/回调缓冲（供主窗口展示）。"""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

from . import APP_NAME
from .paths import log_file

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"

# 简单环形缓冲，供 UI 日志面板展示（避免直接注入 Qt）
class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 500):
        super().__init__()
        self._cap = capacity
        self._lines: list[str] = []
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._lines.append(msg)
                if len(self._lines) > self._cap:
                    del self._lines[: len(self._lines) - self._cap]
        except Exception:
            pass

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)


ring = RingBufferHandler()
ring.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # 避免重复初始化
    for h in list(root.handlers):
        if getattr(h, "_sc_translator_own", False):
            return
        root.removeHandler(h)

    fh = RotatingFileHandler(log_file(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FMT))
    fh.setLevel(logging.DEBUG)
    fh._sc_translator_own = True  # type: ignore[attr-defined]
    root.addHandler(fh)

    ring.setLevel(level)
    ring._sc_translator_own = True  # type: ignore[attr-defined]
    root.addHandler(ring)

    logging.getLogger(APP_NAME).info("logging ready -> %s", log_file())
