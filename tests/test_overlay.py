"""译文悬浮框（常驻置顶）回归：按需结果累积、同文去重、上限淘汰、回话开关与文案。

全部离屏运行（conftest 已设 QT_QPA_PLATFORM=offscreen）：不抓屏、不联网、不真显示窗口。
"""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SC_CI_SKIP_GUI", "") == "1", reason="环境跳过")


def _mk_ctrl(qapp, tmp_home, **kw):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    s = Settings().load()
    s.theme = "dark"
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    ctrl = AppController(qapp, settings=s)
    ctrl.init_ui()
    return ctrl


def _wait_for(qapp, pred, timeout_s: float = 3.0) -> bool:
    """跑事件循环直到 pred() 为真（后台线程的结果经 Qt 信号回主线程）。"""
    end = time.time() + timeout_s
    while time.time() < end:
        qapp.processEvents()
        if pred():
            return True
        time.sleep(0.02)
    qapp.processEvents()
    return bool(pred())


# ---------------------------------------------------------------- 装配
def test_overlay_is_created_and_hidden_by_default(qapp, tmp_home):
    """浮窗随主窗口一起装配，且默认不显示（不按键不打扰）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    assert ctrl.overlay is not None, "译文悬浮框应随主窗口一起创建"
    assert not ctrl.overlay.isVisible(), "默认不应显示浮窗"
    assert ctrl.overlay.ctx is ctrl, "浮窗 ctx 应为 AppController"
    ctrl.shutdown()


def test_push_lines_accumulates_and_dedupes(qapp, tmp_home):
    """两次截图翻译：同文只占一行，新文追加（历史累积，不是"整屏快照消失即删"）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win._push_overlay_rows([("Quantum travel to Crusader", "量子航行至十字军")])
    assert ctrl.overlay.isVisible(), "有新结果时应自动显示浮窗"
    win._push_overlay_rows(
        [
            ("Quantum travel to Crusader", "量子航行至十字军"),
            ("Bounty mission updated", "赏金任务已更新"),
        ]
    )
    assert list(ctrl.overlay._rows) == ["Quantum travel to Crusader", "Bounty mission updated"]
    ctrl.shutdown()


def test_max_entries_evicts_oldest(qapp, tmp_home):
    """超过 settings.max_entries 时淘汰最早的行（该设置此前是零读取的死配置）。"""
    ctrl = _mk_ctrl(qapp, tmp_home, max_entries=2)
    ctrl.mainwin._push_overlay_rows([("A", "甲"), ("B", "乙"), ("C", "丙")])
    assert list(ctrl.overlay._rows) == ["B", "C"]
    ctrl.shutdown()


def test_clear_all_empties_rows(qapp, tmp_home):
    """清空：行全部移除、计数归零。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    ctrl.mainwin._push_overlay_rows([("A", "甲"), ("B", "乙")])
    ctrl.overlay.clear_all()
    assert ctrl.overlay._rows == {}
    assert "0" in ctrl.overlay._count.text()
    ctrl.shutdown()


# ---------------------------------------------------------------- 开关
def test_reply_enabled_toggles_reply_panel(qapp, tmp_home):
    """reply_enabled 真正决定浮窗回话输入条显隐（此前该字段零读取）。

    注意用 isHidden() 而不是 isVisible()：父窗口未显示时，子控件的 isVisible() 恒为假。
    """
    ctrl = _mk_ctrl(qapp, tmp_home, reply_enabled=False)
    assert ctrl.overlay._reply_panel.isHidden(), "关着时回话条应隐藏"

    ctrl.mainwin._ov_reply.setChecked(True)
    assert not ctrl.overlay._reply_panel.isHidden(), "打开后回话条应显示"
    assert ctrl.settings.reply_enabled is True, "开关应落盘"

    ctrl.mainwin._ov_reply.setChecked(False)
    assert ctrl.overlay._reply_panel.isHidden()
    assert ctrl.settings.reply_enabled is False
    ctrl.shutdown()


def test_overlay_reply_copies_only_when_auto_copy_on(qapp, tmp_home):
    """auto_copy_reply 真正决定浮窗回话是否自动进剪贴板（此前该字段零读取）。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(qapp, tmp_home, reply_enabled=True, auto_copy_reply=True)

    def fake_handler(text, target, done):
        done(True, f"[{target}]{text}")

    ctrl.translate_reply_async = fake_handler  # 同步替身，不联网
    ov = ctrl.overlay
    ov._reply_input.setText("你好吗")
    ov._send_reply()
    assert QApplication.clipboard().text() == "[English]你好吗"
    assert ov._exchanges == [("你好吗", "[English]你好吗", "English")], "应记录一条问答"

    QApplication.clipboard().setText("(未复制)")
    ctrl.mainwin._ov_autocopy.setChecked(False)
    assert ctrl.settings.auto_copy_reply is False
    ov._reply_input.setText("再来一次")
    ov._send_reply()
    assert QApplication.clipboard().text() == "(未复制)", "关掉自动复制后不应写入剪贴板"
    assert len(ov._exchanges) == 2
    ctrl.shutdown()


