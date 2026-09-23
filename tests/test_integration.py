"""集成冒烟：真实 RapidOCR + 合成游戏截图 + GUI 组装（offscreen）。

不发起真实翻译请求；RapidOCR 首次运行加载模型可能需要数秒。
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from sc_translator.ocr import OcrEngine, normalize_text

# 允许在无交互桌面的环境跳过
pytestmark = pytest.mark.skipif(os.environ.get("SC_CI_SKIP_GUI", "") == "1", reason="环境跳过")

_IMG_TEXT = [
    "Quantum travel to Crusader",
    "Bounty mission updated",
    "Arrive at OM-1 marker",
]


def _synthetic_screenshot() -> np.ndarray:
    from PIL import Image, ImageDraw, ImageFont

    w, h = 760, 200
    img = Image.new("RGB", (w, h), (16, 19, 26))
    d = ImageDraw.Draw(img)
    font = None
    for cand in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\calibri.ttf"):
        if os.path.exists(cand):
            try:
                font = ImageFont.truetype(cand, 26)
                break
            except Exception:
                continue
    y = 14
    for line in _IMG_TEXT:
        d.text((16, y), line, fill=(224, 230, 238), font=font or ImageFont.load_default())
        y += 44
    # 返回 BGR ndarray（模拟 mss 输出）
    return np.asarray(img)[:, :, ::-1].copy()


def test_rapidocr_reads_synthetic_game_text(tmp_home):
    engine = OcrEngine()
    bgr = _synthetic_screenshot()
    lines = engine.recognize(bgr)
    assert len(lines) >= 2, f"OCR 行数过少: {lines}"
    joined = " ".join(l.normalized() for l in lines).lower()
    # 宽松断言：至少能读出主要单词中的一部分
    hits = sum(1 for word in ("quantum", "travel", "crusader", "bounty", "mission", "arrive", "marker") if word in joined)
    assert hits >= 2, f"OCR 识别内容与期望偏差较大: {joined}"


def _qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


# qapp fixture 由 tests/conftest.py 统一提供（会话级）


def test_region_select_construct(qapp):
    """回归：Qt6 下 RegionSelect 不再引用已删除的枚举，可正常创建/显示。"""
    from sc_translator.ui.region_select import RegionSelect

    win = RegionSelect()
    try:
        win.show()
        assert win.geometry().width() > 0 and win.geometry().height() > 0
    finally:
        win.close()


def _pump(qapp, n=6):
    for _ in range(n):
        qapp.processEvents()
        import time

        time.sleep(0.01)


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


class _FakeClient:
    """替身：不联网，记录调用参数，返回可预测的译文。"""

    def __init__(self, out=None, fail=None):
        from sc_translator.translate.client import ClientOptions

        self.opts = ClientOptions(model="fake")
        self._out = out
        self._fail = fail
        self.calls = []

    def translate_lines_batch(self, lines, source_lang="auto", target_lang="en", keep_chat_prefix=False):
        self.calls.append(("batch", list(lines), source_lang, target_lang))
        if self._fail:
            raise self._fail
        return self._out or [f"[zh]{x}" for x in lines]

    def translate_reply(self, text, target_lang, spicy=False):
        self.calls.append(("reply", text, target_lang, spicy))
        if self._fail:
            raise self._fail
        return self._out if self._out is not None else f"[{target_lang}]{text}"


def test_text_translator_ui_assembly(qapp, tmp_home):
    """纯文本翻译器：双语输入区/结果区齐备，且屏幕实时翻译控件仍未接回。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    assert win is not None
    assert ctrl.overlay is not None, "译文悬浮框应随主窗口一起装配（0.4.0 下线后已重新接线）"
    assert not ctrl.overlay.isVisible(), "浮窗默认不显示"
    assert hasattr(win, "_in_en") and hasattr(win, "_out_zh")
    assert hasattr(win, "_result_en") and hasattr(win, "_spicy")
    assert win._reply_target.count() >= 3, "目标语言应含英语/日语/韩语"
    # 屏幕翻译遗留控件不再出现在主窗口
    from PySide6.QtWidgets import QPushButton

    texts = [b.text() for b in win.findChildren(QPushButton)]
    assert not any("开始" in t or "停止" in t for t in texts), texts
    ctrl.shutdown()


