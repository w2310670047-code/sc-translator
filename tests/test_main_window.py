"""主窗口尺寸回归：可自由缩放（整页滚动区）、初始尺寸收敛到屏幕内、尺寸跨重启记住。

背景（用户反馈）：125% 缩放下"窗口固定大小、页面显示不全"。
根因：布局 minimumSizeHint 高达 1430×1239（各卡片 + 文本框最小高度叠加），
      窗口被强制撑到比屏幕还高，而且完全缩不下去。
"""

from __future__ import annotations

import os

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


def test_page_is_scrollable_so_window_can_shrink(qapp, tmp_home):
    """整页必须在滚动区里，否则内容最小高度会把窗口"钉死"成大尺寸。"""
    from PySide6.QtWidgets import QScrollArea

    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    assert win.findChild(QScrollArea) is not None, "页面应放进 QScrollArea"
    # 布局最小高度必须远小于内容高度，否则用户缩不小
    assert win.minimumSizeHint().height() < 400, win.minimumSizeHint().height()
    ctrl.shutdown()


def test_window_can_be_resized_freely(qapp, tmp_home):
    """自由调整大小：resize 后窗口尺寸真的跟着变（改前会被最小高度弹回 1430×1239）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.show()
    for size in ((700, 500), (520, 420), (900, 640)):
        win.resize(*size)
        qapp.processEvents()
        assert (win.width(), win.height()) == size, (size, win.width(), win.height())
    ctrl.shutdown()


def test_startup_size_fits_available_screen(qapp, tmp_home):
    """初始尺寸收敛到屏幕可用区域内（离屏屏幕很小，正好覆盖 125% 缩放那种尴尬情况）。"""
    from PySide6.QtGui import QGuiApplication

    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.show()
    qapp.processEvents()
    avail = QGuiApplication.primaryScreen().availableGeometry()
    assert win.width() <= avail.width(), (win.width(), avail.width())
    assert win.height() <= avail.height(), (win.height(), avail.height())
    ctrl.shutdown()


def test_window_geometry_persists_across_restart(qapp, tmp_home):
    """尺寸/位置跨重启记住（自由调整大小要能保持）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.setGeometry(60, 40, 500, 400)
    qapp.processEvents()
    win._save_main_geometry()
    assert ctrl.settings.main_geometry["w"] == 500
    assert ctrl.settings.main_geometry["h"] == 400
    ctrl.shutdown()

    ctrl2 = _mk_ctrl(qapp, tmp_home)
    win2 = ctrl2.mainwin
    assert (win2.width(), win2.height()) == (500, 400), (win2.width(), win2.height())
    ctrl2.shutdown()


def test_restored_geometry_is_clamped_into_screen(qapp, tmp_home):
    """历史尺寸/位置超出当前屏幕时要收敛（换显示器后窗口不该跑到屏幕外）。"""
    from PySide6.QtGui import QGuiApplication

    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    avail = QGuiApplication.primaryScreen().availableGeometry()
    win._apply_startup_geometry(
        type("S", (), {
            "main_geometry": {"x": 99999, "y": 99999, "w": avail.width() + 3000, "h": avail.height() + 3000}
        })()
    )
    qapp.processEvents()
    assert win.width() <= avail.width(), (win.width(), avail.width())
    assert win.height() <= avail.height(), (win.height(), avail.height())
    assert win.x() < avail.x() + avail.width() + 1
    assert win.y() < avail.y() + avail.height() + 1
    ctrl.shutdown()
