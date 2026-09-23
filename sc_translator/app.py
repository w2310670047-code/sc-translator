"""应用装配与生命周期。

装配主窗口、翻译客户端与**译文悬浮框**（常驻置顶，按需截图翻译的结果推给它）；
屏幕 OCR 只在按需截图翻译时懒加载（snapshot）。早期的实时巡逻采样管线
（pipeline / patrol）已删除——以保证打包体积最小、启动最快。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from . import APP_DISPLAY_NAME, DEFAULT_MODEL, __version__
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
        # 界面语言要在建窗口之前生效
        from . import i18n

        i18n.set_language(self.settings.ui_language)
        app.setApplicationDisplayName(i18n.t("app.name"))
        setup_logging(logging.DEBUG if self.settings.log_level == "DEBUG" else logging.INFO)
        log.info("%s v%s 启动", APP_DISPLAY_NAME, __version__)

        self._hub = _Hub()
        self._hub.result.connect(self._dispatch_result)
        self._cache: Optional[TranslationCache] = None
        self._threads: list[threading.Thread] = []

        # 译文悬浮框（常驻置顶）：这里只置空，实际对象在 init_ui() 里创建
        self.overlay = None
        self.mainwin = None
        # 按需截图翻译服务（热键触发；重型依赖在里面懒加载）
        self._snap = None
        self.hotkeys = None
        self.hotkey_ok = {"capture": False, "select": False}

        # 术语表（专名预替换）
        self.apply_glossary()
        # 游戏聊天码表（中文 -> 游戏内 @码）
        self.apply_gamecode()
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
        self.ensure_overlay()
        # 窗口是热键消息的宿主，重建后必须重新注册
        self.install_hotkeys()

    def ensure_overlay(self):
        """创建（或复用）译文悬浮框。

        切界面语言会重建主窗口，但浮窗**不重建**——只刷新文案，避免译文历史丢失。
        """
        from .ui.overlay import OverlayWindow

        if self.overlay is None:
            self.overlay = OverlayWindow(self)
        else:
            self.overlay.apply_theme()
            self.overlay.retranslate()
        self.overlay.set_reply_enabled(bool(self.settings.reply_enabled))
        return self.overlay

    def set_ui_language(self, code: str) -> None:
        """切换界面语言：落盘 + 立即重建窗口（保留尺寸位置）。"""
        from . import i18n

        code = i18n.set_language(code)
        self.settings.ui_language = code
        self.settings.save()
        old = self.mainwin
        geo = old.geometry() if old is not None else None
        self.init_ui()
        if geo is not None and self.mainwin is not None:
            self.mainwin.setGeometry(geo)
        if old is not None:
            old.hide()
            old.deleteLater()
        if self.mainwin is not None:
            self.mainwin.show()
        self.qapp.setApplicationDisplayName(i18n.t("app.name"))
        log.info("界面语言已切换为 %s", code)

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
            model=self.settings.model or DEFAULT_MODEL,
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

    def translate_reply_async(self, text: str, target: str, done: Callable[[bool, object], None]) -> None:
        """浮窗回话：后台翻译一条中文，完成后在主线程回调 ``done(ok, result)``。

        失败时把异常转成字符串再回调——悬浮框会对 result 直接做截断显示。
        """
        if not (text or "").strip():
            return
        if not self.settings.load_api_key():
            from .i18n import t as _t

            done(False, _t("ov.reply.no_key"))
            return

        def work() -> str:
            client = self.make_client(use_cache=False)
            return client.translate_reply(text, target, spicy=bool(self.settings.spicy_mode))

        def cb(ok: bool, value: object) -> None:
            done(ok, value if ok else str(value))

        self.run_in_thread(work, cb)

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

    # ------------------------------------------------------- 游戏聊天码
    def apply_gamecode(self) -> None:
        """加载/重载游戏聊天码表（中文 -> 游戏内 @码）。

        码表来自本机已装汉化的 global.ini（设置里可手动指定，留空自动检测）；
        没有装汉化时该功能不可用，但不影响翻译主功能。
        """
        try:
            from . import gamecode

            path = gamecode.resolve_path(self.settings.gamecode_ini_path)
            if path is None:
                gamecode.clear()
                log.info("未找到带社区输入法码表的 global.ini，游戏聊天码功能未启用")
                return
            n = gamecode.load_global_ini(path)
            if not self.settings.gamecode_ini_path:
                # 首次自动检测到的路径写回设置，之后启动不再扫盘
                self.settings.gamecode_ini_path = str(path)
                try:
                    self.settings.save()
                except Exception:  # noqa: BLE001
                    pass
            if n:
                log.info("游戏聊天码就绪：%d 字（版本 %s）", n, gamecode.version())
        except Exception as exc:  # noqa: BLE001
            log.warning("游戏聊天码表加载失败（忽略）: %s", exc)

    # ------------------------------------------------------- 按需截图翻译
    @property
    def snapshot(self):
        """一次性截图翻译服务（首次访问才导入 OCR 栈）。"""
        if self._snap is None:
            from .snapshot import SnapshotService

            self._snap = SnapshotService(self)
        return self._snap

    def install_hotkeys(self) -> int:
        """注册全局热键（截图 / 重框），返回**成功注册的个数**。

        - 全部失败时 ``self.hotkeys`` 保持 None，界面据此给出黄字提示；
        - 逐键记录结果到 ``self.hotkey_ok``（{"capture": bool, "select": bool}），
          这样"只成功一个"也能如实显示，而不是笼统说"已更新"。
        """
        self.hotkey_ok = {"capture": False, "select": False}
        if not self.settings.snap_enabled:
            return 0
        if self.mainwin is None:
            return 0
        from .hotkeys import HotkeyService
        from .snapshot import parse_hotkey

        self.remove_hotkeys()
        try:
            svc = HotkeyService(int(self.mainwin.winId()))
            svc.install()
        except RuntimeError as exc:
            # 窗口正在销毁（关窗时焦点变化会走到这里），静默跳过
            log.debug("窗口不可用，跳过热键注册: %s", exc)
            return 0
        spec = parse_hotkey(self.settings.snap_hotkey)
        if spec:
            self.hotkey_ok["capture"] = svc.add(0x5101, spec[0], spec[1], self.mainwin.on_snap_hotkey)
        spec2 = parse_hotkey(self.settings.snap_hotkey_select)
        if spec2:
            self.hotkey_ok["select"] = svc.add(0x5102, spec2[0], spec2[1], self.mainwin.on_snap_select_hotkey)

        count = sum(1 for v in self.hotkey_ok.values() if v)
        if count:
            self.hotkeys = svc
            log.info(
                "全局热键注册：截图 %s（%s）/ 重框 %s（%s）",
                self.settings.snap_hotkey, "成功" if self.hotkey_ok["capture"] else "失败",
                self.settings.snap_hotkey_select, "成功" if self.hotkey_ok["select"] else "失败",
            )
        else:
            self.hotkeys = None
            try:
                svc.remove()
            except Exception:  # noqa: BLE001
                pass
            log.warning(
                "全局热键注册失败：截图 %s / 重框 %s —— 常见原因是本程序已有另一个实例在运行"
                "（先退出它），或热键被其它软件占用（改用别的键）",
                self.settings.snap_hotkey, self.settings.snap_hotkey_select,
            )
        return count

    def suspend_hotkeys(self) -> None:
        """临时注销热键（用户正在录入新热键时，避免按键本身触发动作）。"""
        self.remove_hotkeys()

    def resume_hotkeys(self) -> int:
        return self.install_hotkeys()

    def remove_hotkeys(self) -> None:
        if self.hotkeys is not None:
            try:
                self.hotkeys.remove()
            except Exception as exc:  # noqa: BLE001
                log.warning("注销热键异常: %s", exc)
            self.hotkeys = None

    # ------------------------------------------------------- 主题
    def apply_theme(self, theme: str) -> None:
        self.qapp.setStyleSheet(build_stylesheet(theme))

    # ------------------------------------------------------- 关闭
    def shutdown(self) -> None:
        try:
            self.cache.flush()
        except Exception as exc:  # noqa: BLE001
            log.warning("退出清理异常: %s", exc)
        self.remove_hotkeys()
        if self._snap is not None:
            try:
                self._snap.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("截图服务清理异常: %s", exc)
        if self.overlay is not None:
            try:
                self.overlay.hide_overlay()
                self.overlay.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("浮窗清理异常: %s", exc)
        log.info("应用退出")
