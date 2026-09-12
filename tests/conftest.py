import os
import sys
from pathlib import Path

import pytest

# 让测试能 import sc_translator（若以仓库根运行则已可）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SC_TRANSLATOR_HOME", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication（headless：QT_QPA_PLATFORM=offscreen）。"""
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_runtime_home(tmp_path, monkeypatch):
    """每个测试都指向临时数据目录：避免单测把 exchange.log / cache.json 写进真实 data\\。

    同时重置日志器与全局词典/术语表状态，保证互不串扰（修复复核 F1）。
    """
    monkeypatch.setenv("SC_TRANSLATOR_HOME", str(tmp_path / "isolated_home"))
    from sc_translator import exchange_log, gamedict, glossary

    exchange_log.reset()
    gamedict.clear()
    glossary.clear()
    yield
    exchange_log.reset()
    gamedict.clear()
    glossary.clear()
