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
    """HTTP 200 但返回空内容：必须报错（不能静默空白），并带上真实原因。"""
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


class _GatewayServer(FakeServer):
    """OpenAI 兼容网关：不认识 thinking 参数（用于验证我们不会误伤这类服务）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.saw_thinking = []

    def handle_post(self, url, payload=None, headers=None):
        self.saw_thinking.append("thinking" in (payload or {}))
        if "thinking" in (payload or {}):
            return FakeResponse(400, {"error": {"message": "unknown parameter: thinking"}})
        return super().handle_post(url, payload, headers)


class _ThinkingLeakServer(FakeServer):
    """第一次把内容留在 reasoning_content（content 空），关掉思考后才正常。

    这正是 deepseek-flash 上的真实现象：思考吃满 max_tokens → content 为空、HTTP 200。
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.payloads: list[dict] = []

    def handle_post(self, url, payload=None, headers=None):
        self.payloads.append(dict(payload or {}))
        if "thinking" not in (payload or {}):
            return FakeResponse(200, {
                "choices": [{
                    "message": {"content": "", "reasoning_content": "让我想想……" * 20},
                    "finish_reason": "length",
                }],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 152}},
            })
        return FakeResponse(200, {"choices": [{"message": {"content": "你好"}, "finish_reason": "stop"}]})


def test_flash_model_disables_thinking_mode():
    """deepseek-flash 同样默认思考（实测 reasoning_tokens=152），必须显式关闭。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    srv = FakeServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="deepseek-flash")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    c.translate_line("hello", "en", "zh-CN")
    assert srv.completions[-1].get("thinking") == {"type": "disabled"}, srv.completions[-1]


def test_thinking_model_table():
    from sc_translator.translate.client import OpenAiCompatClient as C

    # 官方文档：DeepSeek 模型思考模式默认打开（含 deepseek-chat 系），故 deepseek* 一律关闭
    for m in ("deepseek-v4-pro", "deepseek-v4-flash", "deepseek-flash", "deepseek-chat",
              "deepseek-reasoner", "x-thinking-y", "openrouter/deepseek-v4-pro"):
        assert C.needs_thinking_off(m) is True, m
    for m in ("gpt-4o-mini", "qwen2.5-7b", "glm-4-flash", ""):
        assert C.needs_thinking_off(m) is False, m


def test_empty_content_retries_with_thinking_disabled():
    """没关思考导致 content 为空 -> 自动关掉思考重试一次并成功（关键兜底）。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    srv = _ThinkingLeakServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="some-unknown-model")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    out = c.translate_line("hello", "en", "zh-CN")
    assert out == "你好"
    assert len(srv.payloads) == 2, "应当先失败一次、再带 thinking=disabled 重试一次"
    assert "thinking" not in srv.payloads[0], "首次请求不该无缘无故带 thinking（避免不认识该参数的网关报错）"
    assert srv.payloads[1]["thinking"] == {"type": "disabled"}


class _AlwaysEmptyServer(FakeServer):
    """无论是否关闭思考都返回空 content（例如预算被截断/模型异常）。"""

    def handle_post(self, url, payload=None, headers=None):
        return FakeResponse(200, {
            "choices": [{"message": {"content": "", "reasoning_content": "……"}, "finish_reason": "length"}],
            "usage": {"completion_tokens_details": {"reasoning_tokens": 152}},
        })


def test_empty_content_error_explains_thinking_budget():
    """两次都空：错误信息要说清"思考吃满预算"，而不是笼统一句空内容。"""
    from sc_translator.translate.client import ApiError, ClientOptions, OpenAiCompatClient

    srv = _AlwaysEmptyServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="deepseek-flash")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    try:
        c.translate_line("hello", "en", "zh-CN")
        raise AssertionError("应当抛出 ApiError")
    except ApiError as exc:
        msg = str(exc)
        assert "空内容" in msg
        assert "思考" in msg and "reasoning_tokens=152" in msg, msg


