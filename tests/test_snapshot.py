"""截图翻译：热键解析 / 行过滤 / 一次性流水线（用替身，不真抓屏、不联网）。

真实 OCR 冒烟在 tests/test_ocr.py；这里只验证编排逻辑。
"""

from __future__ import annotations

import pytest

from sc_translator import snapshot


# ------------------------------------------------------------------ 热键解析
@pytest.mark.parametrize(
    "spec,mods,vk",
    [
        ("F9", 0, 0x78),
        ("F10", 0, 0x79),
        ("f1", 0, 0x70),
        ("Ctrl+Shift+S", 0x0002 | 0x0004, ord("S")),
        ("alt+f4", 0x0001, 0x73),
        ("PrintScreen", 0, 0x2C),
        ("ctrl + z", 0x0002, ord("Z")),
    ],
)
def test_parse_hotkey(spec, mods, vk):
    assert snapshot.parse_hotkey(spec) == (mods, vk)


@pytest.mark.parametrize("spec", ["", "   ", "Bogus", "Ctrl+", "F99x", "中文键"])
def test_parse_hotkey_rejects_garbage(spec):
    assert snapshot.parse_hotkey(spec) is None


def test_hotkey_label_roundtrip():
    assert snapshot.hotkey_label("F9") == "F9"
    assert snapshot.hotkey_label("ctrl+shift+s") == "Ctrl+Shift+S"
    assert snapshot.hotkey_label("PrintScreen") == "Printscreen"
    assert snapshot.hotkey_label("不是热键") == "不是热键"   # 无法解析时原样返回


# ------------------------------------------------------------------ 行过滤
def test_filter_lines_drops_noise_and_dups():
    raw = [
        "Quantum travel",
        "12345",            # 纯数字
        "---",              # 纯符号
        "Hello there",
        "hello THERE",      # 大小写不同的重复
        "",                 # 空
        "a",                # 单字符（无实义，丢）
        "ok",               # 短但确实是词 → 保留，宁可多翻不要漏
        "Bounty hunting is fun",
    ]
    assert snapshot.filter_lines(raw) == [
        "Quantum travel",
        "Hello there",
        "ok",
        "Bounty hunting is fun",
    ]


def test_filter_lines_keeps_cjk_and_kana():
    raw = ["斯坦顿星系", "こんにちは", "안녕하세요", "！？"]
    assert snapshot.filter_lines(raw) == ["斯坦顿星系", "こんにちは", "안녕하세요"]


def test_filter_lines_caps_length():
    assert snapshot.filter_lines(["x" * 400]) == []


# ------------------------------------------------------------------ 流水线（替身）
class _FakeCapture:
    """替身：实现新的 grab_ex 协议（返回 图像/后端/错误）。"""

    BACKENDS = ("dxcam", "mss", "qt")

    def __init__(self, frame=b"frame"):
        self.frame = frame
        self.calls = []

    def grab_ex(self, phys):
        self.calls.append(phys)
        if self.frame is None:
            return None, "", "dxcam: 失败；mss: BitBlt 失败"
        return self.frame, self.BACKENDS[0], ""

    def grab(self, phys):
        img, _b, _e = self.grab_ex(phys)
        return img

    def close(self):
        pass


class _FakeOcr:
    def __init__(self, texts):
        self.texts = texts

    def recognize(self, img):
        class _R:
            def __init__(self, t):
                self.text = t

        return [_R(t) for t in self.texts]


class _FakeClient:
    def __init__(self, out=None, fail=None):
        self.out = out
        self.fail = fail
        self.calls = []

    def translate_lines_batch(self, texts, source_lang="auto", target_lang="zh-CN", keep_chat_prefix=False):
        self.calls.append((list(texts), source_lang, target_lang))
        if self.fail:
            raise self.fail
        return self.out if self.out is not None else [f"译:{t}" for t in texts]


class _FakeApp:
    def __init__(self, client):
        self.client = client

    def make_client(self, use_cache=True):
        return self.client

    def run_in_thread(self, fn, cb):
        try:
            cb(True, fn())
        except Exception as exc:  # noqa: BLE001
            cb(False, exc)


def _svc(texts, client):
    svc = snapshot.SnapshotService(_FakeApp(client))
    svc._capture = _FakeCapture()
    svc._ocr = _FakeOcr(texts)
    return svc


REGION = {"logical": {"x": 0, "y": 0, "w": 400, "h": 200},
          "physical": {"left": 0, "top": 0, "width": 800, "height": 400},
          "label": "屏幕1"}


def test_work_full_pipeline():
    client = _FakeClient()
    svc = _svc(["Quantum travel", "12345", "Bounty"], client)
    res = svc._work(REGION, max_lines=40, use_cache=True)
    assert [ln.source for ln in res.lines] == ["Quantum travel", "Bounty"]
    assert [ln.translated for ln in res.lines] == ["译:Quantum travel", "译:Bounty"]
    assert res.error == ""
    # 送翻译的请求带术语表/目标语言参数，并且噪声行没被送出去
    assert client.calls[0][0] == ["Quantum travel", "Bounty"]
    assert client.calls[0][2] == "zh-CN"
    # 抓屏用的是区域里的物理矩形
    assert svc.capture.calls == [REGION["physical"]]


def test_work_requires_region():
    svc = _svc(["x"], _FakeClient())
    res = svc._work({}, max_lines=10, use_cache=True)
    assert res.lines == []
    assert "框选" in res.error


