"""翻译客户端 + 缓存 + DPAPI 密钥测试（全部走注入的假传输，不发真实请求）。"""

from __future__ import annotations

import json
import threading
import time

from sc_translator.secrets import protect, unprotect
from sc_translator.translate.cache import TranslationCache
from sc_translator.translate.client import ApiError, ClientOptions, OpenAiCompatClient


class FakeResponse:
    def __init__(self, status: int, payload: dict | str):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload

    @property
    def text(self):
        return str(self._payload)


class FakeServer:
    """实现 OpenAI 兼容的最小假服务，记录收到的 /chat/completions 请求。"""

    def __init__(self, models=None, prefix=""):
        self.models = models or ["deepseek-chat", "deepseek-reasoner"]
        self.prefix = prefix            # 例如 "/v1"，用于测试前缀自动补全
        self.completions: list[dict] = []
        self.fail_model_get = False

    def handle_get(self, url, headers=None):
        if self.fail_model_get:
            return FakeResponse(404, {})
        if url.endswith(self.prefix + "/models"):
            return FakeResponse(200, {"data": [{"id": m} for m in self.models]})
        return FakeResponse(404, {})

    def handle_post(self, url, payload=None, headers=None):
        if url.endswith(self.prefix + "/chat/completions"):
            self.completions.append(payload)
            text = payload["messages"][-1]["content"]
            return FakeResponse(200, {"choices": [{"message": {"content": "【" + text + "】已翻译"}}]})
        return FakeResponse(404, {})


def _client(server: FakeServer, model="deepseek-chat", cache=None) -> OpenAiCompatClient:
    opts = ClientOptions(api_base="https://fake.local", api_key="sk-test", model=model)
    opts.get = server.handle_get
    opts.post = server.handle_post
    return OpenAiCompatClient(opts, cache=cache)


def test_prefix_fallback_to_v1():
    srv = FakeServer(prefix="/v1")
    c = _client(srv)
    assert c.resolve_prefix() == "https://fake.local/v1"
    models = c.list_models()
    assert "deepseek-chat" in models


def test_translate_and_cache_hit(tmp_path):
    srv = FakeServer(prefix="")
    cache = TranslationCache(path=tmp_path / "c.json")
    c = _client(srv, cache=cache)
    out1 = c.translate_line("Hello citizen", "en", "zh-CN")
    assert "已翻译" in out1
    out2 = c.translate_line("Hello citizen", "en", "zh-CN")  # 缓存命中，不再请求
    assert out2 == out1
    assert len(srv.completions) == 1


def test_chinese_passthrough_no_request():
    srv = FakeServer(prefix="")
    c = _client(srv)
    out = c.translate_line("任务已完成，返回机库", "auto", "zh-CN")
    assert out == "任务已完成，返回机库"
    assert len(srv.completions) == 0


class _EmptyServer(FakeServer):
    """模拟 HTTP 200 但 content 为空的响应。"""

    def handle_post(self, url, payload=None, headers=None):
        return FakeResponse(200, {"choices": [{"message": {"content": "  "}}]})


def test_empty_content_200_treated_as_error():
    """HTTP 200 但返回空内容：必须报错（不能静默空白）。"""
    from sc_translator.translate.client import ApiError, ClientOptions, OpenAiCompatClient

    srv = _EmptyServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    try:
        c.translate_line("hello", "en", "zh-CN")
        raise AssertionError("应当抛出 ApiError")
    except ApiError as exc:
        assert exc.status == 200
        assert "空内容" in str(exc)


def test_v4_model_disables_thinking_mode():
    """deepseek-v4* 默认 Thinking，需显式 disabled，否则 content 为空（官方文档）。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    srv = FakeServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="deepseek-v4-flash")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    c.translate_line("hi", "en", "zh-CN")
    payload = srv.completions[0]
    assert payload["thinking"] == {"type": "disabled"}

    srv2 = FakeServer(prefix="")
    opts2 = ClientOptions(api_base="https://fake.local", api_key="k", model="deepseek-chat")
    opts2.get = srv2.handle_get
    opts2.post = srv2.handle_post
    c2 = OpenAiCompatClient(opts2, cache=None)
    c2.translate_line("hi", "en", "zh-CN")
    assert "thinking" not in srv2.completions[0]


def test_batch_translation_numbered_parsing():
    """批量翻译：一次请求多行，按编号解析并保证与输入对齐。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    class NumberedServer(FakeServer):
        def handle_post(self, url, payload=None, headers=None):
            if url.endswith("/chat/completions"):
                self.completions.append(payload)
                # 模拟按编号输出（颠倒顺序、带噪音行，验证解析健壮）
                body = "先一句废话\n\n2. B 译文\n1. A 译文\n说明行"
                return FakeResponse(200, {"choices": [{"message": {"content": body}}]})
            return FakeResponse(404, {})

    srv = NumberedServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    out = c.translate_lines_batch(["alpha line", "beta line"], "en", "zh-CN")
    assert len(out) == 2
    assert out[0] == "A 译文"
    assert out[1] == "B 译文"
    assert len(srv.completions) == 1  # 只发了一次请求