def test_unknown_gateway_does_not_get_thinking_param():
    """非 thinking 模型的首次请求不带 thinking，避免网关因未知参数拒绝。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    srv = _GatewayServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="gpt-4o-mini")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    assert c.translate_line("hello", "en", "zh-CN")
    assert srv.saw_thinking == [False], srv.saw_thinking


class _RejectThinkingServer(FakeServer):
    """严格网关：收到未知参数 thinking 直接 400（官方 API 接受，但自建网关可能不接受）。"""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.payloads: list[dict] = []

    def handle_post(self, url, payload=None, headers=None):
        self.payloads.append(dict(payload or {}))
        if "thinking" in (payload or {}):
            return FakeResponse(400, {"error": {"message": "Failed to deserialize: thinking: unknown field"}})
        return FakeResponse(200, {"choices": [{"message": {"content": "译好了"}}]})


def test_thinking_param_dropped_when_gateway_rejects_it():
    """网关因 thinking 参数报 400 时，自动去掉参数重试并记住（不再重复踩）。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    srv = _RejectThinkingServer(prefix="")
    opts = ClientOptions(api_base="https://fake.local", api_key="k", model="deepseek-flash")
    opts.get = srv.handle_get
    opts.post = srv.handle_post
    c = OpenAiCompatClient(opts, cache=None)
    assert c.translate_line("hello", "en", "zh-CN") == "译好了"
    assert c._no_thinking is True
    assert "thinking" in srv.payloads[0], "第一次会带 thinking"
    assert "thinking" not in srv.payloads[1], "被拒后应去掉参数重试"
    # 后续请求不再带该参数
    srv.payloads.clear()
    c.translate_line("world", "en", "zh-CN")
    assert all("thinking" not in p for p in srv.payloads), srv.payloads


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
    # 官方文档：思考模式对 DeepSeek 模型默认打开，deepseek-chat 同样要关
    assert srv2.completions[0]["thinking"] == {"type": "disabled"}

    srv3 = FakeServer(prefix="")
    opts3 = ClientOptions(api_base="https://fake.local", api_key="k", model="gpt-4o-mini")
    opts3.get = srv3.handle_get
    opts3.post = srv3.handle_post
    c3 = OpenAiCompatClient(opts3, cache=None)
    c3.translate_line("hi", "en", "zh-CN")
    assert "thinking" not in srv3.completions[0], "非 DeepSeek 模型不该带该参数"


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


def test_cache_autosave_does_not_deadlock(tmp_home):
    """第 25 次 put 会自动落盘，绝不能自我死锁（真实故障：截图翻译第 3 次卡死）。

    旧实现 put() 持着 self._lock 调 flush()，而 flush() 又要拿同一把
    **非可重入**锁 ⇒ 该线程永久卡住：界面停在"正在识别并翻译"，关窗时主线程
    抢同一把锁而冻结（Windows 报"Python 未响应"）。

    这里用带超时的 join 守住：一旦回归，测试失败而不是把整个测试套件挂死。
    """
    import json
    import threading

    cache_path = tmp_home / "cache.json"
    cache = TranslationCache(path=cache_path)
    done = threading.Event()

    def work():
        for i in range(60):          # 会跨过 25 与 50 两个自动落盘点
            cache.put("m", "auto", f"t{i}", f"o{i}")
        done.set()

    th = threading.Thread(target=work, daemon=True)
    th.start()
    assert done.wait(timeout=10), "第 25 次 put 之后卡住了（缓存锁自我死锁回归）"
    assert not th.is_alive()
    saved = json.loads(cache_path.read_text(encoding="utf-8"))
    assert len(saved) >= 25, len(saved)   # 至少落盘过一次
    assert not cache._lock.locked(), "落盘后锁必须已释放"


def test_cache_flush_timeout_when_lock_held(tmp_home):
    """退出兜底：锁被别的线程持有时，flush(timeout) 必须放弃而不是干等。"""
    import time

    cache = TranslationCache(path=tmp_home / "cache.json")
    cache.put("m", "en", "a", "甲")
    cache._lock.acquire()            # 模拟"有线程卡在持锁位置"
    try:
        t0 = time.time()
        assert cache.flush(timeout=0.2) is False
        assert time.time() - t0 < 3, "flush(timeout) 不应长时间阻塞"
    finally:
        cache._lock.release()
    assert cache.flush(timeout=0.2) is True


def test_clients_share_one_http_session():
    """共享 Session：保持 TCP/TLS 长连接，省掉每次热键重新握手。"""
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    c1 = OpenAiCompatClient(ClientOptions(api_base="https://a.invalid"))
    c2 = OpenAiCompatClient(ClientOptions(api_base="https://b.invalid"))
    assert c1._session is c2._session


def test_prefix_probed_once_per_base_across_clients():
    """截图翻译每轮都新建客户端，但 /models 前缀探测只能发生一次。

    真实故障：每按一次热键都重新探测前缀（日志里 4395ms / 1960ms 各一次），
    再加上重新握手的 TLS，等于每次白等 1~4.5 秒。
    """
    from sc_translator.translate import client as client_mod
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    base = "https://prefix-probe.invalid/api"

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {"data": []}

    calls: list[str] = []

    def fake_get(url, headers=None, **kw):  # noqa: ARG001
        calls.append(url)
        return _Resp()

    client_mod._PREFIX_CACHE.pop(base, None)
    opts = ClientOptions(api_base=base, api_key="k", model="m", get=fake_get)
    assert OpenAiCompatClient(opts).resolve_prefix() == base
    assert OpenAiCompatClient(opts).resolve_prefix() == base   # 新客户端应复用缓存
    assert len(calls) == 1, calls

    # 换 base（=换服务商）必须重新探测
    other = base + "-other"
    client_mod._PREFIX_CACHE.pop(other, None)
    assert OpenAiCompatClient(ClientOptions(api_base=other, api_key="k", model="m",
                                            get=fake_get)).resolve_prefix() == other
    assert len(calls) == 2, calls


def test_dpapi_roundtrip():
    data = "sk-secret-中文-键"
    enc = protect(data.encode("utf-8"))
    assert enc != data.encode("utf-8")
    assert unprotect(enc).decode("utf-8") == data