def test_translate_reply_async_reports_missing_key(qapp, tmp_home):
    """未配置 API Key 时，浮窗回话应回调失败并给出可读原因（不是抛异常）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    assert not ctrl.settings.load_api_key(), "临时数据目录里不应有 Key"
    got = []
    ctrl.translate_reply_async("你好", "English", lambda ok, val: got.append((ok, val)))
    assert got and got[0][0] is False
    assert isinstance(got[0][1], str) and got[0][1]
    ctrl.shutdown()


def test_translate_reply_async_uses_client(qapp, tmp_home):
    """有 Key 时走后台线程翻译，并在主线程回调 done(True, 译文)。"""

    class _FakeClient:
        def translate_reply(self, text, target, spicy=False):
            return f"[{target}]{text}"

    ctrl = _mk_ctrl(qapp, tmp_home)
    ctrl.settings.save_api_key("sk-test")
    ctrl.make_client = lambda use_cache=True: _FakeClient()
    got = []
    ctrl.translate_reply_async("你好", "Korean", lambda ok, val: got.append((ok, val)))
    assert _wait_for(qapp, lambda: bool(got)), "应在超时前回调"
    assert got == [(True, "[Korean]你好")]
    ctrl.shutdown()


# ---------------------------------------------------------------- 文案/主题
def test_overlay_texts_follow_language(qapp, tmp_home):
    """浮窗文案走 i18n：切语言后 retranslate 应换文案（旧版是硬编码中文）。"""
    from sc_translator import i18n

    ctrl = _mk_ctrl(qapp, tmp_home)
    ov = ctrl.overlay
    i18n.set_language("zh_CN")
    ov.retranslate()
    zh = ov._title.text()
    i18n.set_language("en")
    ov.retranslate()
    en = ov._title.text()
    assert zh != en, (zh, en)
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in en), en
    ctrl.shutdown()


def test_overlay_theme_refresh_does_not_crash(qapp, tmp_home):
    """主题/文案刷新（主窗口每次改设置都会回调）不应抛异常。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    ctrl.mainwin.refresh_overlay_controls()
    ctrl.overlay.apply_theme()
    ctrl.overlay.apply_click_through()
    ctrl.shutdown()


# ---------------------------------------------------------------- 显示位置开关
class _FakeRes:
    """替身：_show_snap_result 只用到 pairs()/error/elapsed_ms/ocr_ms。"""

    error = ""
    elapsed_ms = 0
    ocr_ms = 0

    def __init__(self, pairs):
        self._pairs = list(pairs)

    def pairs(self):
        return self._pairs


