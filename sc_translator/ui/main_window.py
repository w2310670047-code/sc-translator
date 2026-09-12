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

from .. import __version__
from .. import i18n
from ..i18n import t
from ..paths import logs_dir
from ..settings import PROVIDER_PRESETS
from .widgets import KeyLine, make_card

log = logging.getLogger(__name__)

# 服务商：key 稳定（存设置），显示名走 i18n
PROVIDERS = list(PROVIDER_PRESETS)


def provider_choices() -> list[tuple[str, str]]:
    """服务商下拉项 [(稳定key, 本地化显示名)]。"""
    out = []
    for key in PROVIDERS:
        out.append((key, t("provider.custom") if key == "custom" else key))
    return out


class MainWindow(QMainWindow):
    def __init__(self, app) -> None:
        super().__init__(None)
        self.app = app
        s = app.settings
        self.setWindowTitle(t("app.title", version=__version__))
        self.resize(980, 880)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ---------------- 顶栏 ----------------
        top = QHBoxLayout()
        title = QLabel(t("app.name"))
        title.setStyleSheet("font-size:16px; font-weight:700;")
        self._status = QLabel(t("status.ready"))
        self._status.setObjectName("hint")
        top.addWidget(title)
        top.addWidget(self._status)
        top.addStretch(1)
        top.addWidget(QLabel(t("lang.label")))
        self._lang = QComboBox()
        for code, label in i18n.languages():
            self._lang.addItem(label, code)
        idx = self._lang.findData(i18n.current())
        self._lang.setCurrentIndex(idx if idx >= 0 else 0)
        self._lang.setFixedWidth(130)
        self._lang.currentIndexChanged.connect(self._on_language_changed)
        top.addWidget(self._lang)
        root.addLayout(top)

        # ---------------- API 配置 ----------------
        cfg = QFrame()
        cfg.setObjectName("card")
        cl = QHBoxLayout(cfg)
        cl.setContentsMargins(10, 8, 10, 8)
        cl.setSpacing(6)
        self._provider = QComboBox()
        for key, label in provider_choices():
            self._provider.addItem(label, key)
        pidx = self._provider.findData(s.api_provider or "DeepSeek")
        self._provider.setCurrentIndex(pidx if pidx >= 0 else 0)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        cl.addWidget(QLabel(t("provider.label")))
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
        self._btn_models = QPushButton(t("btn.models"))
        self._btn_models.clicked.connect(self._fetch_models)
        cl.addWidget(self._btn_models)
        self._btn_test = QPushButton(t("btn.test"))
        self._btn_test.clicked.connect(self._test_api)
        cl.addWidget(self._btn_test)
        self._btn_logs = QPushButton(t("btn.logs"))
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
        self._gl_en = QCheckBox(t("glossary.label"))
        self._gl_en.setChecked(s.glossary_enabled)
        self._gl_en.toggled.connect(self._on_glossary_toggled)
        gll.addWidget(self._gl_en)
        self._gl_path = QLineEdit(s.glossary_path)
        self._gl_path.setPlaceholderText(t("glossary.path_ph"))
        self._gl_path.editingFinished.connect(self._on_glossary_path_edited)
        gll.addWidget(self._gl_path, 1)
        self._btn_gl_tpl = QPushButton(t("btn.make_glossary"))
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
        self._spicy = QCheckBox(t("spicy.label"))
        self._spicy.setChecked(s.spicy_mode)
        self._spicy.toggled.connect(self._on_spicy_toggled)
        self._spicy.setToolTip(t("spicy.tip"))
        spl.addWidget(self._spicy)
        spl.addStretch(1)
        root.addWidget(sp)

        # ---------------- 翻译区 ----------------
        mid = QHBoxLayout()
        mid.setSpacing(8)

        # 左：看懂（外->中）
        card, lay = make_card(t("pane.in.title"))
        self._in_en = QPlainTextEdit()
        self._in_en.setPlaceholderText(t("pane.in.ph"))
        self._in_en.setMinimumHeight(280)
        lay.addWidget(self._in_en, 1)
        row = QHBoxLayout()
        self._btn_tr = QPushButton(t("btn.translate_zh"))
        self._btn_tr.clicked.connect(self._translate_to_zh)
        row.addWidget(self._btn_tr)
        self._btn_paste = QPushButton(t("btn.paste"))
        self._btn_paste.clicked.connect(self._paste_in)
        row.addWidget(self._btn_paste)
        self._btn_clear = QPushButton(t("btn.clear"))
        self._btn_clear.clicked.connect(lambda: self._in_en.clear())
        row.addWidget(self._btn_clear)
        row.addStretch(1)
        lay.addLayout(row)
        mid.addWidget(card, 1)

        # 右：回话（中->外）
        card2, lay2 = make_card(t("pane.out.title"))
        self._out_zh = QPlainTextEdit()
        self._out_zh.setPlaceholderText(t("pane.out.ph"))
        self._out_zh.setMinimumHeight(120)
        lay2.addWidget(self._out_zh)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel(t("lbl.target")))
        self._reply_target = QComboBox()
        self._reply_target.addItems(["English", "Japanese", "Korean"])
        self._reply_target.setFixedWidth(110)
        row2.addWidget(self._reply_target)
        self._btn_reply = QPushButton(t("btn.translate_copy"))
        self._btn_reply.clicked.connect(self._translate_reply)
        row2.addWidget(self._btn_reply)
        row2.addStretch(1)
        lay2.addLayout(row2)

        outrow = QHBoxLayout()
        outrow.addWidget(QLabel(t("lbl.output")))
        self._reply_out_code = QCheckBox(t("chk.code"))
        self._reply_out_code.setChecked(bool(self.app.settings.reply_out_code))
        self._reply_out_code.setToolTip(t("chk.code.tip"))
        self._reply_out_code.toggled.connect(lambda _v: self._on_reply_out_toggled("code"))
        outrow.addWidget(self._reply_out_code)
        self._reply_out_foreign = QCheckBox(t("chk.foreign"))
        self._reply_out_foreign.setChecked(bool(self.app.settings.reply_out_foreign))
        self._reply_out_foreign.setToolTip(t("chk.foreign.tip"))
        self._reply_out_foreign.toggled.connect(lambda _v: self._on_reply_out_toggled("foreign"))
        outrow.addWidget(self._reply_out_foreign)
        outrow.addStretch(1)
        lay2.addLayout(outrow)

        lay2.addWidget(QLabel(t("lbl.result")))
        self._result_en = QPlainTextEdit()
        self._result_en.setReadOnly(True)
        self._result_en.setMinimumHeight(130)
        lay2.addWidget(self._result_en, 1)
        row3 = QHBoxLayout()
        self._btn_copy = QPushButton(t("btn.copy_result"))
        self._btn_copy.clicked.connect(self._copy_result)
        row3.addWidget(self._btn_copy)
        row3.addStretch(1)
        lay2.addLayout(row3)
        mid.addWidget(card2, 1)
        root.addLayout(mid, 1)

        # ---------------- 游戏聊天码（中文 -> 游戏内 @码）----------------
        gc_card, gc = make_card(t("gc.title"))
        prow = QHBoxLayout()
        prow.addWidget(QLabel(t("gc.path_label")))
        self._gc_path = QLineEdit()
        self._gc_path.setPlaceholderText(t("gc.path_ph"))
        self._gc_path.editingFinished.connect(self._on_gc_path_edited)
        prow.addWidget(self._gc_path, 1)
        self._btn_gc_detect = QPushButton(t("gc.detect"))
        self._btn_gc_detect.clicked.connect(self._detect_gamecode)
        prow.addWidget(self._btn_gc_detect)
        self._btn_gc_browse = QPushButton(t("gc.browse"))
        self._btn_gc_browse.clicked.connect(self._browse_gamecode)
        prow.addWidget(self._btn_gc_browse)
        gc.addLayout(prow)

        self._gc_state = QLabel("…")
        self._gc_state.setObjectName("hint")
        gc.addWidget(self._gc_state)

        gcbox = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel(t("gc.in_label")))
        self._gc_in = QPlainTextEdit()
        self._gc_in.setPlaceholderText(t("gc.in_ph"))
        self._gc_in.setMinimumHeight(70)
        self._gc_in.textChanged.connect(self._on_gc_text)
        left.addWidget(self._gc_in)
        lrow = QHBoxLayout()
        self._btn_gc_encode = QPushButton(t("btn.encode_copy"))
        self._btn_gc_encode.clicked.connect(lambda: self._gc_do("encode"))
        lrow.addWidget(self._btn_gc_encode)
        self._gc_autocopy = QCheckBox(t("gc.autocopy"))
        self._gc_autocopy.setChecked(bool(self.app.settings.gamecode_auto_copy))
        self._gc_autocopy.toggled.connect(self._on_gc_autocopy)
        lrow.addWidget(self._gc_autocopy)
        self._gc_out_code = QCheckBox(t("chk.code"))
        self._gc_out_code.setChecked(bool(self.app.settings.gamecode_out_code))
        self._gc_out_code.setToolTip(t("gc.chk.code.tip"))
        self._gc_out_code.toggled.connect(lambda _v: self._on_gc_out_toggled("code"))
        lrow.addWidget(self._gc_out_code)
        self._gc_out_en = QCheckBox(t("gc.chk.en"))
        self._gc_out_en.setChecked(bool(self.app.settings.gamecode_out_en))
        self._gc_out_en.setToolTip(t("gc.chk.en.tip"))
        self._gc_out_en.toggled.connect(lambda _v: self._on_gc_out_toggled("en"))
        lrow.addWidget(self._gc_out_en)
        lrow.addStretch(1)
        left.addLayout(lrow)
        gcbox.addLayout(left, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel(t("gc.out_label")))
        self._gc_out = QPlainTextEdit()
        self._gc_out.setMinimumHeight(70)
        self._gc_out.setPlaceholderText(t("gc.out_ph_code"))
        self._gc_out.textChanged.connect(self._on_gc_out_text)
        right.addWidget(self._gc_out)
        rrow = QHBoxLayout()
        self._btn_gc_decode = QPushButton(t("btn.decode"))
        self._btn_gc_decode.clicked.connect(lambda: self._gc_do("decode"))
        rrow.addWidget(self._btn_gc_decode)
        self._btn_gc_copy = QPushButton(t("btn.copy_gc"))
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
        self._gc_busy = False
        self._dual_syncing = False
        self._refresh_gamecode_state()
        self._refresh_gc_mode()

    # ---------------- 游戏聊天码 ----------------
    def _on_gc_autocopy(self, on: bool) -> None:
        self.app.settings.gamecode_auto_copy = bool(on)
        self.app.settings.save()

    def _refresh_gamecode_state(self) -> None:
        from .. import gamecode

        self._gc_path.setText(self.app.settings.gamecode_ini_path or "")
        st = gamecode.status()
        if st["ready"]:
            self._gc_state.setText(
                t("gc.state_ready", size=st["size"])
                + (t("gc.state_version", version=st["version"]) if st["version"] else "")
                + t("gc.state_source", source=st["source"])
            )
            self._gc_state.setStyleSheet("")
        else:
            self._gc_state.setText(t("gc.state_missing"))
            self._gc_state.setStyleSheet("color:#f5b83d;")

    def _detect_gamecode(self) -> None:
        from .. import gamecode

        path = gamecode.autodetect()
        if path is None:
            QMessageBox.warning(self, t("dlg.no_table.title"), t("dlg.no_table.body"))
            return
        self._load_gamecode_path(str(path))

    def _browse_gamecode(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.app.settings.gamecode_ini_path or ""
        path, _ = QFileDialog.getOpenFileName(self, t("dlg.pick_ini"), start, t("filter.ini"))
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
            QMessageBox.warning(self, t("dlg.load_fail.title"), str(exc))
            self.app.apply_gamecode()
        else:
            if not n and path:
                QMessageBox.warning(self, t("dlg.empty_table.title"), t("dlg.empty_table.body"))
                self.app.apply_gamecode()
            self._set_status(t("status.table_loaded", n=n))
        self._refresh_gamecode_state()

    def _on_gc_text(self) -> None:
        """勾了"中文码"时输入即时预览（本地、不调 API）；只勾"英文"时不预览。"""
        if self._gc_syncing:
            return
        from .. import gamecode

        if not self._gc_out_code.isChecked() or not gamecode.configured():
            return
        text = self._gc_in.toPlainText()
        try:
            enc = gamecode.encode(text) if text.strip() else ""
        except Exception as exc:  # noqa: BLE001
            log.warning("编码失败: %s", exc)
            return
        self._set_gc_out(enc)
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
        self._gc_timer.timeout.connect(lambda: self._copy_text(text, t("status.copied_send")))
        self._gc_timer.start(800)

    # ---- 界面语言 ----
    def _on_language_changed(self, _idx: int) -> None:
        """切换界面语言：落盘并立即重建窗口（翻译进行中先拒绝，避免回调打到旧控件）。"""
        code = self._lang.currentData()
        if not code or code == i18n.current():
            return
        if self._busy or self._gc_busy:
            self._set_status(t("status.lang_busy"))
            idx = self._lang.findData(i18n.current())
            if idx >= 0:
                self._lang.blockSignals(True)
                self._lang.setCurrentIndex(idx)
                self._lang.blockSignals(False)
            return
        self.app.set_ui_language(str(code))

    # ---- 输出选择：中文码 / 英文（游戏聊天码卡片）----
    def _on_gc_out_toggled(self, which: str) -> None:
        """勾选状态落盘；不允许两个都空（最后一个勾会被自动勾回）。"""
        reverted = False
        self._dual_syncing = True
        try:
            if not self._gc_out_code.isChecked() and not self._gc_out_en.isChecked():
                cb = self._gc_out_code if which == "code" else self._gc_out_en
                cb.setChecked(True)
                reverted = True
        finally:
            self._dual_syncing = False
        s = self.app.settings
        s.gamecode_out_code = self._gc_out_code.isChecked()
        s.gamecode_out_en = self._gc_out_en.isChecked()
        s.save()
        self._refresh_gc_mode()
        if reverted:
            self._set_status(t("status.min_one_gc"))

    def _refresh_gc_mode(self) -> None:
        code, en = self._gc_out_code.isChecked(), self._gc_out_en.isChecked()
        if code and en:
            self._btn_gc_encode.setText(t("btn.gen_dual"))
            self._gc_out.setPlaceholderText(t("gc.out_ph_dual"))
        elif en:
            self._btn_gc_encode.setText(t("btn.translate_en_copy"))
            self._gc_out.setPlaceholderText(t("gc.out_ph_en"))
        else:
            self._btn_gc_encode.setText(t("btn.encode_copy"))
            self._gc_out.setPlaceholderText(t("gc.out_ph_code"))

    def _gc_do(self, mode: str) -> None:
        if mode == "decode":
            self._gc_decode()
            return
        self._gc_encode()

    def _gc_translate_client(self):
        """为"英文行"构造翻译客户端；缺 Key/取消时返回 None。"""
        if not self._persist_api():
            return None
        client = self.app.make_client(use_cache=False)
        client.opts.model = self._model.currentText().strip() or "deepseek-chat"
        return client

    def _gc_encode(self) -> None:
        """中文 -> 按勾选生成：只中文码 / 只英文 / 中文码+英文，并复制。"""
        from .. import gamecode

        if self._gc_busy:
            return
        zh = self._gc_in.toPlainText().strip()
        if not zh:
            self._set_status(t("status.need_zh"))
            return

        want_code = self._gc_out_code.isChecked()
        want_en = self._gc_out_en.isChecked()
        code_line, note = "", ""
        if want_code:
            if gamecode.configured():
                code_line = gamecode.encode(zh)
            else:
                note = t("warn.no_table_code")
                if not want_en:
                    QMessageBox.information(self, t("dlg.notice"), t("dlg.need_table.code_body"))
                    return

        if not want_en:
            # 只需中文码：纯本地，不调用 API
            self._set_gc_out(code_line)
            self._copy_text(code_line, t("status.copied_code"))
            if note:
                self._set_status(note)
            return

        client = self._gc_translate_client()
        if client is None:
            if code_line:   # 没有翻译后端：至少把中文码给出去
                self._set_gc_out(code_line)
                self._copy_text(code_line, t("status.no_key_code_only"))
            else:
                self._set_status(t("status.need_key_en"))
            return

        self._gc_busy = True
        self._btn_gc_encode.setEnabled(False)
        self._set_status(t("status.translating"))

        def work():
            return client.translate_reply(zh, "English", spicy=bool(self.app.settings.spicy_mode))

        def done(ok, val):
            self._gc_busy = False
            self._btn_gc_encode.setEnabled(True)
            if not ok:
                if code_line:   # 翻译失败：至少把中文码给出去
                    self._set_gc_out(code_line)
                    self._copy_text(code_line, t("status.translate_failed_code", err=val))
                else:
                    self._show_fail(val)
                return
            en = str(val).strip()
            out = f"{code_line}\n[en] {en}" if code_line else en
            self._set_gc_out(out)
            self._gc_timer_stop()
            self._copy_text(out, t("status.copied_dual") if code_line else t("status.copied_en"))
            if note:
                self._set_status(note)

        self.app.run_in_thread(work, done)

    def _gc_timer_stop(self) -> None:
        if self._gc_timer is not None:
            self._gc_timer.stop()

    def _set_gc_out(self, text: str) -> None:
        self._gc_syncing = True
        try:
            self._gc_out.setPlainText(text)
        finally:
            self._gc_syncing = False

    def _gc_decode(self) -> None:
        """粘贴别人的 [zh] 码 -> 还原中文（左侧显示并复制，右侧保留原码便于对照）。"""
        from .. import gamecode

        if not gamecode.configured():
            QMessageBox.information(self, t("dlg.notice"), t("dlg.need_table.code_body"))
            return
        try:
            raw = self._gc_out.toPlainText()
            if not raw.strip():
                self._set_status(t("status.need_paste_code"))
                return
            zh = gamecode.decode(raw)
            self._gc_syncing = True
            try:
                self._gc_in.setPlainText(zh)     # 左侧显示中文，便于继续编辑/再翻译
            finally:
                self._gc_syncing = False
            self._copy_text(zh, t("status.decoded"))
            if not gamecode.has_zh_marker(raw):
                self._set_status(t("status.decoded_unsure"))
        except Exception as exc:  # noqa: BLE001
            self._show_fail(exc)

    def _copy_text(self, text: str, tip: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        self._set_status(tip)

    def _copy_gc_out(self) -> None:
        self._copy_text(self._gc_out.toPlainText(), t("status.copied_send"))

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
            QMessageBox.warning(self, t("dlg.no_key.title"), t("dlg.no_key.body"))
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
        self._btn_models.setText(t("btn.loading"))
        client = self.app.make_client(use_cache=False)

        def work():
            return client.list_models()

        def done(ok, val):
            self._btn_models.setEnabled(True)
            self._btn_models.setText(t("btn.models"))
            if not ok:
                QMessageBox.critical(self, t("dlg.fetch_fail.title"), str(val))
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
        self._btn_test.setText(t("btn.testing"))
        client = self.app.make_client(use_cache=False)
        client.opts.model = self._model.currentText().strip() or "deepseek-chat"

        def work():
            return client.translate_line("Hello, this is a translation test.", "en", "zh-CN")

        def done(ok, val):
            self._btn_test.setEnabled(True)
            self._btn_test.setText(t("btn.test"))
            if ok:
                QMessageBox.information(self, t("dlg.test_ok.title"), t("dlg.test_ok.body", val=val))
            else:
                QMessageBox.critical(self, t("dlg.test_fail.title"), str(val))

        self.app.run_in_thread(work, done)

    # ---------------- 术语表 ----------------
    def _refresh_glossary_state(self) -> None:
        try:
            from .. import glossary

            if not self.app.settings.glossary_enabled:
                self._gl_state.setText(t("gl.state_off"))
            elif glossary.configured():
                self._gl_state.setText(t("gl.state_active", n=len(glossary._terms)))
            else:
                self._gl_state.setText(t("gl.state_inactive"))
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
                QMessageBox.information(self, t("gl.made"), f"{target}\n\n每行 英文词条 = 中文译名")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, t("gl.make_fail"), str(exc))

    # ---------------- 动作 ----------------
    def _on_spicy_toggled(self, _on: bool) -> None:
        self.app.settings.spicy_mode = self._spicy.isChecked()
        self.app.settings.save()
        self._set_status(t("status.spicy_on") if self._spicy.isChecked() else t("status.spicy_off"))

    def _paste_in(self) -> None:
        from PySide6.QtWidgets import QApplication

        self._in_en.setPlainText(QApplication.clipboard().text())

    def _copy_result(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._result_en.toPlainText())
        self._set_status(t("status.copied_result"))

    def _translate_to_zh(self) -> None:
        if self._busy:
            return
        text = self._in_en.toPlainText().strip()
        if not text:
            QMessageBox.information(self, t("dlg.notice"), t("dlg.need_foreign"))
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
            QMessageBox.information(self, t("dlg.notice"), t("dlg.need_reply"))
            return
        target = self._reply_target.currentText()
        want_code, want_foreign = self._reply_out_code.isChecked(), self._reply_out_foreign.isChecked()

        # 只勾"中文码"（中译中）：纯本地编码，不需要 API
        if want_code and not want_foreign:
            code_line, note = self._reply_code_line(text)
            if not code_line:
                QMessageBox.information(self, t("dlg.notice"), t("dlg.need_table.reply_body"))
                return
            self._result_en.setPlainText(code_line)
            self._copy_result()
            self._set_status(note or t("status.copied_code"))
            return

        if not self._persist_api():
            return
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

    # ---------------- 输出组合（中文码 / 译文）----------------
    _LANG_MARK = {"English": "en", "Japanese": "ja", "Korean": "ko"}

    def _on_reply_out_toggled(self, which: str) -> None:
        """回话输出勾选：不允许两个都空，勾选状态落盘。"""
        reverted = False
        self._dual_syncing = True
        try:
            if not self._reply_out_code.isChecked() and not self._reply_out_foreign.isChecked():
                cb = self._reply_out_code if which == "code" else self._reply_out_foreign
                cb.setChecked(True)
                reverted = True
        finally:
            self._dual_syncing = False
        s = self.app.settings
        s.reply_out_code = self._reply_out_code.isChecked()
        s.reply_out_foreign = self._reply_out_foreign.isChecked()
        s.save()
        if reverted:
            self._set_status("至少保留一项输出：中文码 或 译文")
            return
        code, foreign = self._reply_out_code.isChecked(), self._reply_out_foreign.isChecked()
        self._set_status(
            "回话输出：中文码 + 译文" if code and foreign
            else ("回话输出：只中文码" if code else "回话输出：只译文")
        )

    def _reply_code_line(self, zh_text: str) -> tuple[str, str]:
        """生成回话用的中文码行；返回 (码行, 提示)。码表缺失时返回 ("", 提示)。"""
        from .. import gamecode

        if not gamecode.configured():
            return "", "⚠ 未找到汉化码表，无法生成中文码"
        line = gamecode.encode(zh_text)
        if not line:
            return "", "⚠ 没有可编码的中文"
        return line, ""

    def _compose_reply(self, zh_text: str, target: str, translation: str) -> tuple[str, str]:
        """按勾选拼装回话结果。

        - 中文码 + 译文：``[zh] @中文码`` 换行 ``[en] 译文``（双方都看得懂）
        - 只译文：仅译文（默认）
        - 只中文码：在上面单独处理（不需要 API）
        """
        if not self._reply_out_code.isChecked():
            return translation, ""
        code_line, note = self._reply_code_line(zh_text)
        if not code_line:
            return translation, note + "（本次只输出译文）"
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
        self._set_status(t("status.fail", msg=msg))
        QMessageBox.warning(self, t("dlg.fail.title"), str(msg))

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