def test_translate_to_chinese_click_writes_result(qapp, tmp_home):
    """点按路径：输入外文 → 点按钮 → 结果区显示中文（替身客户端，不联网）。"""
    ctrl = _mk_ctrl(qapp, tmp_home)
    fake = _FakeClient()
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._in_en.setPlainText("Quantum travel\nBounty")
    win._btn_tr.click()
    _wait_flag(qapp, lambda: win._busy)
    assert fake.calls and fake.calls[0][0] == "batch", fake.calls
    assert fake.calls[0][3] == "zh-CN"
    assert win._result_en.toPlainText() == "[zh]Quantum travel\n[zh]Bounty"
    ctrl.shutdown()


def test_reply_click_copies_and_uses_spicy(qapp, tmp_home):
    """回话路径：中文 → 目标语言，结果写入结果区并自动复制；嘴臭开关透传到请求。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(qapp, tmp_home, spicy_mode=True)
    fake = _FakeClient()
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._out_zh.setPlainText("你好")
    win._btn_reply.click()
    _wait_flag(qapp, lambda: win._busy)
    assert fake.calls and fake.calls[0][0] == "reply", fake.calls
    assert fake.calls[0][1] == "你好"
    assert fake.calls[0][2] == win._reply_target.currentText()
    assert fake.calls[0][3] is True, "开启嘴臭模式时应以 spicy=True 调用"
    assert win._result_en.toPlainText() == "[English]你好"
    assert QApplication.clipboard().text() == "[English]你好", "回话结果应自动进剪贴板"
    ctrl.shutdown()


def test_gamecode_card_encode_decode(qapp, tmp_home):
    """游戏聊天码卡片：输入中文即时编码、点按复制、粘码可解码。"""
    from PySide6.QtWidgets import QApplication

    from sc_translator import gamecode

    ini = tmp_home / "global.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(
        "_starcitizen_doctor_localization_community_input_method_version=1.2.3\n"
        "IH=你\nE8=好\nAP=吗\n100=测\n"
        "_starcitizen_doctor_localization_version=4.2.0\n",
        encoding="utf-8",
    )
    ctrl = _mk_ctrl(qapp, tmp_home, gamecode_ini_path=str(ini))
    win = ctrl.mainwin
    assert gamecode.configured(), "启动时应自动载入码表"
    assert "码表就绪" in win._gc_state.text(), win._gc_state.text()
    assert "1.2.3" in win._gc_state.text(), win._gc_state.text()

    # 输入即时编码
    win._gc_in.setPlainText("你好吗")
    _pump(qapp)
    assert win._gc_out.toPlainText() == "[zh] @IH@E8@AP"

    # 点按编码并复制
    QApplication.clipboard().setText("")
    win._gc_autocopy.setChecked(False)   # 关掉防抖，避免干扰本次断言
    win._btn_gc_encode.click()
    _pump(qapp)
    assert QApplication.clipboard().text() == "[zh] @IH@E8@AP"

    # 反向：粘别人的码 -> 解码成中文（@100=测）
    win._gc_out.setPlainText("[zh] @100@IH@E8")
    win._btn_gc_decode.click()
    _pump(qapp)
    assert win._gc_in.toPlainText() == "测你好"
    assert "已解码" in win._status.text(), win._status.text()
    ctrl.shutdown()


def test_gamecode_without_table_shows_hint(qapp, tmp_home, monkeypatch):
    """没装汉化时：状态栏给出明确指引，点按钮不崩、只提示。"""
    from sc_translator import gamecode
    from PySide6.QtWidgets import QMessageBox

    # 屏蔽自动检测，模拟"本机没有码表"
    monkeypatch.setattr(gamecode, "autodetect", lambda roots=None: None, raising=False)
    monkeypatch.setenv("SC_GAMECODE_INI", "")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    ctrl = _mk_ctrl(qapp, tmp_home, gamecode_ini_path="")
    win = ctrl.mainwin
    assert not gamecode.configured()
    assert "未找到码表" in win._gc_state.text(), win._gc_state.text()
    win._gc_in.setPlainText("你好吗")
    win._btn_gc_encode.click()
    _pump(qapp)
    assert win._gc_out.toPlainText() == "", "没有码表时不应产生输出"
    ctrl.shutdown()


def test_spicy_checkbox_persists_to_settings(qapp, tmp_home):
    """嘴臭模式：主窗口复选框与设置项双向一致并落盘。"""
    from sc_translator.settings import Settings

    ctrl = _mk_ctrl(qapp, tmp_home, spicy_mode=False)
    win = ctrl.mainwin
    assert win._spicy.isChecked() is False
    win._spicy.setChecked(True)
    _pump(qapp)
    assert ctrl.settings.spicy_mode is True
    assert Settings().load().spicy_mode is True, "开关必须落盘，重启后仍生效"
    win._spicy.setChecked(False)
    _pump(qapp)
    assert Settings().load().spicy_mode is False
    ctrl.shutdown()


def _dual_ini(tmp_home):
    ini = tmp_home / "global.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text(
        "_starcitizen_doctor_localization_community_input_method_version=1.2.3\n"
        "IH=你\nE8=好\nAP=吗\n100=测\n"
        "_starcitizen_doctor_localization_version=4.2.0\n",
        encoding="utf-8",
    )
    return ini


def test_reply_output_code_plus_foreign(qapp, tmp_home):
    """回话输出勾选「中文码 + 译文」：第一行中文码，第二行英文。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path=str(_dual_ini(tmp_home)),
        reply_out_code=True, reply_out_foreign=True,
    )
    fake = _FakeClient(out="How are you")
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    assert win._reply_out_code.isChecked() and win._reply_out_foreign.isChecked()
    win._keyline.setText("sk-test")
    win._out_zh.setPlainText("你好吗")
    win._btn_reply.click()
    _wait_flag(qapp, lambda: win._busy)
    assert win._result_en.toPlainText() == "[zh] @IH@E8@AP\n[en] How are you"
    assert QApplication.clipboard().text() == "[zh] @IH@E8@AP\n[en] How are you"
    ctrl.shutdown()