def test_both_output_switches_on_by_default(qapp, tmp_home):
    """默认两个显示位置都开：结果既进常驻浮窗，也弹鼠标旁快看浮窗。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    assert win._snap_overlay.isChecked() and win._snap_popup.isChecked()
    win._show_snap_result(_FakeRes([("Quantum travel", "量子航行")]))
    assert list(ctrl.overlay._rows) == ["Quantum travel"]
    assert win._popup is not None and win._popup.isVisible()
    ctrl.shutdown()


def test_overlay_switch_off_keeps_results_in_main_window(qapp, tmp_home):
    """关掉「常驻悬浮窗」：结果不再进浮窗，但仍写主窗口结果区（手动复制路径）。"""
    ctrl = _mk_ctrl(qapp, tmp_home, snap_show_overlay=False)
    win = ctrl.mainwin
    win._show_snap_result(_FakeRes([("Quantum travel", "量子航行")]))
    assert ctrl.overlay._rows == {}, "关掉后不应再有浮窗行"
    assert win._snap_src.toPlainText() == "Quantum travel"
    assert win._snap_dst.toPlainText() == "量子航行"
    ctrl.shutdown()


def test_popup_switch_off_skips_cursor_popup(qapp, tmp_home):
    """关掉「鼠标旁浮窗」：不弹快看浮窗，但常驻浮窗与主窗口照常收到结果。"""
    ctrl = _mk_ctrl(qapp, tmp_home, snap_show_popup=False)
    win = ctrl.mainwin
    win._show_snap_result(_FakeRes([("Quantum travel", "量子航行")]))
    assert win._popup is None or not win._popup.isVisible()
    assert list(ctrl.overlay._rows) == ["Quantum travel"]
    assert win._snap_dst.toPlainText() == "量子航行"
    ctrl.shutdown()


def test_both_switches_off_only_main_window(qapp, tmp_home):
    """两个都关：只写主窗口结果区，两个浮窗都不出现（由用户手动复制）。"""
    ctrl = _mk_ctrl(qapp, tmp_home, snap_show_overlay=False, snap_show_popup=False)
    win = ctrl.mainwin
    win._show_snap_result(_FakeRes([("Quantum travel", "量子航行")]))
    assert ctrl.overlay._rows == {}
    assert not ctrl.overlay.isVisible()
    assert win._popup is None
    assert win._snap_dst.toPlainText() == "量子航行"
    ctrl.shutdown()


def test_overlay_checkbox_shows_and_hides_overlay(qapp, tmp_home):
    """勾选框即时生效：打开=立刻露出，关闭=立刻收起，并写进设置。"""
    ctrl = _mk_ctrl(qapp, tmp_home, snap_show_overlay=False)
    win = ctrl.mainwin
    win._snap_overlay.setChecked(True)
    assert ctrl.settings.snap_show_overlay is True
    assert ctrl.overlay.isVisible()
    win._snap_overlay.setChecked(False)
    assert ctrl.settings.snap_show_overlay is False
    assert not ctrl.overlay.isVisible()
    ctrl.shutdown()


# ---------------------------------------------------------------- 旋钮控件（第 12 轮）
def test_overlay_knob_widgets_reflect_settings(qapp, tmp_home):
    """原先"只能改 settings.json"的旋钮，现在都有控件且反映当前设置。"""
    ctrl = _mk_ctrl(
        qapp, tmp_home,
        snap_max_lines=25, snap_write_main=False,
        always_show=False, auto_hide_sec=5, max_entries=77,
        font_size=16, opacity=60, show_original=False, click_through=False,
    )
    win = ctrl.mainwin
    assert win._snap_max_lines.value() == 25
    assert win._snap_write_main.isChecked() is False
    assert win._ov_always.isChecked() is False
    assert win._ov_auto_hide.value() == 5
    assert win._ov_max_entries.value() == 77
    assert win._ov_font.value() == 16
    assert win._ov_opacity.value() == 60
    assert win._ov_show_original.isChecked() is False
    assert win._ov_click_through.isChecked() is False
    ctrl.shutdown()


def test_overlay_knob_edits_persist_and_apply(qapp, tmp_home):
    """改控件立即落盘，并按需即时生效（样式重刷、穿透态同步）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin

    win._ov_max_entries.setValue(300)
    assert ctrl.settings.max_entries == 300
    # 调小上限要立即裁剪已有行，而不是等下次截图
    ctrl.mainwin._push_overlay_rows([(f"L{i}", f"译{i}") for i in range(5)])
    assert len(ctrl.overlay._rows) == 5
    win._ov_max_entries.setValue(2)
    assert len(ctrl.overlay._rows) == 2, list(ctrl.overlay._rows)
    win._ov_font.setValue(18)
    assert ctrl.settings.font_size == 18
    win._ov_opacity.setValue(70)
    assert ctrl.settings.opacity == 70
    win._ov_auto_hide.setValue(9)
    assert ctrl.settings.auto_hide_sec == 9
    win._snap_max_lines.setValue(80)
    assert ctrl.settings.snap_max_lines == 80
    win._snap_write_main.setChecked(False)
    assert ctrl.settings.snap_write_main is False
    win._ov_always.setChecked(False)
    assert ctrl.settings.always_show is False

    # 穿透开关：取消勾选 = 进入固定态；重新勾选 = 回到穿透态
    win._ov_click_through.setChecked(False)
    assert ctrl.settings.click_through is False and ctrl.overlay.pinned() is True
    win._ov_click_through.setChecked(True)
    assert ctrl.settings.click_through is True and ctrl.overlay.pinned() is False
    ctrl.shutdown()


def test_show_original_toggle_rerenders_existing_rows(qapp, tmp_home):
    """「显示原文」关掉后应**立即重渲染已有行**，而不是等下次截图。"""
    from PySide6.QtWidgets import QLabel

    ctrl = _mk_ctrl(qapp, tmp_home, show_original=True)
    win = ctrl.mainwin
    win._push_overlay_rows([("Hello there", "你好")])
    row = ctrl.overlay._rows["Hello there"]
    lbl = row.findChild(QLabel)
    assert "Hello there" in lbl.text()

    win._ov_show_original.setChecked(False)
    assert "Hello there" not in lbl.text(), lbl.text()
    assert ctrl.settings.show_original is False
    ctrl.shutdown()
