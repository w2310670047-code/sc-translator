"""SC Translator 启动入口：python -m sc_translator

在最早阶段就把控制台输出/未捕获异常/faulthandler 落到
%APPDATA%\\SCTranslator\\logs\\startup.log，保证双击 pythonw 启动失败时也有据可查；
启动成功（主窗口显示）后在 logs\\app_ready.marker 写标记供 run.bat 判断。
"""

from __future__ import annotations

import datetime
import os
import sys
import traceback


def _data_dir() -> str:
    """与 sc_translator.paths.home_dir 保持一致（本地 data 优先，退回 %APPDATA%）。"""
    override = os.environ.get("SC_TRANSLATOR_HOME")
    if override:
        return override
    try:
        from .paths import home_dir

        return str(home_dir())
    except Exception:  # noqa: BLE001
        # 极早期（模块导入失败等）兜底
        return os.path.join(
            os.environ.get("APPDATA") or os.path.expanduser("~"), "SCTranslator"
        )


def _logs_dir() -> str:
    return os.path.join(_data_dir(), "logs")


def _marker_path() -> str:
    return os.path.join(_logs_dir(), "app_ready.marker")


class _Tee:
    """同时写向多个流（控制台 + 日志文件）。"""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, s: str) -> None:
        for st in self.streams:
            try:
                st.write(s)
                st.flush()
            except Exception:
                pass

    def flush(self) -> None:
        for st in self.streams:
            try:
                st.flush()
            except Exception:
                pass


def _setup_crash_logging():
    logs = _logs_dir()
    data = _data_dir()
    try:
        os.makedirs(logs, exist_ok=True)
        os.makedirs(data, exist_ok=True)
    except Exception:
        pass
    path = os.path.join(logs, "startup.log")
    fh = open(path, "a", encoding="utf-8", errors="replace")
    fh.write("\n" + "=" * 60 + f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] 启动\n")
    fh.flush()

    # pythonw 没有控制台：把 stderr 接到日志文件，Qt/PySide 的告警与异常也能留痕
    sys.stderr = _Tee(getattr(sys, "__stderr__", None), fh)

    def _hook(exc_type, exc, tb):
        try:
            sys.stderr.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    sys.excepthook = _hook
    try:
        import faulthandler

        faulthandler.enable(fh)
    except Exception:
        pass
    return fh


def _write_ready_marker() -> None:
    try:
        os.makedirs(_logs_dir(), exist_ok=True)
        with open(_marker_path(), "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()}\n{datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n")
    except Exception:
        pass


def _remove_ready_marker() -> None:
    try:
        if os.path.exists(_marker_path()):
            os.remove(_marker_path())
    except Exception:
        pass


