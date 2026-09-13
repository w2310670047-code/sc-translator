"""抓屏多后端回退回归。

背景（真实反馈）：游戏已是无边框（Borderless），但 mss 走 GDI BitBlt 仍然报
``Windows graphics function failed: BitBlt`` —— DXGI 翻转模型的游戏画面抓不动，
与"是否独占全屏"无关。现在按 DXGI(dxcam) → BitBlt(mss) → Qt 的顺序自动回退，
并把真实原因写进提示与日志。
"""

from __future__ import annotations

import numpy as np
import pytest

from sc_translator import screen as screen_mod


def _img(w=40, h=30, value=120):
    return np.full((h, w, 3), value, dtype=np.uint8)


@pytest.fixture()
def cap(monkeypatch):
    """构造一个不依赖真实桌面/真实后端的 ScreenCapture。"""
    monkeypatch.setattr(screen_mod, "mss", None)          # 跳过真实 mss 初始化
    c = screen_mod.ScreenCapture()
    monkeypatch.setattr(c, "_monitors", [{"left": 0, "top": 0, "width": 1920, "height": 1080}])
    return c


def _set_backends(c, monkeypatch, impls: dict):
    """把某个后端替换成给定实现（None = 让它不可用）。"""
    for name in ("dxcam", "mss", "qt"):
        fn = impls.get(name)
        monkeypatch.setattr(c, f"_grab_{name}", (None if fn is None else fn), raising=False)


RECT = {"left": 10, "top": 20, "width": 100, "height": 60}


# ------------------------------------------------------------------ 回退顺序
def test_first_backend_wins(cap, monkeypatch):
    calls = []
    _set_backends(cap, monkeypatch, {
        "dxcam": lambda r: (calls.append("dxcam"), _img())[1],
        "mss": lambda r: (calls.append("mss"), _img())[1],
    })
    img, backend, err = cap.grab_ex(RECT)
    assert img is not None and backend == "dxcam" and err == ""
    assert calls == ["dxcam"], "第一后端成功就不该再试其它后端"


def test_falls_back_when_bitblt_fails(cap, monkeypatch):
    """还原用户现场：dxcam 缺失、mss 报 BitBlt 失败、Qt 兜底成功。"""
    def boom(_r):
        raise RuntimeError("Windows graphics function failed (no error provided): BitBlt")

    _set_backends(cap, monkeypatch, {
        "dxcam": None,
        "mss": boom,
        "qt": lambda r: _img(value=200),
    })
    img, backend, err = cap.grab_ex(RECT)
    assert img is not None, "mss 失败后必须能回退成功"
    assert backend == "qt" and err == ""


def test_all_backends_fail_reports_each_reason(cap, monkeypatch):
    _set_backends(cap, monkeypatch, {
        "dxcam": lambda r: None,
        "mss": lambda r: (_ for _ in ()).throw(RuntimeError("BitBlt")),
        "qt": None,
    })
    img, backend, err = cap.grab_ex(RECT)
    assert img is None and backend == ""
    assert "mss" in err and "BitBlt" in err, err
    assert "dxcam" in err, err            # 每个后端的原因都要能看见


def test_blank_frame_falls_through(cap, monkeypatch):
    """某个后端只给全黑（HDR/受保护内容常见）时，应继续换后端而不是把黑图当结果。"""
    black = np.zeros((30, 40, 3), dtype=np.uint8)
    _set_backends(cap, monkeypatch, {
        "dxcam": lambda r: black,
        "mss": lambda r: _img(value=99),
    })
    img, backend, err = cap.grab_ex(RECT)
    assert backend == "mss"
    assert img is not None and int(img.mean()) == 99


def test_all_blank_reports_blank_reason(cap, monkeypatch):
    black = np.zeros((30, 40, 3), dtype=np.uint8)
    _set_backends(cap, monkeypatch, {
        "dxcam": lambda r: black,
        "mss": lambda r: black,
        "qt": lambda r: black,
    })
    img, backend, err = cap.grab_ex(RECT)
    assert img is None
    assert "全黑" in err, err


def test_sticky_backend_preference(cap, monkeypatch):
    """上次成功的后端要优先（避免每次都先踩一次失败）。"""
    order = []

    def dx(r):
        order.append("dxcam")
        raise RuntimeError("nope")

    def ms(r):
        order.append("mss")
        return _img()

    _set_backends(cap, monkeypatch, {"dxcam": dx, "mss": ms})
    cap.grab_ex(RECT)
    # 每个后端有两次机会（首次偶发失败很常见），所以 dxcam 会被试两次再换 mss
    assert order == ["dxcam", "dxcam", "mss"], order
    order.clear()
    cap.grab_ex(RECT)                     # 第二次：mss 已记住，应该排第一
    assert order[0] == "mss", order


# ------------------------------------------------------------------ 裁剪与判定
def test_rect_is_clamped_into_virtual_desktop(cap, monkeypatch):
    seen = {}

    def ms(rect):
        seen.update(rect)
        return _img()

    _set_backends(cap, monkeypatch, {"dxcam": None, "mss": ms})
    cap.grab_ex({"left": -50, "top": -80, "width": 5000, "height": 4000})
    assert seen == {"left": 0, "top": 0, "width": 1920, "height": 1080}, seen


def test_looks_blank_detection(cap):
    assert cap._looks_blank(np.zeros((10, 10, 3), dtype=np.uint8)) is True
    assert cap._looks_blank(_img(value=120)) is False
    assert cap._looks_blank(_img(value=1)) is True          # 近黑也算
    assert cap._looks_blank(np.zeros((0, 0, 3), dtype=np.uint8)) is True


def test_empty_rect_is_reported(cap):
    img, backend, err = cap.grab_ex({})
    assert img is None and "区域" in err


def test_dxcam_available_returns_bool():
    assert isinstance(screen_mod.dxcam_available(), bool)
