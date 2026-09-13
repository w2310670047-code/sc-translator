"""框选区域（F10）回归：坐标必须是全局逻辑坐标、取消/完成都必须把主窗口还回来。

背景：真实使用中"框选"有问题——取消框选（Esc/右键）后主窗口被 hide() 掉却没被还原，
程序看起来"消失"了；另外选中矩形的坐标是**控件局部坐标**，多显示器（虚拟桌面原点不为 0）
时会存成错误区域。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from sc_translator.ui.region_select import RegionSelect


@pytest.fixture()
def picker(qapp):
    win = RegionSelect()
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    win.show()
    qapp.processEvents()
    yield win
    try:
        win.close()
    except RuntimeError:
        pass
    qapp.processEvents()


def _drag(win, qapp, p0: QPoint, p1: QPoint) -> QRect | None:
    got: list[QRect] = []
    win.selection.connect(got.append)
    QTest.mousePress(win, Qt.MouseButton.LeftButton, pos=p0)
    QTest.mouseMove(win, p1)
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, pos=p1)
    qapp.processEvents()
    return got[0] if got else None


def test_selection_is_reported_in_global_coordinates(picker, qapp, monkeypatch):
    """矩形必须是全局逻辑坐标（虚拟桌面原点非 0 时同样成立）。"""
    # 把控件挪到非原点位置，模拟"虚拟桌面原点不是 (0,0)"或副屏
    origin = QPoint(300, 200)
    picker.setGeometry(QRect(origin, picker.size()))
    qapp.processEvents()

    rect = _drag(picker, qapp, QPoint(50, 40), QPoint(250, 140))
    assert rect is not None, "拖拽后应发出 selection 信号"
    # 局部 (50,40)-(250,140) + 控件原点 (300,200) = 全局 (350,240)-(550,340)
    assert rect.left() == origin.x() + 50, f"left 应为全局坐标，实际 {rect.left()}"
    assert rect.top() == origin.y() + 40, f"top 应为全局坐标，实际 {rect.top()}"
    assert rect.width() == 200 and rect.height() == 100


def test_tiny_drag_is_ignored(picker, qapp):
    """误触（小于最小尺寸）不算框选成功。"""
    got: list[QRect] = []
    picker.selection.connect(got.append)
    QTest.mousePress(picker, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseRelease(picker, Qt.MouseButton.LeftButton, pos=QPoint(15, 15))
    qapp.processEvents()
    assert got == []


def test_escape_emits_cancelled(picker, qapp):
    got: list[bool] = []
    picker.cancelled.connect(lambda: got.append(True))
    QTest.keyClick(picker, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert got == [True], "Esc 应发出 cancelled"


def test_right_click_emits_cancelled(picker, qapp):
    got: list[bool] = []
    picker.cancelled.connect(lambda: got.append(True))
    QTest.mouseClick(picker, Qt.MouseButton.RightButton, pos=QPoint(30, 30))
    qapp.processEvents()
    assert got == [True], "右键应发出 cancelled"


# ------------------------------------------------------------------ 主窗口还原
def _ctrl(qapp, tmp_home):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    ctrl = AppController(qapp, settings=Settings().load())
    ctrl.init_ui()
    ctrl.mainwin.show()
    qapp.processEvents()
    return ctrl


def _live_picker(qapp) -> RegionSelect | None:
    """找到当前活着的框选窗口（它没有 parent，是顶层窗口）。"""
    for w in qapp.topLevelWidgets():
        if isinstance(w, RegionSelect):
            return w
    return None


def test_cancel_restores_main_window(qapp, tmp_home):
    ctrl = _ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.on_snap_select_hotkey()
    qapp.processEvents()
    assert not win.isVisible(), "框选期间主窗口应让位"
    picker = _live_picker(qapp)
    assert picker is not None, "应该出现框选窗口"
    picker.cancelled.emit()          # 等价于用户按 Esc / 右键取消
    picker.close()
    qapp.processEvents()
    assert win.isVisible(), "取消框选后主窗口必须回来（否则程序看起来消失了）"
    ctrl.shutdown()


def test_select_restores_main_window_and_saves_region(qapp, tmp_home):
    ctrl = _ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.on_snap_select_hotkey()
    qapp.processEvents()
    picker = _live_picker(qapp)
    assert picker is not None
    rect = QRect(120, 90, 400, 200)
    picker.selection.emit(rect)
    picker.close()
    qapp.processEvents()
    assert win.isVisible(), "框选完成后主窗口必须回来"
    saved = ctrl.settings.snap_region or {}
    assert saved.get("logical", {}).get("w") == 400, saved
    assert saved.get("physical", {}).get("width", 0) > 0, saved
    ctrl.shutdown()


def test_closing_picker_any_way_restores_main_window(qapp, tmp_home):
    """即使没有 cancelled/selection（例如窗口被系统关掉），也不能把主窗口弄丢。"""
    ctrl = _ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.on_snap_select_hotkey()
    qapp.processEvents()
    picker = _live_picker(qapp)
    assert picker is not None
    picker.close()
    qapp.processEvents()
    assert win.isVisible(), "框选窗口关闭后主窗口必须回来"
    ctrl.shutdown()
