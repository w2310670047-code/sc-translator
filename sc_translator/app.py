"""应用装配与生命周期（纯文字翻译版）。

只创建主窗口与翻译客户端相关对象；屏幕 OCR / 悬浮窗 / 采样管线已不在运行路径中，
以便打包体积最小、启动最快。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, __version__
from .logger_setup import setup_logging
from .settings import Settings
from .translate.cache import TranslationCache
from .translate.client import ClientOptions, OpenAiCompatClient
from .ui.theme import build_stylesheet

log = logging.getLogger(__name__)


class _Hub(QObject):
    """后台线程 -> 主线程的回调中枢。"""
    result = Signal(object)   # (cb, ok, value_or_exc)


class AppController:
    def __init__(self, app: QApplication, settings: Optional[Settings] = None) -> None:
        self.qapp = app
        self.settings = settings or Settings().load()
        setup_logging(logging.DEBUG if self.settings.log_level == "DEBUG" else logging.INFO)
        log.info("%s v%s 启动", APP_DISPLAY_NAME, __version__)

        self._hub = _Hub()
        self._hub.result.connect(self._dispatch_result)
        self._cache: Optional[TranslationCache] = None
        self._threads: list[threading.Thread] = []

        # 兼容字段（屏幕悬浮窗已移除）
        self.overlay = None
        self.mainwin = None

        # 术语表（专名预替换）
        self.apply_glossary()
        # 静态UI词典（默认关闭，保留接口）
        self.apply_dict()

    def _dispatch_result(self, payload: object) -> None:
        cb, ok, value = payload  # type: ignore[misc]
        try:
            cb(ok, value)
        except Exception:  # noqa: BLE001
            log.exception("回调执行异常")

    def init_ui(self) -> None:
        from .ui.main_window import MainWindow

        self.mainwin = MainWindow(self)
        self.mainwin.setStyleSheet(build_stylesheet(self.settings.theme))

    # ------------------------------------------------------- API
    @property
    def cache(self) -> TranslationCache:
        if self._cache is None:
            self._cache = TranslationCache()
        return self._cache

    def save_api_key(self, key: str) -> None:
        self.settings.save_api_key(key)

    def make_client(self, use_cache: bool = True) -> OpenAiCompatClient:
        opts = ClientOptions(
            api_base=self.settings.api_base,
            api_key=self.settings.load_api_key(),
            model=self.settings.model or "deepseek-chat",
            spicy=bool(self.settings.spicy_mode),
        )
        return OpenAiCompatClient(opts, cache=self.cache if use_cache else None)

    def run_in_thread(self, fn: Callable[[], object], cb: Callable[[bool, object], None]) -> None:
        """后台线程执行 fn，完成后在主线程调 cb(ok, value_or_exc)。"""

        def runner():
            try:
                ok, value = True, fn()
            except Exception as exc:  # noqa: BLE001
                ok, value = False, exc
            self._hub.result.emit((cb, ok, value))  # 跨线程 emit -> 排队回主线程

        t = threading.Thread(target=runner, daemon=True)
        self._threads.append(t)
        t.start()

    # ------------------------------------------------------- 词典/术语表
    def apply_dict(self) -> None:
        """加载/重载 SC 静态UI词典（默认关闭；纯文字翻译不启用）。"""
        try:
            from . import gamedict

            if self.settings.dict_enabled and self.settings.dict_path:
                data = gamedict.load(self.settings.dict_path)
                if data:
                    log.info("静态UI词典已启用：%d 词条", len(data))
            else:
                gamedict.clear()
        except Exception as exc:  # noqa: BLE001
            log.warning("词典加载失败（忽略）: %s", exc)

    def apply_glossary(self) -> None:
        """加载/重载 SC 术语表（专名预替换）。

        未显式配置路径时，自动使用程序目录 data\\sc_glossary.ini（若存在），
        这样打包后的便携版开箱即带官方术语表。
        """
        try:
            from . import glossary
            from .paths import default_glossary_file

            if not self.settings.glossary_enabled:
                glossary.clear()
                return
            path = self.settings.glossary_path
            if not path:
                auto = default_glossary_file()
                if auto.is_file():
                    path = str(auto)
                    log.info("术语表未配置路径，自动使用 %s", auto)
            if path:
                glossary.load(path)
            else:
                glossary.clear()
            glossary.ensure_defaults()
            if glossary.configured():
                log.info("SC 术语表就绪：%d 词条", len(glossary._terms))
        except Exception as exc:  # noqa: BLE001
            log.warning("术语表加载失败（忽略）: %s", exc)

    # ------------------------------------------------------- 主题
    def apply_theme(self, theme: str) -> None:
        self.qapp.setStyleSheet(build_stylesheet(theme))

    # ------------------------------------------------------- 关闭
    def shutdown(self) -> None:
        try:
            self.cache.flush()
        except Exception as exc:  # noqa: BLE001
            log.warning("退出清理异常: %s", exc)
        log.info("应用退出")
