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


# ---------------------------------------------------------------- 设置对话框（第 26 轮）
def _main_page(win):
    """主界面那一页（滚动区的 inner widget）——用显式属性，别靠 findChild 的遍历顺序。"""
    return win._page_scroll.widget()


def test_settings_button_opens_dialog(qapp, tmp_home, monkeypatch):
    """右上角齿轮：点一下就打开设置对话框（这里把 exec 换成替身，避免模态阻塞测试）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    opened = []
    monkeypatch.setattr(win._settings_dialog, "exec", lambda: opened.append(True))

    assert win._btn_settings.text(), "齿轮按钮要有文案"
    assert win._btn_settings.toolTip(), "齿轮按钮要有说明"
    win._btn_settings.click()
    assert opened == [True], "点击齿轮应打开设置对话框"
    ctrl.shutdown()


def test_settings_dialog_is_modal_and_reused(qapp, tmp_home):
    """对话框是模态的，且**复用同一个对象**（控件在其中，重建会丢状态）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    dlg = win._settings_dialog
    assert dlg.isModal() is True
    assert win._settings_dialog is dlg
    ctrl.shutdown()


def test_settings_widgets_moved_into_dialog(qapp, tmp_home):
    """配好就不动的项必须搬进对话框：API/术语表/热键/OCR/结果显示/译文浮窗/界面语言。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    page, dlg = _main_page(win), win._settings_dialog
    moved = {
        "服务商": win._provider, "API 地址": win._api_base, "Key": win._keyline, "模型": win._model,
        "获取模型": win._btn_models, "术语表开关": win._gl_en, "术语表路径": win._gl_path,
        "启用热键": win._snap_enable, "截图热键": win._snap_key, "重框热键": win._snap_key2,
        "结果显示位置": win._snap_overlay, "鼠标旁浮窗": win._snap_popup, "最大行数": win._snap_max_lines,
        "写入主窗口": win._snap_write_main, "CPU 亲和": win._cpu_pin, "GPU 加速": win._ocr_gpu,
        "模型读图": win._ocr_vision, "常驻显示": win._ov_always, "浮窗字号": win._ov_font,
        "浮窗不透明度": win._ov_opacity, "鼠标穿透": win._ov_click_through,
        "回话输入条": win._ov_reply, "回话自动复制": win._ov_autocopy, "显示浮窗": win._btn_ov_show,
        "界面语言": win._lang, "日志": win._btn_logs,
    }
    for name, w in moved.items():
        assert dlg.isAncestorOf(w), f"{name} 应该在设置对话框里"
        assert not page.isAncestorOf(w), f"{name} 不该还留在主界面"
    ctrl.shutdown()


def test_core_workflow_widgets_stay_on_main_page(qapp, tmp_home):
    """核心翻译区留在主界面：翻译按钮、回话按钮、截图触发、结果框、状态栏、齿轮。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    page = _main_page(win)
    for name, w in {
        "状态栏": win._status, "齿轮": win._btn_settings,
        "立即截图翻译": win._btn_snap_now, "框选区域": win._btn_snap_region,
        "截图原文框": win._snap_src, "截图译文框": win._snap_dst,
    }.items():
        assert page.isAncestorOf(w), f"{name} 应留在主界面"
    ctrl.shutdown()


def test_main_page_is_leaner_after_settings_move(qapp, tmp_home):
    """把设置搬走后主页面要明显变矮（这是"避免杂乱"的可量化判据）。

    历史上的对照：全部设置留在主页面时 sizeHint 为 1607px（默认 980 宽）。
    这里只断言一个宽松上界，避免不同平台/字体下抖动。
    """
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win.resize(980, 880)
    qapp.processEvents()
    height = _main_page(win).sizeHint().height()
    assert height < 1500, f"主页面仍然太高（{height}px），设置项可能没搬走"
    ctrl.shutdown()
