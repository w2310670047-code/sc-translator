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

from .. import DEFAULT_MODEL, __version__
from .. import i18n
from ..i18n import t
from ..paths import logs_dir
from ..settings import PROVIDER_PRESETS
from .widgets import HotkeyEdit, KeyLine, make_card

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
        # 恢复上次选择：设置里虽存了 reply_target，此前界面既不恢复也不写回，
        # 于是选 Japanese/Korean 后重启会悄悄回到 English。
        idx = self._reply_target.findText(str(s.reply_target or ""))
        if idx >= 0:
            self._reply_target.setCurrentIndex(idx)
        self._reply_target.currentTextChanged.connect(self._save_reply_target)
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

        # ---------------- 按需截图翻译（热键触发）----------------
        snap_card, snap = make_card(t("snap.title"))
        srow = QHBoxLayout()
        self._snap_enable = QCheckBox(t("snap.enable"))
        self._snap_enable.setChecked(bool(s.snap_enabled))
        self._snap_enable.toggled.connect(self._on_snap_enabled)
        srow.addWidget(self._snap_enable)
        srow.addWidget(QLabel(t("snap.key_label")))
        # 点一下直接按组合键录入；录入期间临时注销全局热键，避免按键本身触发动作
        self._snap_key = HotkeyEdit(
            s.snap_hotkey, on_edit_start=self._begin_hotkey_edit, on_edit_done=self._on_snap_keys_changed
        )
        self._snap_key.setFixedWidth(130)
        srow.addWidget(self._snap_key)
        srow.addWidget(QLabel(t("snap.key_select_label")))
        self._snap_key2 = HotkeyEdit(
            s.snap_hotkey_select, on_edit_start=self._begin_hotkey_edit, on_edit_done=self._on_snap_keys_changed
        )
        self._snap_key2.setFixedWidth(130)
        srow.addWidget(self._snap_key2)
        self._btn_snap_now = QPushButton(t("snap.btn_now"))
        self._btn_snap_now.clicked.connect(self.on_snap_hotkey)
        srow.addWidget(self._btn_snap_now)
        self._btn_snap_region = QPushButton(t("snap.btn_region"))
        self._btn_snap_region.clicked.connect(self.on_snap_select_hotkey)
        srow.addWidget(self._btn_snap_region)
        srow.addStretch(1)
        snap.addLayout(srow)

        # 结果显示位置：常驻悬浮窗 / 鼠标旁浮窗（两个都关=只写主窗口结果区，手动复制）
        drow = QHBoxLayout()
        drow.addWidget(QLabel(t("snap.col_out")))
        self._snap_overlay = QCheckBox(t("chk.snap_overlay"))
        self._snap_overlay.setChecked(bool(s.snap_show_overlay))
        self._snap_overlay.setToolTip(t("chk.snap_overlay.tip"))
        self._snap_overlay.toggled.connect(self._on_snap_overlay_toggled)
        drow.addWidget(self._snap_overlay)
        self._snap_popup = QCheckBox(t("chk.snap_popup"))
        self._snap_popup.setChecked(bool(s.snap_show_popup))
        self._snap_popup.setToolTip(t("chk.snap_popup.tip", sec=int(s.snap_popup_sec or 0)))
        self._snap_popup.toggled.connect(self._on_snap_popup_toggled)
        drow.addWidget(self._snap_popup)
        drow.addStretch(1)
        snap.addLayout(drow)

        # 浮窗相关：回话输入条 / 自动复制 / 手动叫回浮窗（在浮窗里点过 ✕ 之后用）
        orow = QHBoxLayout()
        self._ov_reply = QCheckBox(t("chk.ov_reply"))
        self._ov_reply.setChecked(bool(s.reply_enabled))
        self._ov_reply.setToolTip(t("chk.ov_reply.tip"))
        self._ov_reply.toggled.connect(self._on_ov_reply_toggled)
        orow.addWidget(self._ov_reply)
        self._ov_autocopy = QCheckBox(t("chk.ov_autocopy"))
        self._ov_autocopy.setChecked(bool(s.auto_copy_reply))
        self._ov_autocopy.setToolTip(t("chk.ov_autocopy.tip"))
        self._ov_autocopy.toggled.connect(self._on_ov_autocopy_toggled)
        orow.addWidget(self._ov_autocopy)
        self._btn_ov_show = QPushButton(t("ov.show"))
        self._btn_ov_show.setToolTip(t("ov.show.tip"))
        self._btn_ov_show.clicked.connect(self._show_overlay)
        orow.addWidget(self._btn_ov_show)
        orow.addStretch(1)
        snap.addLayout(orow)

        self._snap_state = QLabel("…")
        self._snap_state.setObjectName("hint")
        snap.addWidget(self._snap_state)

        sbody = QHBoxLayout()
        sbody.addWidget(QLabel(t("snap.col_src")))
        self._snap_src = QPlainTextEdit()
        self._snap_src.setReadOnly(True)
        self._snap_src.setMinimumHeight(80)
        sbody.addWidget(self._snap_src, 1)
        sbody.addWidget(QLabel(t("snap.col_dst")))
        self._snap_dst = QPlainTextEdit()
        self._snap_dst.setReadOnly(True)
        self._snap_dst.setMinimumHeight(80)
        sbody.addWidget(self._snap_dst, 1)
        snap.addLayout(sbody)
        root.addWidget(snap_card)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._translate_to_zh)
        QShortcut(QKeySequence("Ctrl+Enter"), self, activated=self._translate_to_zh)
        self._busy = False
        self._gc_timer = None
        self._gc_syncing = False
        self._gc_busy = False
        self._dual_syncing = False
        self._snap_busy = False
        self._picker = None
        self._popup = None
        self._shutting_down = False
        self._refresh_gamecode_state()
        self._refresh_gc_mode()
        self._refresh_snap_state()

    # ---------------- 按需截图翻译 ----------------
    def _refresh_snap_state(self) -> None:
        from ..snapshot import hotkey_label

        s = self.app.settings
        region = s.snap_region or {}
        lab = region.get("label") or ""
        logi = region.get("logical") or {}
        if logi:
            area = f"{logi.get('w', 0)}×{logi.get('h', 0)} @({logi.get('x', 0)},{logi.get('y', 0)})"
        else:
            area = t("snap.state_no_region")
        hot = hotkey_label(s.snap_hotkey)
        hot2 = hotkey_label(s.snap_hotkey_select)
        state = t("snap.state", key=hot, key2=hot2, area=area, label=lab)
        warn = False
        if not s.snap_enabled:
            state += "  " + t("snap.disabled")
            warn = True
        elif getattr(self.app, "hotkeys", None) is None:
            # 注册失败：最常见原因是"已有另一个实例在运行"或热键被别的软件占用
            state += "  " + t("snap.status_fail")
            warn = True
        self._snap_state.setText(state)
        self._snap_state.setStyleSheet("color:#f5b83d;" if warn else "")
        self._snap_enable.setChecked(bool(s.snap_enabled))
        self._snap_key.setSpec(s.snap_hotkey)
        self._snap_key2.setSpec(s.snap_hotkey_select)

    def _on_snap_enabled(self, on: bool) -> None:
        self.app.settings.snap_enabled = bool(on)
        self.app.settings.save()
        if on:
            if self.app.install_hotkeys():
                self._set_status(t("snap.status_on"))
            else:
                self._set_status(t("snap.status_fail"))
        else:
            self.app.remove_hotkeys()
            self._set_status(t("snap.status_off"))
        self._refresh_snap_state()

    def _push_overlay_rows(self, pairs) -> None:
        """把本次截图翻译结果推给常驻浮窗（同文原地更新，不重复占行）。

        受「常驻悬浮窗」开关控制；关掉时结果仍写主窗口结果区（可手动复制）。
        """
        if not self.app.settings.snap_show_overlay:
            return
        ov = getattr(self.app, "overlay", None)
        if ov is None:
            return
        try:
            ov.push_lines(
                [{"key": src, "text": src, "translated": dst, "pending": False} for src, dst in pairs]
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("推送浮窗失败（忽略）: %s", exc)

    def _show_overlay(self) -> None:
        """显示译文悬浮框（在浮窗里点过 ✕ 之后，靠这个按钮把它叫回来）。"""
        try:
            self.app.ensure_overlay().show_overlay()
        except Exception as exc:  # noqa: BLE001
            self._set_status(t("ov.show_fail", msg=exc))

    def _on_ov_reply_toggled(self, on: bool) -> None:
        """浮窗回话输入条开关：落盘并即时生效。"""
        s = self.app.settings
        s.reply_enabled = bool(on)
        s.save()
        ov = getattr(self.app, "overlay", None)
        if ov is not None:
            ov.set_reply_enabled(bool(on), notify_main=False)

    def _on_ov_autocopy_toggled(self, on: bool) -> None:
        """浮窗回话译文自动复制开关：落盘（浮窗回话时实时读取该设置）。"""
        s = self.app.settings
        s.auto_copy_reply = bool(on)
        s.save()

    def _on_snap_overlay_toggled(self, on: bool) -> None:
        """常驻悬浮窗开关：落盘；关掉时立即收起，打开时立即露出（否则看不出开了什么）。"""
        s = self.app.settings
        s.snap_show_overlay = bool(on)
        s.save()
        ov = getattr(self.app, "overlay", None)
        if ov is None:
            return
        if on:
            ov.show_overlay()
        else:
            ov.hide_overlay()

    def _on_snap_popup_toggled(self, on: bool) -> None:
        """鼠标旁快看浮窗开关：落盘；关掉时把已经弹出的那个收起。"""
        s = self.app.settings
        s.snap_show_popup = bool(on)
        s.save()
        if not on and getattr(self, "_popup", None) is not None:
            self._popup.hide_popup()

    # ---- 热键录入 ----
    def _begin_hotkey_edit(self) -> None:
        """进入录入态：先注销全局热键，否则用户按下的就是旧热键（会真的去截图/弹框选）。"""
        if self._shutting_down:
            return
        log.info("开始录入热键：临时注销全局热键")
        self.app.suspend_hotkeys()
        self._set_status(t("snap.recording"))

    def _on_snap_keys_changed(self) -> None:
        """录入结束：校验 -> 落盘 -> 重新注册；失败则回滚到原来的可用组合。"""
        if self._shutting_down:
            return          # 关窗/销毁过程中失焦会走到这里，直接跳过
        try:
            self._apply_snap_keys()
        except RuntimeError as exc:
            # 窗口（C++ 侧）已销毁时，延迟回调仍可能走到这里
            log.debug("窗口已销毁，跳过热键应用: %s", exc)

    def _apply_snap_keys(self) -> None:
        from ..snapshot import parse_hotkey

        s = self.app.settings
        old = (s.snap_hotkey, s.snap_hotkey_select)
        new = (self._snap_key.spec().strip(), self._snap_key2.spec().strip())

        # 1) 格式校验
        for spec in new:
            if parse_hotkey(spec) is None:
                self._revert_hotkeys(old, t("snap.bad_key", spec=spec))
                return
        # 2) 不允许两个热键相同（同一个组合只能注册一次）
        if new[0] == new[1]:
            self._revert_hotkeys(old, t("snap.same_key", spec=new[0]))
            return

        s.snap_hotkey, s.snap_hotkey_select = new
        s.save()
        if not s.snap_enabled:
            self._set_status(t("snap.status_off"))
            self._refresh_snap_state()
            return

        count = self.app.install_hotkeys()
        if count == 2:
            self._set_status(t("snap.status_rebind"))
        elif count == 1:
            failed = t("snap.key_label") if not self.app.hotkey_ok.get("capture") else t("snap.key_select_label")
            self._set_status(t("snap.partial_fail", which=failed))
        else:
            # 全失败：把上次可用的组合改回去并重新注册，别让用户"一个热键都没有"
            self._revert_hotkeys(old, t("snap.status_fail"), reinstall=True)
            return
        self._refresh_snap_state()

    def _revert_hotkeys(self, old: tuple[str, str], note: str, reinstall: bool = True) -> None:
        s = self.app.settings
        s.snap_hotkey, s.snap_hotkey_select = old
        s.save()
        log.warning("热键设置未生效（%s），回滚为 %s / %s", note, old[0], old[1])
        if reinstall and s.snap_enabled:
            self.app.install_hotkeys()
        self._refresh_snap_state()
        self._set_status(note)
        QMessageBox.warning(self, t("dlg.notice"), note)

    def on_snap_hotkey(self) -> None:
        """热键：抓取记住的区域 -> OCR -> 翻译 -> 浮窗 + 主窗口。"""
        s = self.app.settings
        region = s.snap_region or {}
        if not (region.get("physical")):
            self._set_status(t("snap.need_region"))
            self.on_snap_select_hotkey()
            return
        if self._snap_busy:
            return
        log.info("热键触发截图翻译：区域=%s", (region.get("physical")))
        self._snap_busy = True
        self._btn_snap_now.setEnabled(False)
        self._set_status(t("snap.working"))

        def done(res) -> None:
            self._snap_busy = False
            self._btn_snap_now.setEnabled(True)
            self._show_snap_result(res)

        self.app.snapshot.run(
            region, done, max_lines=int(s.snap_max_lines or 40), use_cache=True
        )

    def _show_snap_result(self, res) -> None:
        s = self.app.settings
        pairs = res.pairs()
        note_bits = []
        if res.error:
            note_bits.append(res.error)
        if res.elapsed_ms:
            note_bits.append(t("snap.note_timing", ocr=res.ocr_ms, total=res.elapsed_ms))
        note = "  ".join(note_bits)

        if pairs and s.snap_write_main:
            self._snap_src.setPlainText("\n".join(a for a, _ in pairs))
            self._snap_dst.setPlainText("\n".join(b for _, b in pairs))
        if pairs:
            self._push_overlay_rows(pairs)
        if not pairs:
            self._set_status(note or t("snap.no_text"))
        else:
            self._set_status(t("snap.done", n=len(pairs)))

        if not s.snap_show_popup:
            return
        from .snap_popup import SnapPopup

        if self._popup is None:
            self._popup = SnapPopup()
            self._popup.copyRequested.connect(lambda txt: self._copy_text(txt, t("snap.copied")))
        if pairs:
            self._popup.show_result(pairs, note=note, auto_hide_sec=int(s.snap_popup_sec or 0))
        else:
            self._popup.show_message(note or t("snap.no_text"), auto_hide_sec=5)

    def on_snap_select_hotkey(self) -> None:
        """热键/按钮：重新框选截图区域。

        关键点（曾经出过 bug）：无论用户是"选中"还是"取消/直接关掉"，
        主窗口都必须回到屏幕上——否则用户会以为程序消失了。
        """
        if self._busy or self._snap_busy:
            self._set_status(t("snap.busy"))
            return
        if getattr(self, "_picker", None) is not None:
            # 再按一次 = 取消框选
            try:
                self._picker.close()
            except RuntimeError:
                pass
            self._restore_after_pick()
            return

        from .region_select import pick_region

        log.info("框选截图区域：隐藏主窗口并弹出全屏选择器")
        self._set_status(t("snap.selecting"))
        self.hide()
        try:
            win = pick_region(cb=self._on_snap_region_picked)
        except Exception as exc:  # noqa: BLE001
            log.exception("框选窗口创建失败: %s", exc)
            self._restore_after_pick()
            QMessageBox.warning(self, t("dlg.notice"), t("snap.region_fail"))
            return
        self._picker = win
        win.cancelled.connect(self._restore_after_pick)
        win.destroyed.connect(self._restore_after_pick)
        log.info("框选选择器已显示：%s", win.geometry().getRect())

    def _on_snap_region_picked(self, logical) -> None:
        self._apply_snap_region(logical)
        self._restore_after_pick()

    def _restore_after_pick(self, *_args) -> None:
        """框选收尾：把主窗口还回来（幂等，多次调用无副作用）。"""
        self._picker = None
        if self.isVisible():
            return
        self.show()
        self.raise_()
        self.activateWindow()
        log.info("框选结束，主窗口已恢复")

    def _apply_snap_region(self, logical) -> None:
        """把框选的**全局逻辑**矩形换算并保存（含多屏/DPI 物理区域）。"""
        try:
            from ..screen import (
                ScreenInfo,
                build_layouts,
                logical_rect_to_physical,
            )
            from PySide6.QtGui import QGuiApplication

            rect = (logical.x(), logical.y(), logical.width(), logical.height())
            screens = []
            for idx, sc in enumerate(QGuiApplication.screens()):
                g = sc.geometry()
                screens.append(
                    ScreenInfo(
                        index=idx,
                        logical=(g.x(), g.y(), g.width(), g.height()),
                        dpr=float(sc.devicePixelRatio()),
                    )
                )
            layouts = build_layouts(screens)
            phys = logical_rect_to_physical(layouts, rect)
            if phys is None:
                log.warning("框选区域不在任何显示器内：%s", rect)
                self._set_status(t("snap.region_fail"))
                return
            label = ""
            for lay in layouts:
                ox, oy = lay.phys_origin
                pw, ph = lay.phys_size
                if ox <= phys["left"] < ox + pw and oy <= phys["top"] < oy + ph:
                    label = f"屏幕{lay.info.index + 1}"
                    break
            self.app.settings.snap_region = {
                "logical": {"x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3]},
                "physical": phys,
                "label": label,
            }
            self.app.settings.save()
            log.info(
                "截图区域已保存：logical=%s physical=%s label=%s",
                self.app.settings.snap_region["logical"], phys, label,
            )
            self._set_status(t("snap.region_saved", w=rect[2], h=rect[3], label=label))
        except Exception as exc:  # noqa: BLE001
            log.exception("保存截图区域失败: %s", exc)
            self._set_status(t("snap.region_fail"))
        self._refresh_snap_state()

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
        client.opts.model = self._model.currentText().strip() or DEFAULT_MODEL
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

        # 任何"显式复制"都要先取消游戏码卡片的防抖自动复制，
        # 否则 0.8 秒后它会把剪贴板覆盖成旧内容（真实踩到过：回话刚复制完就被顶掉）。
        self._gc_timer_stop()
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

    def _save_reply_target(self, text: str) -> None:
        """回话目标语言落盘（此前界面既不恢复也不写回，选完重启就丢）。"""
        self.app.settings.reply_target = str(text)
        self.app.settings.save()

    def _persist_api(self) -> bool:
        key = self._keyline.text().strip()
        if not key:
            QMessageBox.warning(self, t("dlg.no_key.title"), t("dlg.no_key.body"))
            return False
        self.app.settings.api_base = self._api_base.text().strip()
        self.app.settings.model = self._model.currentText().strip() or DEFAULT_MODEL
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
        client.opts.model = self._model.currentText().strip() or DEFAULT_MODEL

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
        client.opts.model = self._model.currentText().strip() or DEFAULT_MODEL
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
        client.opts.model = self._model.currentText().strip() or DEFAULT_MODEL
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

    # ---------------- 与浮窗的双向同步 ----------------
    def refresh_overlay_controls(self) -> None:
        """浮窗侧改了状态（嘴臭/固定/穿透）→ 回同步主窗口控件，并刷新浮窗文案与主题。

        旧版这里是空桩（浮窗已下线）；现在由 OverlayWindow 在设置变更后回调。
        """
        s = self.app.settings
        blk = self._spicy.blockSignals(True)
        self._spicy.setChecked(bool(s.spicy_mode))
        self._spicy.blockSignals(blk)
        for box, value in (
            (getattr(self, "_ov_reply", None), bool(s.reply_enabled)),
            (getattr(self, "_ov_autocopy", None), bool(s.auto_copy_reply)),
            (getattr(self, "_snap_overlay", None), bool(s.snap_show_overlay)),
            (getattr(self, "_snap_popup", None), bool(s.snap_show_popup)),
        ):
            if box is None:
                continue
            blk = box.blockSignals(True)
            box.setChecked(value)
            box.blockSignals(blk)
        ov = getattr(self.app, "overlay", None)
        if ov is not None:
            ov.apply_theme()
            ov.retranslate()
            ov.set_reply_enabled(bool(s.reply_enabled), notify_main=False)

    def _open_logs(self) -> None:
        try:
            os.startfile(logs_dir())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            subprocess.Popen(["explorer", str(logs_dir())])

    def closeEvent(self, ev: QCloseEvent) -> None:
        # 先标记关闭中：热键录入框失焦会回调到本窗口，此时窗口可能已在销毁
        self._shutting_down = True
        self._gc_timer_stop()
        try:
            if self._popup is not None:
                self._popup.hide_popup()
        except Exception:  # noqa: BLE001
            pass
        self.app.shutdown()
        super().closeEvent(ev)
