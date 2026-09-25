"""OCR 设备模式（CPU ⇄ GPU/DirectML）回归。

- 引擎层：按可用 provider 决定用 DML / CUDA / 回落 CPU（provider 用替身注入，不依赖本机显卡）。
- 应用层：apply_ocr_mode() 在缺 GPU 运行时时**退回 CPU 并如实提示**，切换时丢弃旧引擎
  （GPU 会话的显存靠这一步归还）。
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SC_CI_SKIP_GUI", "") == "1", reason="环境跳过")


def _mk_ctrl(qapp, tmp_home, **kw):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    s = Settings().load()
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    ctrl = AppController(qapp, settings=s)
    ctrl.init_ui()
    return ctrl


# ---------------------------------------------------------------- 引擎层
def test_gpu_mode_sets_dml_flags(monkeypatch):
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_providers", lambda: ["DmlExecutionProvider"])
    eng = ocr_mod.OcrEngine(use_gpu=True)
    assert eng.gpu_active is True
    assert eng._kwargs["det_use_dml"] and eng._kwargs["cls_use_dml"] and eng._kwargs["rec_use_dml"]
    assert "det_use_cuda" not in eng._kwargs
    assert eng._engine is None, "取用时不建会话（懒加载）"


def test_gpu_mode_prefers_cuda_when_only_cuda(monkeypatch):
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_providers", lambda: ["CUDAExecutionProvider"])
    eng = ocr_mod.OcrEngine(use_gpu=True)
    assert eng.gpu_active is True
    assert eng._kwargs["det_use_cuda"] and "det_use_dml" not in eng._kwargs


def test_gpu_mode_without_provider_stays_cpu(monkeypatch):
    """请求 GPU 但没有 provider：不设任何 GPU 开关，标记为未生效（由上层如实告知用户）。"""
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_providers", lambda: [])
    eng = ocr_mod.OcrEngine(use_gpu=True)
    assert eng.gpu_active is False
    assert eng.use_gpu_requested is True
    assert not any("use_dml" in k or "use_cuda" in k for k in eng._kwargs)


def test_cpu_mode_has_no_gpu_flags(monkeypatch):
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_providers", lambda: ["DmlExecutionProvider"])
    eng = ocr_mod.OcrEngine()          # 默认 CPU
    assert eng.gpu_active is False
    assert not any("use_dml" in k or "use_cuda" in k for k in eng._kwargs)
    assert eng._kwargs["det_limit_side_len"] == ocr_mod.DET_LIMIT_SIDE_LEN


def test_engine_close_releases_session():
    """close() 必须丢掉引擎（GPU 会话占的显存靠它归还）。"""
    from sc_translator.ocr import OcrEngine

    eng = OcrEngine()
    eng._engine = object()
    eng._last_digest = b"x"
    eng._last_rows = [object()]
    eng.close()
    assert eng._engine is None
    assert eng._last_digest is None and eng._last_rows == []


def test_snapshot_service_builds_gpu_engine_when_setting_on(monkeypatch, tmp_home):
    import sc_translator.ocr as ocr_mod
    from sc_translator.snapshot import SnapshotService

    monkeypatch.setattr(ocr_mod, "gpu_providers", lambda: ["DmlExecutionProvider"])

    class _App:
        class settings:
            ocr_use_gpu = True

    svc = SnapshotService(_App())
    eng = svc.ocr
    assert eng.gpu_active is True and eng._kwargs.get("det_use_dml") is True
    svc.close()
    assert svc._ocr is None, "close() 应释放 OCR 引擎"


# ---------------------------------------------------------------- 应用层
def test_apply_ocr_mode_reverts_when_gpu_runtime_missing(tmp_home, monkeypatch):
    import sc_translator.ocr as ocr_mod
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    monkeypatch.setattr(ocr_mod, "gpu_provider_available", lambda: False)
    ctrl = object.__new__(AppController)          # 不建 UI/QApplication，只测逻辑
    ctrl.settings = Settings().load()
    ctrl.settings.ocr_use_gpu = True
    ctrl._snap = None
    ok, msg = ctrl.apply_ocr_mode()
    assert ok is False
    assert ctrl.settings.ocr_use_gpu is False, "缺运行时必须把设置退回 CPU"
    assert "onnxruntime-directml" in msg


def test_apply_ocr_mode_drops_cached_service(tmp_home, monkeypatch):
    import sc_translator.ocr as ocr_mod
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    monkeypatch.setattr(ocr_mod, "gpu_provider_available", lambda: True)
    ctrl = object.__new__(AppController)
    ctrl.settings = Settings().load()
    closed = []

    class _Snap:
        def close(self):
            closed.append(True)

    ctrl._snap = _Snap()
    ctrl.settings.ocr_use_gpu = True
    ok, msg = ctrl.apply_ocr_mode()
    assert ok is True and closed == [True] and ctrl._snap is None
    assert "GPU" in msg

    ctrl.settings.ocr_use_gpu = False
    ctrl._snap = _Snap()
    ok, msg = ctrl.apply_ocr_mode()
    assert ok is True and len(closed) == 2 and ctrl._snap is None
    assert "CPU" in msg


# ---------------------------------------------------------------- 界面
def test_ocr_gpu_checkbox_reflects_setting(qapp, tmp_home):
    ctrl = _mk_ctrl(qapp, tmp_home, ocr_use_gpu=False)
    assert ctrl.mainwin._ocr_gpu.isChecked() is False
    assert ctrl.mainwin._ocr_gpu.toolTip(), "应有说明用的 tooltip"
    ctrl.shutdown()


def test_ocr_gpu_checkbox_reverts_when_runtime_missing(qapp, tmp_home, monkeypatch):
    """没有 GPU 运行时时点开：勾选与设置都退回 CPU，并在状态栏说明怎么装。"""
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_provider_available", lambda: False)
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    win._ocr_gpu.setChecked(True)
    assert ctrl.settings.ocr_use_gpu is False
    assert win._ocr_gpu.isChecked() is False
    assert "onnxruntime-directml" in win._status.text()
    ctrl.shutdown()


def test_ocr_gpu_checkbox_enables_and_rebuilds(qapp, tmp_home, monkeypatch):
    import sc_translator.ocr as ocr_mod

    monkeypatch.setattr(ocr_mod, "gpu_provider_available", lambda: True)
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    closed = []

    class _Snap:
        def close(self):
            closed.append(True)

    ctrl._snap = _Snap()
    win._ocr_gpu.setChecked(True)
    assert ctrl.settings.ocr_use_gpu is True
    assert win._ocr_gpu.isChecked() is True
    assert closed == [True], "切模式必须丢弃旧引擎，否则 GPU 会话/显存不释放"
    assert ctrl._snap is None
    assert "GPU" in win._status.text()
    ctrl.shutdown()
