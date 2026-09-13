"""热键设置回归：按键录入、录入期间注销全局热键、校验与回滚。

背景（真实反馈"设置快捷键有问题"）：热键框原是普通文本框，得手打 "F9"；
而用户点进去按 F9 时，**全局热键会被系统触发**（去截图甚至弹框选把主窗口藏起来）。
另外：改键失败时旧热键会丢、两个热键可以设成同一个、注册失败也显示"已更新"。

注意：本测试不依赖 Windows 真的注册成功（offscreen 下 winId 不是真实 HWND），
统一用假的 register 控制成功/失败。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from sc_translator import hotkeys
from sc_translator.snapshot import spec_from_qt


@pytest.fixture(autouse=True)
def _no_dialogs(monkeypatch):
    """任何弹窗都会卡住无头测试，统一替换掉。"""
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))


@pytest.fixture()
def fake_register(monkeypatch):
    """可控的假 RegisterHotKey：默认全部成功；fail_all / fail_ids 可指定失败。"""
    state = {"calls": [], "fail_all": False, "fail_after": None}

    def fake(hwnd, hid, mods, vk):
        state["calls"].append((hid, mods, vk))
        if state["fail_all"]:
            return False
        if state["fail_after"] is not None and len(state["calls"]) > state["fail_after"]:
            return False
        return True

    monkeypatch.setattr(hotkeys, "register", fake)
    monkeypatch.setattr(hotkeys, "unregister", lambda *a, **k: None)
    return state


# ------------------------------------------------------------------ 键码 -> 热键串
@pytest.mark.parametrize(
    "key,mods,text,expect",
    [
        (Qt.Key.Key_F9, Qt.KeyboardModifier.NoModifier, "", "F9"),
        (Qt.Key.Key_F10, Qt.KeyboardModifier.NoModifier, "", "F10"),
        (Qt.Key.Key_F1, Qt.KeyboardModifier.NoModifier, "", "F1"),
        (Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier, "", "F12"),
        (Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier, "S", "Ctrl+Shift+S"),
        (Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "z", "Ctrl+Z"),
        (Qt.Key.Key_5, Qt.KeyboardModifier.AltModifier, "5", "Alt+5"),
        (Qt.Key.Key_Print, Qt.KeyboardModifier.NoModifier, "", "PRINTSCREEN"),
        (Qt.Key.Key_Home, Qt.KeyboardModifier.NoModifier, "", "HOME"),
        (Qt.Key.Key_Insert, Qt.KeyboardModifier.ControlModifier, "", "Ctrl+INSERT"),
    ],
)
def test_spec_from_qt_accepts(key, mods, text, expect):
    assert spec_from_qt(key, mods.value, text) == expect


@pytest.mark.parametrize(
    "key,mods,text",
    [
        (Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier, "s"),       # 纯字母：会抢走整个键盘
        (Qt.Key.Key_5, Qt.KeyboardModifier.NoModifier, "5"),       # 纯数字同理
        (Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier, ""),
        (Qt.Key.Key_MediaPlay, Qt.KeyboardModifier.NoModifier, ""),  # 不支持的键
    ],
)
def test_spec_from_qt_rejects(key, mods, text):
    assert spec_from_qt(key, mods.value, text) is None


def test_named_key_table_matches_qt():
    """命名键码表必须与 Qt 实际枚举一致（曾经把 Insert/PageUp 等写错，静默失效）。"""
    from sc_translator.snapshot import _QT_NAMED_BY_CODE

    for qt_name, ours in [
        ("Key_Escape", "ESC"),
        ("Key_Tab", "TAB"),
        ("Key_Return", "ENTER"),
        ("Key_Insert", "INSERT"),
        ("Key_Pause", "PAUSE"),
        ("Key_Print", "PRINTSCREEN"),
        ("Key_Home", "HOME"),
        ("Key_End", "END"),
        ("Key_PageUp", "PAGEUP"),
        ("Key_PageDown", "PAGEDOWN"),
        ("Key_Space", "SPACE"),
    ]:
        code = int(getattr(Qt.Key, qt_name).value)
        assert _QT_NAMED_BY_CODE.get(code) == ours, f"{qt_name} 映射不对（0x{code:08X}）"


def test_modifier_masks_match_qt():
    """修饰键掩码必须与 Qt 一致：Ctrl/Shift 曾经写反，导致显示的键与注册的键不一致。"""
    from sc_translator.snapshot import _MODIFIER_NAMES

    assert _MODIFIER_NAMES[int(Qt.KeyboardModifier.ControlModifier.value)] == "Ctrl"
    assert _MODIFIER_NAMES[int(Qt.KeyboardModifier.ShiftModifier.value)] == "Shift"
    assert _MODIFIER_NAMES[int(Qt.KeyboardModifier.AltModifier.value)] == "Alt"
    assert spec_from_qt(
        int(Qt.Key.Key_S.value),
        int(Qt.KeyboardModifier.ControlModifier.value) | int(Qt.KeyboardModifier.ShiftModifier.value),
        "S",
    ) == "Ctrl+Shift+S"
    assert spec_from_qt(
        int(Qt.Key.Key_Z.value), int(Qt.KeyboardModifier.ControlModifier.value), "z"
    ) == "Ctrl+Z"


# ------------------------------------------------------------------ 录入控件
@pytest.fixture()
def edit(qapp):
    from sc_translator.ui.widgets import HotkeyEdit

    events: list[str] = []
    w = HotkeyEdit("F9", on_edit_start=lambda: events.append("start"), on_edit_done=lambda: events.append("done"))
    w.show()
    qapp.processEvents()
    yield w, events
    w.close()
    qapp.processEvents()


def test_hotkey_edit_records_keypress(edit, qapp):
    w, events = edit
    assert w.spec() == "F9"
    w.setFocus()
    qapp.processEvents()
    assert "start" in events, "获得焦点应通知外部开始录入（外部据此注销全局热键）"
    QTest.keyClick(w, Qt.Key.Key_F8)
    qapp.processEvents()
    assert w.spec() == "F8", "按键录入应更新热键"
    assert w.text() == "F8"
    assert "done" in events, "录入完成应通知外部保存"


def test_hotkey_edit_ignores_bare_letter(edit, qapp):
    w, _ = edit
    w.setFocus()
    qapp.processEvents()
    QTest.keyClick(w, Qt.Key.Key_S)
    qapp.processEvents()
    assert w.spec() == "F9", "纯字母键必须被拒绝，不能悄悄改掉设置"


def test_hotkey_edit_records_modifier_combo(edit, qapp):
    w, _ = edit
    w.setFocus()
    qapp.processEvents()
    QTest.keyClick(w, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    qapp.processEvents()
    assert w.spec() == "Ctrl+Shift+S", w.spec()


def test_hotkey_edit_escape_keeps_previous(edit, qapp):
    w, _ = edit
    w.setFocus()
    qapp.processEvents()
    QTest.keyClick(w, Qt.Key.Key_F7)
    qapp.processEvents()
    assert w.spec() == "F7"
    w.setFocus()
    qapp.processEvents()
    QTest.keyClick(w, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert w.spec() == "F7", "Esc 只取消本次编辑（保持上一次的值）"


def test_hotkey_edit_is_read_only(edit):
    w, _ = edit
    assert w.isReadOnly(), "热键框应禁止手打文本，只接受按键录入"


# ------------------------------------------------------------------ 主窗口流程
def _ctrl(qapp, tmp_home, **kw):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    s = Settings().load()
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    ctrl = AppController(qapp, settings=s)
    ctrl.init_ui()
    return ctrl


@pytest.fixture()
def ctrl_factory(qapp, tmp_home, fake_register):
    """统一创建/清理：结束后按真实关闭路径收尾，避免遗留窗口与延迟回调干扰后续测试。"""
    made = []

    def make(**kw):
        c = _ctrl(qapp, tmp_home, **kw)
        made.append(c)
        return c

    yield make
    for c in made:
        win = c.mainwin
        if win is not None:
            try:
                win._shutting_down = True
                win.close()
            except RuntimeError:
                pass
        c.shutdown()
    qapp.processEvents()


def test_editing_suspends_and_restores_hotkeys(qapp, ctrl_factory):
    """录入期间必须没有全局热键在生效，否则按下的键会真的触发动作。"""
    ctrl = ctrl_factory(snap_enabled=True)
    win = ctrl.mainwin
    assert ctrl.hotkeys is not None, "启动应注册好热键"
    assert ctrl.hotkey_ok == {"capture": True, "select": True}

    win._begin_hotkey_edit()
    assert ctrl.hotkeys is None, "录入期间应注销全局热键"

    win._snap_key.setSpec("F8")
    win._on_snap_keys_changed()
    assert ctrl.hotkeys is not None, "录入结束后应重新注册"
    assert ctrl.settings.snap_hotkey == "F8"
    assert ctrl.settings.snap_hotkey_select == "F10"


def test_same_hotkeys_rejected_and_reverted(qapp, ctrl_factory):
    ctrl = ctrl_factory(snap_enabled=True, snap_hotkey="F9", snap_hotkey_select="F10")
    win = ctrl.mainwin
    win._snap_key.setSpec("F8")
    win._snap_key2.setSpec("F8")          # 两个热键相同
    win._on_snap_keys_changed()
    assert ctrl.settings.snap_hotkey == "F9", "非法组合必须回滚"
    assert ctrl.settings.snap_hotkey_select == "F10"
    assert ctrl.hotkeys is not None, "回滚后应仍是可用状态"


def test_registration_failure_rolls_back(qapp, ctrl_factory, fake_register):
    """新热键注册失败时：回滚到旧组合并让它重新生效，不能一个热键都不剩。"""
    ctrl = ctrl_factory(snap_enabled=True, snap_hotkey="F9", snap_hotkey_select="F10")
    win = ctrl.mainwin
    fake_register["fail_all"] = True          # 模拟新键被别的程序占用
    win._snap_key.setSpec("F8")
    win._on_snap_keys_changed()
    assert ctrl.settings.snap_hotkey == "F9", "注册失败应回滚设置"
    assert ctrl.settings.snap_hotkey_select == "F10"
    assert ctrl.hotkeys is None, "此时确实没有热键可用（界面会黄字提示）"
    # 占用解除后用户再改一次就能成功
    fake_register["fail_all"] = False
    win._snap_key.setSpec("F6")
    win._on_snap_keys_changed()
    assert ctrl.settings.snap_hotkey == "F6"
    assert ctrl.hotkeys is not None


def test_all_failed_registration_leaves_warning_state(qapp, ctrl_factory, fake_register):
    """全部注册失败时 hotkeys 必须是 None，界面才会显示黄字提示。"""
    fake_register["fail_all"] = True
    ctrl = ctrl_factory(snap_enabled=True)
    assert ctrl.hotkeys is None
    assert ctrl.hotkey_ok == {"capture": False, "select": False}
    win = ctrl.mainwin
    win._refresh_snap_state()
    assert "注册失败" in win._snap_state.text(), win._snap_state.text()
    assert "f5b83d" in win._snap_state.styleSheet(), "失败时应黄字提示"


def test_partial_failure_is_reported(qapp, ctrl_factory, fake_register):
    """只成功一个也要如实显示，而不是笼统说"已更新"。"""
    ctrl = ctrl_factory(snap_enabled=True, snap_hotkey="F9", snap_hotkey_select="F10")
    win = ctrl.mainwin
    fake_register["calls"].clear()
    fake_register["fail_after"] = 1           # 第 2 个（重框）失败
    win._snap_key.setSpec("F8")
    win._on_snap_keys_changed()
    assert ctrl.hotkey_ok["capture"] is True
    assert ctrl.hotkey_ok["select"] is False
    assert "注册失败" in win._status.text(), win._status.text()
    assert ctrl.hotkeys is not None


def test_invalid_spec_via_field_reverts(qapp, ctrl_factory):
    """字段里出现非法值（理论上录不进去）也要回滚而不是崩。"""
    ctrl = ctrl_factory(snap_enabled=True, snap_hotkey="F9", snap_hotkey_select="F10")
    win = ctrl.mainwin
    win._snap_key._spec = "中文键"            # 绕过控件直接注入非法值
    win._on_snap_keys_changed()
    assert ctrl.settings.snap_hotkey == "F9"
    assert ctrl.hotkeys is not None


def test_no_rework_while_shutting_down(qapp, ctrl_factory):
    """关窗过程中热键框失焦会回调到这里：必须直接跳过，否则会摸到已销毁的 C++ 对象。

    真实触发过：RuntimeError: Internal C++ object (MainWindow) already deleted。
    """
    ctrl = ctrl_factory(snap_enabled=True, snap_hotkey="F9", snap_hotkey_select="F10")
    win = ctrl.mainwin
    win._shutting_down = True
    before = (ctrl.settings.snap_hotkey, ctrl.settings.snap_hotkey_select)
    win._begin_hotkey_edit()                  # 不应去注销热键
    win._snap_key.setSpec("F6")
    win._on_snap_keys_changed()               # 不应保存/重新注册
    assert (ctrl.settings.snap_hotkey, ctrl.settings.snap_hotkey_select) == before
    win._shutting_down = False
