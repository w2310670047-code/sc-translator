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
        self.resize(980, 880)

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

        self._dual_line = QCheckBox("双行：中文码 + 译文")
        self._dual_line.setChecked(bool(self.app.settings.reply_dual_line))
        self._dual_line.setToolTip(
            "开：同时翻译为中文与目标语言——第一行是游戏内中文码（[zh] @…，中国玩家看得懂），"
            "第二行是译文（外国玩家看得懂）。\n关：只输出译文。"
        )
        self._dual_line.toggled.connect(self._on_dual_line_toggled)
        lay2.addWidget(self._dual_line)

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

        # ---------------- 游戏聊天码（中文 -> 游戏内 @码）----------------
        gc_card, gc = make_card("游戏聊天码：把中文送进游戏聊天（需已装带社区输入法支持的汉化）")
        prow = QHBoxLayout()
        prow.addWidget(QLabel("汉化 global.ini"))
        self._gc_path = QLineEdit()
        self._gc_path.setPlaceholderText("留空 = 自动检测已安装的汉化")
        self._gc_path.editingFinished.connect(self._on_gc_path_edited)
        prow.addWidget(self._gc_path, 1)
        self._btn_gc_detect = QPushButton("自动检测")
        self._btn_gc_detect.clicked.connect(self._detect_gamecode)
        prow.addWidget(self._btn_gc_detect)
        self._btn_gc_browse = QPushButton("浏览…")
        self._btn_gc_browse.clicked.connect(self._browse_gamecode)
        prow.addWidget(self._btn_gc_browse)
        gc.addLayout(prow)

        self._gc_state = QLabel("…")
        self._gc_state.setObjectName("hint")
        gc.addWidget(self._gc_state)

        gcbox = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("中文（输入即时编码）"))
        self._gc_in = QPlainTextEdit()
        self._gc_in.setPlaceholderText("你好吗")
        self._gc_in.setMinimumHeight(70)
        self._gc_in.textChanged.connect(self._on_gc_text)
        left.addWidget(self._gc_in)
        lrow = QHBoxLayout()
        self._btn_gc_encode = QPushButton("编码并复制")
        self._btn_gc_encode.clicked.connect(lambda: self._gc_do("encode"))
        lrow.addWidget(self._btn_gc_encode)
        self._gc_autocopy = QCheckBox("自动复制")
        self._gc_autocopy.setChecked(bool(self.app.settings.gamecode_auto_copy))
        self._gc_autocopy.toggled.connect(self._on_gc_autocopy)
        lrow.addWidget(self._gc_autocopy)
        lrow.addStretch(1)
        left.addLayout(lrow)
        gcbox.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("游戏码 / 结果（可粘贴别人的 [zh] 消息后解码）"))
        self._gc_out = QPlainTextEdit()
        self._gc_out.setMinimumHeight(70)
        self._gc_out.setPlaceholderText("[zh] @IH@E8@AP")
        self._gc_out.textChanged.connect(self._on_gc_out_text)
        right.addWidget(self._gc_out)
        rrow = QHBoxLayout()
        self._btn_gc_decode = QPushButton("解码为中文")
        self._btn_gc_decode.clicked.connect(lambda: self._gc_do("decode"))
        rrow.addWidget(self._btn_gc_decode)
        self._btn_gc_copy = QPushButton("复制结果")
        self._btn_gc_copy.clicked.connect(self._copy_gc_out)
        rrow.addWidget(self._btn_gc_copy)
        rrow.addStretch(1)
        right.addLayout(rrow)
        gcbox.addLayout(right, 1)
        gc.addLayout(gcbox)
        root.addWidget(gc_card)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._translate_to_zh)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._translate_to_zh)
        self._busy = False
        self._gc_timer = None
        self._gc_syncing = False
        self._refresh_gamecode_state()

    # ---------------- 游戏聊天码 ----------------
    def _gc_source_text(self) -> str:
        """编码方向取左侧中文框；若为空则取右侧（便于只粘贴一条码去解码）。"""
        return self._gc_in.toPlainText()

    def _on_gc_autocopy(self, on: bool) -> None:
        self.app.settings.gamecode_auto_copy = bool(on)
        self.app.settings.save()

    def _refresh_gamecode_state(self) -> None:
        from .. import gamecode

        self._gc_path.setText(self.app.settings.gamecode_ini_path or "")
        st = gamecode.status()
        if st["ready"]:
            self._gc_state.setText(
                f"码表就绪：{st['size']} 字"
                + (f" · 版本 {st['version']}" if st["version"] else "")
                + f" · 来源 {st['source']}"
            )
            self._gc_state.setStyleSheet("")
        else:
            self._gc_state.setText(
                "未找到码表：请先安装带“社区输入法支持”的汉化，或点“浏览…”选择游戏目录下的 "
                "…\\Localization\\chinese_(simplified)\\global.ini"
            )
            self._gc_state.setStyleSheet("color:#f5b83d;")

    def _detect_gamecode(self) -> None:
        from .. import gamecode

        path = gamecode.autodetect()
        if path is None:
            QMessageBox.warning(
                self,
                "未找到码表",
                "没有在本机找到带社区输入法码表的 global.ini。\n"
                "请先在 SC 汉化盒子里安装带“社区输入法支持”的汉化，或手动选择文件。",
            )
            return
        self._load_gamecode_path(str(path))

    def _browse_gamecode(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.app.settings.gamecode_ini_path or ""
        path, _ = QFileDialog.getOpenFileName(self, "选择汉化后的 global.ini", start, "INI 文件 (*.ini);;所有文件 (*)")
        if path:
            self._load_gamecode_path(path)

    def _on_gc_path_edited(self) -> None:
        self._load_gamecode_path(self._gc_path.text().strip())

    def _load_gamecode_path(self, path: str) -> None:
        from .. import gamecode

        self.app.settings.gamecode_ini_path = path
        self.app.settings.save()
        try:
            n = gamecode.load_global_ini(path) if path else 0
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "码表加载失败", str(exc))
            self.app.apply_gamecode()
        else:
            if not n and path:
                QMessageBox.warning(self, "码表为空", "该文件里没有社区输入法码表块。")
                self.app.apply_gamecode()
            self._set_status(f"游戏码表已加载：{n} 字")
        self._refresh_gamecode_state()

    def _on_gc_text(self) -> None:
        """中文框输入即时编码（与原社区工具一致），并做 0.8 秒防抖自动复制。"""
        if self._gc_syncing:
            return
        from .. import gamecode

        if not gamecode.configured():
            return
        text = self._gc_in.toPlainText()
        try:
            enc = gamecode.encode(text) if text.strip() else ""
        except Exception as exc:  # noqa: BLE001
            log.warning("编码失败: %s", exc)
            return
        self._gc_syncing = True
        try:
            self._gc_out.setPlainText(enc)
        finally:
            self._gc_syncing = False
        self._gc_schedule_copy(enc)

    def _on_gc_out_text(self) -> None:
        """右侧被粘贴内容后，也做一次防抖自动复制（解码结果由按钮写入左侧）。"""
        if self._gc_syncing:
            return
        self._gc_schedule_copy(self._gc_out.toPlainText())

    def _gc_schedule_copy(self, text: str) -> None:
        from PySide6.QtCore import QTimer

        if not self._gc_autocopy.isChecked() or not text.strip():
            return
        if self._gc_timer is not None:
            self._gc_timer.stop()
        self._gc_timer = QTimer(self)
        self._gc_timer.setSingleShot(True)
        self._gc_timer.timeout.connect(lambda: self._copy_text(text, "游戏码已复制"))
        self._gc_timer.start(800)

    def _gc_do(self, mode: str) -> None:
        from .. import gamecode

        if not gamecode.configured():
            QMessageBox.information(
                self,
                "提示",
                "游戏码表未加载。\n请先安装带“社区输入法支持”的汉化，或点“自动检测 / 浏览…”指定 global.ini。",
            )
            return
        try:
            if mode == "encode":
                out = gamecode.encode(self._gc_in.toPlainText())
                self._gc_syncing = True
                try:
                    self._gc_out.setPlainText(out)
                finally:
                    self._gc_syncing = False
                if not out:
                    self._set_status("没有可编码的中文")
                    return
                self._copy_text(out, "已复制游戏码，进游戏 Ctrl+V 发送")
            else:
                raw = self._gc_out.toPlainText()
                if not raw.strip():
                    self._set_status("请先在右侧粘贴 [zh] 开头的游戏码消息")
                    return
                out = gamecode.decode(raw)
                self._gc_syncing = True
                try:
                    self._gc_in.setPlainText(out)
                finally:
                    self._gc_syncing = False
                tip = "已解码" if gamecode.has_zh_marker(raw) else "已解码（未检测到 [zh] 前缀，结果可能不准）"
                self._set_status(tip)
        except Exception as exc:  # noqa: BLE001
            self._show_fail(exc)

    def _copy_text(self, text: str, tip: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._set_status(tip)

    def _copy_gc_out(self) -> None:
        self._copy_text(self._gc_out.toPlainText(), "已复制游戏码")

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
            if not ok:
                self._show_fail(val)
                return
            composed, note = self._compose_reply(text, target, val)
            self._result_en.setPlainText(composed)
            self._copy_result()
            if note:
                self._set_status(note)

        self._run_async(work, "翻译中…", extra=post)

    # ---------------- 双行输出（中文码 + 译文）----------------
    _LANG_MARK = {"English": "en", "Japanese": "ja", "Korean": "ko"}

    def _on_dual_line_toggled(self, on: bool) -> None:
        self.app.settings.reply_dual_line = bool(on)
        self.app.settings.save()
        self._set_status(
            "双行模式：中文码 + 译文" if on else "单行模式：只输出译文"
        )

    def _compose_reply(self, zh_text: str, target: str, translation: str) -> tuple[str, str]:
        """按开关拼装回话结果。

        开：``[zh] @中文码`` + 换行 + ``[en] 译文``（中国玩家看第一行、外国玩家看第二行）
        关：只输出译文。
        码表缺失时自动退回"只输出译文"，并给出提示。
        """
        if not self._dual_line.isChecked():
            return translation, ""
        from .. import gamecode

        if not gamecode.configured():
            return translation, "⚠ 未找到汉化码表，本次只输出译文（双行需要码表）"
        code_line = gamecode.encode(zh_text)
        if not code_line:
            return translation, "⚠ 没有可编码的中文，本次只输出译文"
        mark = self._LANG_MARK.get(target, "en")
        return f"{code_line}\n[{mark}] {translation}", ""

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
