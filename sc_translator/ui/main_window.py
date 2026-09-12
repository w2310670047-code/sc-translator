"""主窗口：文字输入双向翻译器（已移除屏幕 OCR 实时翻译界面）。

模式：
- 看懂：粘贴/输入外文 -> 简体中文（走术语表+AI）
- 回话：输入中文 -> English/Japanese/Korean 并复制（去游戏粘贴发送）
"""

from __future__ import annotations

import logging
import os
import subprocess

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_DISPLAY_NAME, __version__
from ..paths import logs_dir
from .widgets import KeyLine, make_card

log = logging.getLogger(__name__)

PROVIDERS = ["DeepSeek", "OpenAI", "自定义 OpenAI 兼容"]


class MainWindow(QMainWindow):
    def __init__(self, app) -> None:
        super().__init__(None)
        self.app = app
        s = app.settings
        self.setWindowTitle(f"{APP_DISPLAY_NAME} v{__version__}（文字翻译）")
        self.resize(860, 640)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ---------------- 顶栏 ----------------
        top = QHBoxLayout()
        title = QLabel(APP_DISPLAY_NAME)
        title.setStyleSheet("font-size:16px; font-weight:700;")
        self._status = QLabel("就绪")
        self._status.setObjectName("hint")
        top.addWidget(title)
        top.addWidget(self._status)
        top.addStretch(1)
        root.addLayout(top)

        # ---------------- API 配置 ----------------
        cfg = QFrame()
        cfg.setObjectName("card")
        cl = QHBoxLayout(cfg)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        self._provider = QComboBox()
        self._provider.addItems(PROVIDERS)
        self._provider.setCurrentIndex(max(0, PROVIDERS.index(s.api_provider) if s.api_provider in PROVIDERS else 0))
        self._provider.currentTextChanged.connect(self._on_provider_changed)
        cl.addWidget(QLabel("服务商"))
        cl.addWidget(self._provider)
        cl.addWidget(QLabel("API"))
        self._api_base = QLineEdit(s.api_base)
        self._api_base.setMinimumWidth(220)
        cl.addWidget(self._api_base, 1)
        cl.addWidget(QLabel("Key"))
        self._keyline = KeyLine()
        self._keyline.setText(s.load_api_key())
        cl.addWidget(self._keyline, 2)
        self._model = QComboBox()
        self._model.setEditable(True)
        if s.model:
            self._model.addItem(s.model)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        cl.addWidget(self._model)
        self._btn_models = QPushButton("获取模型")
        self._btn_models.clicked.connect(self._fetch_models)
        cl.addWidget(self._btn_models)
        self._btn_test = QPushButton("测试")
        self._btn_test.clicked.connect(self._test_api)
        cl.addWidget(self._btn_test)
        self._btn_logs = QPushButton("日志")
        self._btn_logs.clicked.connect(self._open_logs)
        cl.addWidget(self._btn_logs)
        root.addWidget(cfg)
        self._api_base.textChanged.connect(self._save_api_base)
        self._model.currentTextChanged.connect(self._save_model)

        # ---------------- 术语表 ----------------
        gl = QFrame()
        gl.setObjectName("card")
        gll = QHBoxLayout(gl)
        gll.setContentsMargins(10, 6, 10, 6)
        self._gl_en = QCheckBox("SC术语表（Stanton→斯坦顿星系、Pyro→派罗星系…）")
        self._gl_en.setChecked(s.glossary_enabled)
        self._gl_en.toggled.connect(self._on_glossary_toggled)
        gll.addWidget(self._gl_en)
        self._gl_path = QLineEdit(s.glossary_path)
        self._gl_path.setPlaceholderText("术语表文件(可选，留空用默认词条)")
        self._gl_path.editingFinished.connect(self._on_glossary_path_edited)
        gll.addWidget(self._gl_path, 1)
        self._btn_gl_tpl = QPushButton("生成术语表")
        self._btn_gl_tpl.clicked.connect(self._glossary_template)
        gll.addWidget(self._btn_gl_tpl)
        self._gl_state = QLabel("")
        self._gl_state.setObjectName("hint")
        gll.addWidget(self._gl_state)
        root.addWidget(gl)
        self._refresh_glossary_state()

        # ---------------- 嘴臭模式 ----------------
        sp = QFrame()
        sp.setObjectName("card")
        spl = QHBoxLayout(sp)
        spl.setContentsMargins(10, 6, 10, 6)
        self._spicy = QCheckBox("嘴臭模式：开启用嘴臭提示词(嘲讽垃圾话)，关闭用正常提示词")
        self._spicy.setChecked(s.spicy_mode)
        self._spicy.toggled.connect(self._on_spicy_toggled)
        self._spicy.setToolTip("开启后“看懂”译文与“回话”输出都用嘴臭风格；关闭恢复正常。")
        spl.addWidget(self._spicy)
        spl.addStretch(1)
        root.addWidget(sp)

        # ---------------- 翻译区 ----------------
        mid = QHBoxLayout()
        mid.setSpacing(8)

        # 左：看懂（外->中）
        card, lay = make_card("看懂：粘贴/输入外文 → 中文")
        self._in_en = QPlainTextEdit()
        self._in_en.setPlaceholderText("把聊天里看到的外文粘贴/输入到这里…")
        self._in_en.setMinimumHeight(280)
        lay.addWidget(self._in_en, 1)
        row = QHBoxLayout()
        self._btn_tr = QPushButton("翻译到中文")
        self._btn_tr.clicked.connect(self._translate_to_zh)
        row.addWidget(self._btn_tr)
        self._btn_paste = QPushButton("粘贴剪贴板")
        self._btn_paste.clicked.connect(self._paste_in)
        row.addWidget(self._btn_paste)
        self._btn_clear = QPushButton("清空")
        self._btn_clear.clicked.connect(lambda: self._in_en.clear())
        row.addWidget(self._btn_clear)
        row.addStretch(1)
        lay.addLayout(row)
        mid.addWidget(card, 1)

        # 右：回话（中->外）
        card2, lay2 = make_card("回话：输入中文 → 外文")
        self._out_zh = QPlainTextEdit()
        self._out_zh.setPlaceholderText("要发给外国玩家的中文回话…")
        self._out_zh.setMinimumHeight(120)
        lay2.addWidget(self._out_zh)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("目标"))
        self._reply_target = QComboBox()
        self._reply_target.addItems(["English", "Japanese", "Korean"])
        self._reply_target.setFixedWidth(110)
        row2.addWidget(self._reply_target)
        self._btn_reply = QPushButton("翻译并复制")
        self._btn_reply.clicked.connect(self._translate_reply)
        row2.addWidget(self._btn_reply)
        row2.addStretch(1)
        lay2.addLayout(row2)

        lay2.addWidget(QLabel("译文（只读，可选中复制）"))
        self._result_en = QPlainTextEdit()
        self._result_en.setReadOnly(True)
        self._result_en.setMinimumHeight(130)
        lay2.addWidget(self._result_en, 1)
        row3 = QHBoxLayout()
        self._btn_copy = QPushButton("复制译文")
        self._btn_copy.clicked.connect(self._copy_result)
        row3.addWidget(self._btn_copy)
        row3.addStretch(1)
        lay2.addLayout(row3)
        mid.addWidget(card2, 1)
        root.addLayout(mid, 1)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._translate_to_zh)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._translate_to_zh)
        self._busy = False

    # ---------------- API ----------------
    def _on_provider_changed(self, name: str) -> None:
        from ..settings import PROVIDER_PRESETS

        preset = PROVIDER_PRESETS.get(name, "")
        if preset:
            self._api_base.setText(preset)
        self.app.settings.api_provider = name

    def _save_api_base(self, _t: str) -> None:
        self.app.settings.api_base = self._api_base.text().strip()
        self.app.settings.save()

    def _save_model(self, _t: str) -> None:
        self.app.settings.model = self._model.currentText().strip()
        self.app.settings.save()

    def _persist_api(self) -> bool:
        key = self._keyline.text().strip()
        if not key:
            QMessageBox.warning(self, "缺少 API Key", "请先填写 API Key。")
            return False
        self.app.settings.api_base = self._api_base.text().strip()
        self.app.settings.model = self._model.currentText().strip() or "deepseek-chat"
        self.app.save_api_key(key)
        self.app.settings.save()
        return True

    def _fetch_models(self) -> None:
        if not self._persist_api():
            return
        self._btn_models.setEnabled(False)
        self._btn_models.setText("获取中…")
        client = self.app.make_client(use_cache=False)

        def work():
            return client.list_models()

        def done(ok, val):
            self._btn_models.setEnabled(True)
            self._btn_models.setText("获取模型")
            if not ok:
                QMessageBox.critical(self, "获取失败", str(val))
                return
            cur = self._model.currentText()
            models = list(val or [])
            self._model.blockSignals(True)
            self._model.clear()
            self._model.addItems(models)
            if cur in models:
                self._model.setCurrentText(cur)
            self._model.blockSignals(False)
            self._save_model("")

        self.app.run_in_thread(work, done)

    def _test_api(self) -> None:
        if not self._persist_api():
            return
        self._btn_test.setEnabled(False)
        self._btn_test.setText("测试中…")
        client = self.app.make_client(use_cache=False)
        client.opts.model = self._model.currentText().strip() or "deepseek-chat"

        def work():
            return client.translate_line("Hello, this is a translation test.", "en", "zh-CN")

        def done(ok, val):
            self._btn_test.setEnabled(True)
            self._btn_test.setText("测试")
            if ok:
                QMessageBox.information(self, "测试成功", f"测试译文：{val}")
            else:
                QMessageBox.critical(self, "测试失败", str(val))

        self.app.run_in_thread(work, done)

    # ---------------- 术语表 ----------------
    def _refresh_glossary_state(self) -> None:
        try:
            from .. import glossary

            if not self.app.settings.glossary_enabled:
                self._gl_state.setText("已关闭")
            elif glossary.configured():
                self._gl_state.setText(f"已生效 {len(glossary._terms)} 词条")
            else:
                self._gl_state.setText("未生效")
        except Exception as exc:  # noqa: BLE001
            self._gl_state.setText(str(exc))

    def _on_glossary_toggled(self, _on: bool) -> None:
        self.app.settings.glossary_enabled = self._gl_en.isChecked()
        self.app.settings.save()
        self.app.apply_glossary()
        self._refresh_glossary_state()

    def _on_glossary_path_edited(self) -> None:
        self.app.settings.glossary_path = self._gl_path.text().strip()
        self.app.settings.save()
        self.app.apply_glossary()
        self._refresh_glossary_state()

    def _glossary_template(self) -> None:
        try:
            from .. import glossary, paths

            target = self._gl_path.text().strip() or str(paths.home_dir() / "sc_glossary.ini")
            if glossary.write_sample(target):
                self._gl_path.setText(target)
                self.app.settings.glossary_path = target
                self.app.settings.glossary_enabled = True
                self._gl_en.setChecked(True)
                self.app.settings.save()
                self.app.apply_glossary()
                self._refresh_glossary_state()
                QMessageBox.information(self, "术语表已生成", f"{target}\n\n每行 英文词条 = 中文译名")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "生成失败", str(exc))

    # ---------------- 动作 ----------------
    def _on_spicy_toggled(self, _on: bool) -> None:
        self.app.settings.spicy_mode = self._spicy.isChecked()
        self.app.settings.save()
        self._set_status("嘴臭模式已开启" if self._spicy.isChecked() else "嘴臭模式已关闭")

    def _paste_in(self) -> None:
        from PySide6.QtWidgets import QApplication

        self._in_en.setPlainText(QApplication.clipboard().text())

    def _copy_result(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._result_en.toPlainText())
        self._set_status("已复制译文")

    def _translate_to_zh(self) -> None:
        if self._busy:
            return
        text = self._in_en.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先粘贴或输入外文。")
            return
        if not self._persist_api():
            return
        client = self.app.make_client(use_cache=True)
        client.opts.model = self._model.currentText().strip() or "deepseek-chat"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        def work():
            outs = client.translate_lines_batch(lines, source_lang="auto", target_lang="zh-CN")
            return "\n".join(outs)

        self._run_async(work, "翻译中…")

    def _translate_reply(self) -> None:
        if self._busy:
            return
        text = self._out_zh.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先输入中文回话。")
            return
        if not self._persist_api():
            return
        target = self._reply_target.currentText()
        client = self.app.make_client(use_cache=False)
        client.opts.model = self._model.currentText().strip() or "deepseek-chat"
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        def work():
            return "\n".join(
                client.translate_reply(ln, target, spicy=bool(self.app.settings.spicy_mode))
                for ln in lines
            )

        def post(ok, val):
            if ok:
                self._result_en.setPlainText(val)
                self._copy_result()
            else:
                self._show_fail(val)

        self._run_async(work, "翻译中…", extra=post)

    def _run_async(self, work, status: str, extra=None) -> None:
        self._busy = True
        self._set_status(status)

        def done(ok, val):
            self._busy = False
            if extra is not None:
                extra(ok, val)
                return
            if ok:
                self._result_en.setPlainText(val)
                self._set_status("完成")
            else:
                self._show_fail(val)

        self.app.run_in_thread(work, done)

    def _show_fail(self, msg) -> None:
        self._set_status(f"失败：{msg}")
        QMessageBox.warning(self, "翻译失败", str(msg))

    def _set_status(self, text: str) -> None:
        self._status.setText(text)

    # ---------------- AppController 兼容桩 ----------------
    def _refresh_region_desc(self) -> None:
        pass

    def refresh_overlay_controls(self) -> None:
        pass

    def on_running_changed(self, running: bool) -> None:
        pass

    def on_status(self, counters: dict) -> None:
        pass

    def on_error(self, msg: str) -> None:
        self._set_status(f"异常：{msg}")

    def _open_logs(self) -> None:
        try:
            os.startfile(logs_dir())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            subprocess.Popen(["explorer", str(logs_dir())])

    def closeEvent(self, ev: QCloseEvent) -> None:
        self.app.shutdown()
        super().closeEvent(ev)