def test_dict_hit_skips_api(tmp_path):
    """词典优先：命中词条直接返回中文，不发请求。"""
    from sc_translator import gamedict
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    d = tmp_path / "d.ini"
    d.write_text("Accept Contract = 接受合同\n", encoding="utf-8")
    gamedict.load(str(d))
    try:
        srv = FakeServer(prefix="")
        opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m")
        opts.get = srv.handle_get
        opts.post = srv.handle_post
        c = OpenAiCompatClient(opts, cache=None)
        assert c.translate_line("Accept Contract", "en", "zh-CN") == "接受合同"
        out = c.translate_lines_batch(["Accept Contract", "unknown line"], "en", "zh-CN")
        assert out[0] == "接受合同"
        # 词典命中的行绝不进 API（假服务无编号输出会触发兜底，不影响本断言）
        sent = [p["messages"][-1]["content"] for p in srv.completions]
        assert all("Accept Contract" not in s for s in sent)
        assert any("unknown line" in s for s in sent)
    finally:
        gamedict.clear()


def test_reply_exchange_log_style_reflects_spicy(tmp_home):
    """F2 回归：嘴臭回话在交换日志里必须标 style=spicy。"""
    from sc_translator import exchange_log
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    exchange_log.reset()
    srv = FakeServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    c.translate_reply("别跑啊，单挑", "English", spicy=True)
    c.translate_reply("你好", "English", spicy=False)
    exchange_log.reset()
    content = (tmp_home / "logs" / "exchange.log").read_text(encoding="utf-8")
    assert "style=spicy" in content
    assert "style=normal" in content


def test_retry_on_429_then_success():
    calls = {"n": 0}

    class Server429(FakeServer):
        def handle_post(self, url, payload=None, headers=None):
            calls["n"] += 1
            if calls["n"] <= 2:
                return FakeResponse(429, {"error": "slow down"})
            return super().handle_post(url, payload, headers)

    srv = Server429(prefix="")
    c = _client(srv)
    # 缩短重试等待
    c.opts.max_retries = 2
    c.opts.retry_base_s = 0.0
    out = c.translate_line("retry me", "en", "zh-CN")
    assert "已翻译" in out
    assert calls["n"] == 3


def test_spicy_toggle_switches_prompt():
    """嘴臭开关只切换译文提示词：关闭=正常提示词；开启=嘴臭提示词（无自动反击）。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    # --- 关闭（默认）：正常翻译提示词，不含嘴臭风格 ---
    srv = FakeServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    c.translate_line("hello there", "en", "zh-CN")
    normal_sys = srv.completions[0]["messages"][0]["content"]
    assert "垃圾话" not in normal_sys and "嘴臭" not in normal_sys

    # --- 开启：同一文本走嘴臭附加提示 ---
    srv1 = FakeServer(prefix="")
    opts1 = ClientOptions(api_base="https://fake.local", api_key="k", model="m", spicy=True)
    opts1.get = srv1.handle_get
    opts1.post = srv1.handle_post
    c1 = OpenAiCompatClient(opts1, cache=None)
    c1.translate_line("hello there", "en", "zh-CN")
    spicy_sys = srv1.completions[0]["messages"][0]["content"]
    assert "嘴臭" in spicy_sys and "垃圾话" in spicy_sys
    assert "反击" not in spicy_sys  # 无自动反击相关逻辑


def test_spicy_and_normal_translations_cached_separately(tmp_path):
    """同一文本在正常/嘴臭两态下缓存互不污染（切换开关不命中旧风格）。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    cache = TranslationCache(path=tmp_path / "c.json")

    def build(spicy):
        srv = FakeServer(prefix="")
        opts = ClientOptions(api_base="https://fake.local", api_key="k", model="m", spicy=spicy)
        opts.get = srv.handle_get
        opts.post = srv.handle_post
        return srv, OpenAiCompatClient(opts, cache=cache)

    srv_a, c_a = build(spicy=True)
    srv_b, c_b = build(spicy=False)
    c_a.translate_line("same text", "en", "zh-CN")
    c_b.translate_line("same text", "en", "zh-CN")
    assert len(srv_a.completions) == 1 and len(srv_b.completions) == 1


def test_final_error_raises():
    class Server500(FakeServer):
        def handle_post(self, url, payload=None, headers=None):
            return FakeResponse(500, {})

    srv = Server500(prefix="")
    c = _client(srv)
    c.opts.max_retries = 0
    try:
        c.translate_line("boom", "en", "zh-CN")
        raise AssertionError("应当抛错")
    except ApiError:
        pass


def test_cache_persists(tmp_home):
    cache_path = tmp_home / "cache.json"
    c1 = TranslationCache(path=cache_path)
    c1.put("m", "en", "alpha", "阿尔法")
    c1.flush()
    c2 = TranslationCache(path=cache_path)
    assert c2.get("m", "en", "alpha") == "阿尔法"


def test_dpapi_roundtrip():
    data = "sk-secret-中文-键"
    enc = protect(data.encode("utf-8"))
    assert enc != data.encode("utf-8")
    assert unprotect(enc).decode("utf-8") == data