def test_reply_output_foreign_only(qapp, tmp_home):
    """回话输出只勾「译文」：只出英文，且不调用码表。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path=str(_dual_ini(tmp_home)),
        reply_out_code=False, reply_out_foreign=True,
    )
    fake = _FakeClient(out="How are you")
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._out_zh.setPlainText("你好吗")
    win._btn_reply.click()
    _wait_flag(qapp, lambda: win._busy)
    assert win._result_en.toPlainText() == "How are you"
    assert QApplication.clipboard().text() == "How are you"
    ctrl.shutdown()


def test_reply_output_code_only_needs_no_api(qapp, tmp_home):
    """回话输出只勾「中文码」（中译中）：纯本地编码，不填 Key 也能用、不联网。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path=str(_dual_ini(tmp_home)),
        reply_out_code=True, reply_out_foreign=False,
    )
    fake = _FakeClient(out="SHOULD-NOT-BE-USED")
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("")          # 故意不填 Key
    win._out_zh.setPlainText("你好吗")
    win._btn_reply.click()
    _pump(qapp)
    assert win._result_en.toPlainText() == "[zh] @IH@E8@AP"
    assert QApplication.clipboard().text() == "[zh] @IH@E8@AP"
    assert fake.calls == [], "只发中文码时不应调用翻译接口"
    assert "Ctrl+V" in win._status.text(), win._status.text()
    ctrl.shutdown()