def test_work_handles_no_text():
    svc = _svc(["###", "42"], _FakeClient())   # 全被过滤掉
    res = svc._work(REGION, max_lines=10, use_cache=True)
    assert res.lines == []
    assert "没有识别到文字" in res.error


def test_work_keeps_source_when_translation_fails():
    from sc_translator.translate.client import ApiError

    svc = _svc(["Quantum travel"], _FakeClient(fail=ApiError("模型返回了空内容")))
    res = svc._work(REGION, max_lines=10, use_cache=True)
    assert [ln.source for ln in res.lines] == ["Quantum travel"], "翻译失败时仍要展示原文"
    assert all(ln.ok is False for ln in res.lines)
    assert "翻译失败" in res.error


def test_work_handles_capture_failure():
    svc = _svc(["x"], _FakeClient())
    svc._capture = _FakeCapture(frame=None)
    res = svc._work(REGION, max_lines=10, use_cache=True)
    assert res.lines == []
    assert "抓屏失败" in res.error


def test_work_respects_max_lines():
    client = _FakeClient()
    svc = _svc([f"Line number {i}" for i in range(30)], client)
    res = svc._work(REGION, max_lines=5, use_cache=True)
    assert len(res.lines) == 5
    assert len(client.calls[0][0]) == 5


def test_work_pads_missing_translations():
    """模型少返回几行时，缺的行标为失败但保留原文。"""
    svc = _svc(["First line", "Second line", "Third line"], _FakeClient(out=["一"]))
    res = svc._work(REGION, max_lines=10, use_cache=True)
    assert len(res.lines) == 3
    assert res.lines[0].translated == "一"
    assert res.lines[1].translated == "" and res.lines[1].ok is False


def test_run_delivers_result_via_callback():
    got = []
    svc = _svc(["Quantum travel"], _FakeClient())
    svc.run(REGION, got.append, max_lines=10)
    assert len(got) == 1
    assert got[0].lines[0].source == "Quantum travel"


def test_work_reports_ocr_text_before_translation():
    """分阶段反馈：OCR 一结束就先回调原文，且必须**早于**翻译请求。"""
    order: list[tuple] = []
    client = _FakeClient()
    svc = _svc(["Quantum travel", "12345", "Bounty"], client)

    def on_ocr(texts):
        order.append((list(texts), len(client.calls)))   # 此刻已发生的翻译调用次数

    svc._work(REGION, max_lines=40, use_cache=True, on_ocr=on_ocr)
    assert order == [(["Quantum travel", "Bounty"], 0)], order
    assert len(client.calls) == 1, "翻译照常只发一次"


def test_run_delivers_error_result():
    got = []
    svc = _svc(["x"], _FakeClient())
    svc.run({}, got.append, max_lines=10)
    assert len(got) == 1 and got[0].error


def test_consecutive_runs_with_real_cache_do_not_hang(tmp_home):
    """连续截图翻译不得卡死：真实故障是第 3 次永远停在"正在识别并翻译"。

    端到端复现路径：真实 ``OpenAiCompatClient`` + 真实 ``TranslationCache``，
    只把 HTTP 传输换成假响应。每次 10 行新文本，跑 3 次就会跨过缓存第 25 次
    自动落盘的临界点（旧实现在那里自我死锁 ⇒ 工作线程永不返回）。

    用带超时的线程守住：一旦回归，测试失败而不是把整个测试套件挂死。
    """
    import threading

    from sc_translator.translate.cache import TranslationCache
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    cache = TranslationCache(path=tmp_home / "cache.json")
    gets: list[str] = []

    class _Resp:
        status_code = 200
        text = ""

        def __init__(self, content=""):
            self._content = content

        def json(self):
            return {"choices": [{"message": {"content": self._content}}]}

    def fake_post(url, payload=None, headers=None, **kw):  # noqa: ARG001
        n = len((payload or {}).get("messages", [{}])[-1].get("content", "").splitlines())
        return _Resp("\n".join(f"{i + 1}. 译文{i + 1}" for i in range(n)))

    def fake_get(url, headers=None, **kw):  # noqa: ARG001
        gets.append(url)
        return _Resp("")          # resolve_prefix 只看 status_code

    class _App:
        def make_client(self, use_cache=True):
            opts = ClientOptions(api_base="https://fake.invalid", api_key="k", model="m",
                                 post=fake_post, get=fake_get)
            return OpenAiCompatClient(opts, cache=cache if use_cache else None)

    svc = snapshot.SnapshotService(_App())
    svc._capture = _FakeCapture()
    results = []

    def run_three():
        for run in range(3):
            svc._ocr = _FakeOcr([f"Quantum travel {run}-{i}" for i in range(10)])
            results.append(svc._work(REGION, max_lines=40, use_cache=True))

    th = threading.Thread(target=run_three, daemon=True)
    th.start()
    th.join(20)
    assert not th.is_alive(), "连续截图翻译卡住了（缓存自动落盘死锁回归）"
    assert len(results) == 3
    assert all(r.error == "" and len(r.lines) == 10 for r in results), [r.error for r in results]
    assert not cache._lock.locked(), "跑完必须没有残留持锁"
    # 每轮都会新建客户端，但 /models 前缀探测只能有一次（否则每按一次热键白等 1~4.5 秒）
    assert len(gets) == 1, gets
