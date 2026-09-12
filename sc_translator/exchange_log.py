"""交换日志：记录每次真实翻译请求的 用户输入 -> 模型输出（含错误）。

独立文件 data\\logs\\exchange.log，UTF-8、按大小轮转。
每条记录格式（repr 形式保留不可见字符，便于排查乱码/空内容）：

  [kind=reply model=deepseek-v4-flash style=normal ok=True]
  IN : '用户输入…'
  OUT: '模型输出…'
  或 ERR: '错误信息…'
"""

from __future__ import annotations

import logging
import threading
from logging.handlers import RotatingFileHandler

from .paths import logs_dir

_lock = threading.Lock()
_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    with _lock:
        if _logger is None:
            path = logs_dir() / "exchange.log"
            handler = RotatingFileHandler(path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
            handler.setLevel(logging.INFO)
            _logger = logging.getLogger("sc_translator.exchange")
            _logger.addHandler(handler)
            _logger.setLevel(logging.INFO)
            _logger.propagate = False
        return _logger


def reset() -> None:
    """关闭并重建日志器（测试/换数据目录用）。"""
    global _logger
    with _lock:
        if _logger is not None:
            for h in list(_logger.handlers):
                _logger.removeHandler(h)
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass
        _logger = None


def record(
    kind: str,               # realtime / reply / test
    model: str,
    inp: str,
    out: str = "",
    error: str = "",
    style: str = "normal",   # normal / spicy
    cached: bool = False,
) -> None:
    """写一条输入/输出记录。out 与 error 至少给一个。"""
    try:
        inp_repr = repr(inp) if inp else ""
        ok = not error
        head = (
            f"[kind={kind} model={model} style={style} cached={cached} ok={ok}]"
        )
        if ok:
            _get_logger().info("%s\nIN  : %s\nOUT : %s", head, inp_repr, repr(out) if out else repr(""))
        else:
            _get_logger().error("%s\nIN  : %s\nERR : %s", head, inp_repr, repr(error))
    except Exception:  # noqa: BLE001
        # 日志自身失败绝不能影响翻译主流程
        pass