def _doctor(online: bool) -> int:
    """自检模式（--doctor [--online]）：不开窗口，检查配置/提示词/术语表/后端连通性。

    结果写入 data\\logs\\doctor.log 并以退出码返回（0=全部通过）。
    打包成 exe 后没有控制台，这是最可靠的“装好了没”验证方式。
    """
    import time

    lines: list[str] = []
    ok = True

    def step(name: str, fn):
        nonlocal ok
        t0 = time.time()
        try:
            detail = fn()
            lines.append(f"[PASS] {name}: {detail}  ({(time.time() - t0) * 1000:.0f}ms)")
        except Exception as exc:  # noqa: BLE001
            ok = False
            lines.append(f"[FAIL] {name}: {type(exc).__name__}: {exc}")

    step("数据目录", lambda: str(_data_dir()))

    def _settings():
        from .settings import Settings

        s = Settings().load()
        key = s.load_api_key()
        return f"provider={s.api_provider} model={s.model} base={s.api_base} key={'已配置' if key else '未配置'} 嘴臭={s.spicy_mode}"

    step("设置", _settings)

    def _prompts():
        from .prompts import normal_prompt, reply_prompt, spicy_prompt

        return f"normal={len(normal_prompt())}字 spicy={len(spicy_prompt())}字 reply={len(reply_prompt())}字"

    step("提示词", _prompts)

    def _glossary():
        from . import glossary
        from .app import AppController  # noqa: F401  (仅为保持导入图一致)

        from .paths import default_glossary_file

        p = default_glossary_file()
        n = glossary.load(str(p)) if p.is_file() else 0
        glossary.ensure_defaults()
        return f"{p.name} 载入 {n} 词条，生效 {len(glossary._terms)} 条"

    step("术语表", _glossary)

    if online:

        def _api():
            from .settings import Settings
            from .translate.client import ClientOptions, OpenAiCompatClient

            s = Settings().load()
            key = s.load_api_key()
            if not key:
                raise RuntimeError("未配置 API Key，无法在线自检")
            opts = ClientOptions(
                api_base=s.api_base,
                api_key=key,
                model=s.model or "deepseek-chat",
                spicy=bool(s.spicy_mode),
            )
            client = OpenAiCompatClient(opts)
            models = client.list_models()
            out = client.translate_reply("你好，测试一下。", "English")
            return f"模型 {len(models)} 个；回话翻译 -> {out.strip()[:60]}"

        step("在线翻译（API）", _api)

    text = "\n".join(lines) + f"\n结论：{'全部通过' if ok else '存在失败项'}\n"
    try:
        os.makedirs(_logs_dir(), exist_ok=True)
        with open(os.path.join(_logs_dir(), "doctor.log"), "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:
        pass
    print(text)
    try:
        sys.stderr.write(text)
    except Exception:
        pass
    return 0 if ok else 1


def _run() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("SCTranslator")
    app.setApplicationDisplayName("Star Citizen 翻译器")
    font = QFont("Microsoft YaHei UI")
    font.setPointSize(10)
    app.setFont(font)

    # 单实例锁
    from PySide6.QtCore import QLockFile

    lock = QLockFile(os.path.join(_data_dir(), "instance.lock"))
    lock.setStaleLockTime(15_000)  # 进程崩溃/强杀后 15 秒自动视为陈旧，可重新获取
    if not lock.tryLock(50):
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.information(
            None,
            "提示",
            "SC 翻译器已在运行（或上次异常退出）。\n"
            "若确认没有运行，请删除下面的文件后重试：\n" + os.path.join(_data_dir(), "instance.lock"),
        )
        return 1

    from .app import AppController

    controller = AppController(app)
    controller.init_ui()
    controller.mainwin.show()
    _write_ready_marker()

    # 冒烟测试：SC_SMOKE_SECONDS=N 时 N 秒后自动退出（自动化验证用）
    smoke = os.environ.get("SC_SMOKE_SECONDS")
    if smoke:
        from PySide6.QtCore import QTimer

        QTimer.singleShot(int(smoke) * 1000, app.quit)

    try:
        rc = app.exec()
    finally:
        controller.shutdown()
        lock.unlock()
        _remove_ready_marker()
    return rc


def main() -> int:
    # --home=DIR 可重定向数据目录（需在任何目录计算之前生效）
    for arg in sys.argv[1:]:
        if arg.startswith("--home="):
            os.environ["SC_TRANSLATOR_HOME"] = arg.split("=", 1)[1]
            break
    # 迁移旧 %APPDATA% 数据到本地 data/（须在写任何本地日志之前执行）
    try:
        from .paths import migrate_legacy_data

        migrate_legacy_data()
    except Exception:  # noqa: BLE001
        pass
    # 首次运行自举：释放随包提示词 / 术语表到程序目录（已存在则不动）
    try:
        from . import bootstrap

        bootstrap.run()
    except Exception:  # noqa: BLE001
        pass
    fh = _setup_crash_logging()
    try:
        if "--doctor" in sys.argv:
            return _doctor(online="--online" in sys.argv)
        return _run()
    except SystemExit as exc:  # 正常 sys.exit
        return int(exc.code) if exc.code is not None else 0
    except BaseException:  # 未捕获异常：写日志并给出可见提示
        sys.excepthook(*sys.exc_info())
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            _ = QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.critical(
                None,
                "SC 翻译器启动失败",
                "启动时发生错误，详见日志：\n" + os.path.join(_logs_dir(), "startup.log"),
            )
        except Exception:
            pass
        return 1
    finally:
        try:
            fh.flush()
            fh.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