def test_reply_target_persists_across_restart(qapp, tmp_home):
    """回话目标语言要落盘并在窗口重建后恢复（此前界面既不恢复也不写回，F7）。"""
    from sc_translator.settings import Settings

    ctrl = _mk_ctrl(qapp, tmp_home, reply_target="Korean")
    win = ctrl.mainwin
    assert win._reply_target.currentText() == "Korean", "应恢复上次选择的目标语言"

    win._reply_target.setCurrentText("Japanese")
    assert ctrl.settings.reply_target == "Japanese", "切换后应立即落盘"
    assert Settings().load().reply_target == "Japanese", "并写入 settings.json"
    ctrl.shutdown()

    ctrl2 = _mk_ctrl(qapp, tmp_home)
    assert ctrl2.mainwin._reply_target.currentText() == "Japanese", "重建窗口后仍应保持"
    ctrl2.shutdown()


def test_reply_output_code_only_without_table_warns(qapp, tmp_home, monkeypatch):
    """只勾中文码但本机没码表：提示去装汉化/指定文件，不输出垃圾。"""
    from sc_translator import gamecode
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(gamecode, "autodetect", lambda roots=None: None, raising=False)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path="", reply_out_code=True, reply_out_foreign=False,
    )
    win = ctrl.mainwin
    win._out_zh.setPlainText("你好吗")
    win._btn_reply.click()
    _pump(qapp)
    assert win._result_en.toPlainText() == ""
    ctrl.shutdown()


def test_reply_output_falls_back_without_table(qapp, tmp_home, monkeypatch):
    """勾了中文码+译文但没码表：退回只输出译文，并给出提示。"""
    from sc_translator import gamecode

    monkeypatch.setattr(gamecode, "autodetect", lambda roots=None: None, raising=False)
    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path="", reply_out_code=True, reply_out_foreign=True,
    )
    fake = _FakeClient(out="How are you")
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._out_zh.setPlainText("你好吗")
    win._btn_reply.click()
    _wait_flag(qapp, lambda: win._busy)
    assert win._result_en.toPlainText() == "How are you"
    assert "只输出译文" in win._status.text(), win._status.text()
    ctrl.shutdown()


def test_reply_output_checkboxes_persist_and_mark_japanese(qapp, tmp_home):
    """勾选落盘；目标语言日语时标记为 [ja]；两个都取消会保留一项。"""
    from sc_translator.settings import Settings

    ctrl = _mk_ctrl(
        qapp, tmp_home,
        gamecode_ini_path=str(_dual_ini(tmp_home)),
        reply_out_code=False, reply_out_foreign=True,
    )
    win = ctrl.mainwin
    win._reply_out_code.setChecked(True)
    _pump(qapp)
    saved = Settings().load()
    assert saved.reply_out_code is True and saved.reply_out_foreign is True
    win._reply_target.setCurrentText("Japanese")
    text, note = win._compose_reply("你好", "Japanese", "こんにちは")
    assert text == "[zh] @IH@E8\n[ja] こんにちは", text
    assert note == ""
    # 想两个都取消 -> 自动保留一项，并提示
    win._reply_out_foreign.setChecked(False)
    win._reply_out_code.setChecked(False)
    _pump(qapp)
    assert win._reply_out_code.isChecked() or win._reply_out_foreign.isChecked()
    assert "至少保留一项" in win._status.text(), win._status.text()
    ctrl.shutdown()


