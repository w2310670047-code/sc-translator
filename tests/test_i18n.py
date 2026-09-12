"""界面多语言回归：三语成套、切换生效、语言选择落盘、关键界面元素被翻译。"""

from __future__ import annotations

import pytest

from sc_translator import i18n

CJK = "\u4e00-\u9fff"


@pytest.fixture(autouse=True)
def _reset_lang():
    yield
    i18n.set_language("zh_CN")


# ------------------------------------------------------------------ 文案表
def test_every_key_has_three_locales():
    """一条 key 必须三语齐全（结构上保证不漏翻）。"""
    for key in i18n.keys():
        row = i18n._T[key]
        assert len(row) == len(i18n.LANGS), f"{key} 元组长度不等于语言数"
        for lang, text in zip(i18n.LANGS, row):
            assert isinstance(text, str), f"{key}/{lang} 不是字符串"
    assert len(i18n.keys()) > 60, "文案表看起来不完整"


def test_no_nonempty_gap_between_locales():
    """除明确留空的项外，简体有文案时繁中/英文也不能为空。"""
    for key in i18n.keys():
        zh, tw, en = i18n._T[key]
        if zh:
            assert tw, f"{key} 缺繁体"
            assert en, f"{key} 缺英文"


def test_english_locale_is_english():
    """core 界面英文文案不应还是中文（占位符与专名例外）。"""
    i18n.set_language("en")
    for key in ("status.ready", "btn.translate_zh", "btn.copy_result", "pane.in.title", "gc.title"):
        text = i18n.t(key)
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in text), f"{key} 英文版仍是中文：{text}"


def test_traditional_locale_differs_from_simplified():
    """繁中至少要在典型字上不同于简中（避免复制粘贴忘改）。"""
    some_tw = [i18n._T[k][1] for k in ("status.ready", "btn.copy_result", "pane.out.title")]
    some_zh = [i18n._T[k][0] for k in ("status.ready", "btn.copy_result", "pane.out.title")]
    assert any(a != b for a, b in zip(some_zh, some_tw)), "繁中与简中完全一致，可能没翻译"


# ------------------------------------------------------------------ 取值
def test_set_language_and_fallback():
    assert i18n.set_language("zh_TW") == "zh_TW"
    assert i18n.current() == "zh_TW"
    assert i18n.t("status.ready") == "就緒"
    assert i18n.set_language("en") == "en"
    assert i18n.t("status.ready") == "Ready"
    # 未知语言回退简中
    assert i18n.set_language("fr") == "zh_CN"
    assert i18n.set_language("") == "zh_CN"


def test_t_formats_placeholders_and_survives_bad_key():
    i18n.set_language("en")
    assert i18n.t("gc.state_ready", size=7020) == "Code table ready: 7020 chars"
    assert i18n.t("status.fail", msg="boom") == "Failed: boom"
    assert i18n.t("no.such.key") == "no.such.key"      # 缺失 key 原样返回，不抛异常
    assert i18n.t("status.ready", unused=1) == "Ready"  # 多余占位符不炸


def test_languages_list_is_localized():
    i18n.set_language("en")
    codes = [c for c, _ in i18n.languages()]
    assert codes == list(i18n.LANGS)
    assert dict(i18n.languages())["en"] == "English"
    i18n.set_language("zh_CN")
    assert dict(i18n.languages())["zh_TW"] == "繁體中文"


# ------------------------------------------------------------------ 界面
def test_window_uses_saved_language(qapp, tmp_home):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    s = Settings().load()
    s.ui_language = "en"
    s.save()
    ctrl = AppController(qapp, settings=s)
    ctrl.init_ui()
    win = ctrl.mainwin
    assert "Star Citizen Translator" in win.windowTitle(), win.windowTitle()
    assert win._btn_tr.text() == "Translate to Chinese", win._btn_tr.text()
    assert win._btn_reply.text() == "Translate & copy"
    assert win._lang.currentData() == "en"
    assert win._status.text() == "Ready"
    ctrl.shutdown()
    i18n.set_language("zh_CN")


def test_switching_language_rebuilds_window_and_persists(qapp, tmp_home):
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    ctrl = AppController(qapp, settings=Settings().load())
    ctrl.init_ui()
    old = ctrl.mainwin
    assert old._btn_tr.text() == "翻译到中文"

    # 切到繁中
    idx = old._lang.findData("zh_TW")
    old._lang.setCurrentIndex(idx)
    win = ctrl.mainwin
    assert win is not old, "切换语言应重建窗口"
    assert win._btn_tr.text() == "翻譯成中文", win._btn_tr.text()
    assert "翻譯器" in win.windowTitle(), win.windowTitle()
    assert Settings().load().ui_language == "zh_TW", "语言选择必须落盘"
    assert i18n.current() == "zh_TW"

    # 再切到英文
    idx = win._lang.findData("en")
    win._lang.setCurrentIndex(idx)
    win2 = ctrl.mainwin
    assert win2._btn_copy.text() == "Copy result", win2._btn_copy.text()
    assert Settings().load().ui_language == "en"
    ctrl.shutdown()
    i18n.set_language("zh_CN")


def test_language_switch_refused_while_busy(qapp, tmp_home):
    """翻译进行中切换语言要拒绝并提示，避免回调打到已销毁的控件。"""
    from sc_translator.app import AppController
    from sc_translator.settings import Settings

    ctrl = AppController(qapp, settings=Settings().load())
    ctrl.init_ui()
    win = ctrl.mainwin
    win._busy = True
    win._lang.setCurrentIndex(win._lang.findData("en"))
    assert ctrl.mainwin is win, "忙时不应重建窗口"
    assert "稍后" in win._status.text(), win._status.text()
    assert i18n.current() == "zh_CN"
    win._busy = False
    ctrl.shutdown()


def test_provider_choices_keep_stable_keys(qapp, tmp_home):
    """服务商 value 必须是稳定 key（存设置用），显示名才本地化。"""
    from sc_translator.ui.main_window import provider_choices

    i18n.set_language("zh_CN")
    keys_zh = [k for k, _ in provider_choices()]
    labels_zh = [v for _, v in provider_choices()]
    i18n.set_language("en")
    keys_en = [k for k, _ in provider_choices()]
    labels_en = [v for _, v in provider_choices()]
    assert keys_zh == keys_en == ["DeepSeek", "OpenAI", "custom"]
    assert labels_zh[2] != labels_en[2], "自定义服务商显示名应随语言变化"
    assert labels_en[2] == "Custom OpenAI-compatible"
    i18n.set_language("zh_CN")


def test_legacy_provider_name_migrates(tmp_home, qapp):
    """旧设置里存的是显示名，读取时应升级成稳定 key。"""
    import json

    from sc_translator.paths import settings_file
    from sc_translator.settings import Settings

    settings_file().write_text(
        json.dumps({"api_provider": "自定义 OpenAI 兼容"}, ensure_ascii=False), encoding="utf-8"
    )
    assert Settings().load().api_provider == "custom"