def test_gamecode_card_three_combinations(qapp, tmp_home):
    """卡片三种组合：只中文码（离线）/ 只英文 / 中文码+英文（双行）。"""
    from PySide6.QtWidgets import QApplication

    ctrl = _mk_ctrl(qapp, tmp_home, gamecode_ini_path=str(_dual_ini(tmp_home)))
    fake = _FakeClient(out="How are you")
    ctrl.make_client = lambda use_cache=True: fake
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._gc_autocopy.setChecked(False)
    win._gc_in.setPlainText("你好吗")

    # 1) 默认：只中文码，纯本地
    assert win._gc_out_code.isChecked() and not win._gc_out_en.isChecked()
    assert win._btn_gc_encode.text() == "编码并复制"
    QApplication.clipboard().setText("")
    win._btn_gc_encode.click()
    _pump(qapp)
    assert win._gc_out.toPlainText() == "[zh] @IH@E8@AP"
    assert fake.calls == [], "只中文码不应调用 API"

    # 2) 只英文（先勾英文，再取消中文码——避免中间态两个都空）
    win._gc_out_en.setChecked(True)
    win._gc_out_code.setChecked(False)
    _pump(qapp)
    assert win._btn_gc_encode.text() == "翻译为英文并复制"
    win._gc_in.setPlainText("你好吗")     # 触发一次 textChanged，只英文不应改动右侧预览
    _pump(qapp)
    win._btn_gc_encode.click()
    _wait_flag(qapp, lambda: win._gc_busy)
    assert win._gc_out.toPlainText() == "How are you"
    assert QApplication.clipboard().text() == "How are you"

    # 3) 中文码 + 英文
    win._gc_out_code.setChecked(True)
    _pump(qapp)
    assert win._btn_gc_encode.text() == "生成双行并复制"
    win._btn_gc_encode.click()
    _wait_flag(qapp, lambda: win._gc_busy)
    assert win._gc_out.toPlainText() == "[zh] @IH@E8@AP\n[en] How are you"
    assert QApplication.clipboard().text() == "[zh] @IH@E8@AP\n[en] How are you"
    ctrl.shutdown()


def test_gamecode_card_code_only_without_api_key(qapp, tmp_home):
    """卡片只勾中文码时，没有 API Key 也能正常出码。"""
    ctrl = _mk_ctrl(qapp, tmp_home, gamecode_ini_path=str(_dual_ini(tmp_home)))
    win = ctrl.mainwin
    win._keyline.setText("")
    win._gc_autocopy.setChecked(False)
    win._gc_in.setPlainText("你好")
    win._btn_gc_encode.click()
    _pump(qapp)
    assert win._gc_out.toPlainText() == "[zh] @IH@E8"
    ctrl.shutdown()


def test_translate_failure_shows_status(qapp, tmp_home, monkeypatch):
    """失败路径：API 报错时状态栏提示失败，且不把错误写进译文区。"""
    from sc_translator.translate.client import ApiError
    from PySide6.QtWidgets import QMessageBox

    ctrl = _mk_ctrl(qapp, tmp_home)
    fake = _FakeClient(fail=ApiError("模型返回了空内容（已禁用思维链）"))
    ctrl.make_client = lambda use_cache=True: fake
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    win = ctrl.mainwin
    win._keyline.setText("sk-test")
    win._in_en.setPlainText("Quantum travel")
    win._btn_tr.click()
    _wait_flag(qapp, lambda: win._busy)
    assert "失败" in win._status.text(), win._status.text()
    assert "空内容" in win._status.text(), win._status.text()
    assert win._result_en.toPlainText() == ""
    ctrl.shutdown()


def test_screen_capture_probe():
    """真实环境抓屏冒烟：能抓到非空帧即可（无游戏时抓桌面）。"""
    try:
        from sc_translator.screen import ScreenCapture
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"mss 不可用: {exc}")
    cap = ScreenCapture()
    try:
        shot = cap.grab({"left": 0, "top": 0, "width": 320, "height": 180})
        assert shot is not None and shot.size > 0 and shot.shape[2] == 3
    finally:
        cap.close()

def _wait_flag(qapp, getter, seconds=10.0, step=0.01):
    """等待后台任务结束（win._busy / win._gc_busy 变 False）。

    原实现固定 80 轮 ×10ms ≈ 0.8s，机器忙时（前面测试刚加载过 OCR 模型）
    会偶发超时导致假失败，这里改成按秒计的上限并保留事件循环驱动。
    """
    import time as _t

    deadline = _t.time() + seconds
    while _t.time() < deadline:
        qapp.processEvents()
        if not getter():
            return True
        _t.sleep(step)
    return not getter()