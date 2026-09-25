"""方案 C（模型直接读图）回归：请求格式、输出解析、快照分支、界面开关。

- 客户端：按官方 /guides/vision 的 OpenAI 兼容格式构造图片消息（data URL + detail=low）；
- 快照：开着「模型直接读图」时必须**完全不碰本地 OCR**，关着时照旧走本地 OCR；
- 界面：勾选落盘，并且读图模式下「GPU 加速」自动置灰。
"""

from __future__ import annotations

import os

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("SC_CI_SKIP_GUI", "") == "1", reason="环境跳过")

REGION = {
    "logical": {"x": 0, "y": 0, "w": 400, "h": 200},
    "physical": {"left": 0, "top": 0, "width": 800, "height": 400},
    "label": "屏幕1",
}


# ---------------------------------------------------------------- 输出解析
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1. Quantum travel => 量子航行\n2. Bounty => 赏金",
         [("Quantum travel", "量子航行"), ("Bounty", "赏金")]),
        ("1. A → 甲\n2. B ⇒ 乙", [("A", "甲"), ("B", "乙")]),
        ("1、A => 甲", [("A", "甲")]),                       # 中文序号
        ("A => 甲", [("A", "甲")]),                          # 无序号
        ("```\n1. A => 甲\n```\n以上是识别结果", [("A", "甲")]),  # 围栏与说明文字要丢掉
        ("Quantum travel", [("", "Quantum travel")]),        # 缺分隔符 → 整行当译文
        ("", []),
    ],
)
def test_parse_vision_pairs(raw, expected):
    from sc_translator.translate.client import parse_vision_pairs

    assert parse_vision_pairs(raw) == expected


def test_parse_vision_pairs_respects_max_lines():
    from sc_translator.translate.client import parse_vision_pairs

    raw = "\n".join(f"{i}. line{i} => 译{i}" for i in range(1, 11))
    assert len(parse_vision_pairs(raw, max_lines=3)) == 3


# ---------------------------------------------------------------- 请求格式
class _Resp:
    status_code = 200
    text = ""

    def __init__(self, content=""):
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _client(captured: dict, content: str):
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    def fake_get(url, headers=None, **kw):  # noqa: ARG001
        return _Resp("")          # resolve_prefix 只看 status_code

    def fake_post(url, payload=None, headers=None, **kw):  # noqa: ARG001
        captured["url"] = url
        captured["payload"] = payload
        return _Resp(content)

    return OpenAiCompatClient(ClientOptions(api_base="https://vision.invalid", api_key="k",
                                            model="deepseek-flash", post=fake_post, get=fake_get))


def test_translate_image_builds_official_vision_payload():
    captured: dict = {}
    c = _client(captured, "1. Quantum travel => 量子航行")
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 200
    pairs = c.translate_image(png, target_lang="zh-CN", max_lines=10)
    assert pairs == [("Quantum travel", "量子航行")]

    payload = captured["payload"]
    assert payload["model"] == "deepseek-flash" and payload["stream"] is False
    system = payload["messages"][0]["content"]
    assert "原文 => 译文" in system and "简体中文" in system
    blocks = payload["messages"][1]["content"]
    assert isinstance(blocks, list) and blocks[0]["type"] == "text"
    img = blocks[1]
    assert img["type"] == "image_url"
    assert img["image_url"]["url"].startswith("data:image/png;base64,"), img["image_url"]["url"][:40]
    assert img["image_url"]["detail"] == "low", "官方文档：low 会缩到 512×512，更省 token"


def test_translate_image_unparseable_raises_with_hint():
    from sc_translator.translate.client import ApiError

    c = _client({}, "```\n```")
    with pytest.raises(ApiError) as ei:
        c.translate_image(b"\x89PNG" + b"y" * 50)
    assert "格式" in str(ei.value) and "本地 OCR" in str(ei.value)


# ---------------------------------------------------------------- 快照分支
class _Capture:
    BACKENDS = ["dxcam", "mss", "qt"]

    def __init__(self):
        self.calls = []
        self.frame = np.zeros((40, 80, 3), dtype=np.uint8)

    def grab_ex(self, phys):
        self.calls.append(phys)
        return self.frame, self.BACKENDS[0], ""

    def close(self):
        pass


class _Ocr:
    """若被调用就说明分支走错了。"""

    def __init__(self):
        self.calls = 0

    def recognize(self, img):  # noqa: ARG002
        self.calls += 1
        return []


class _Client:
    def __init__(self, pairs=None, fail=None):
        self.pairs = pairs if pairs is not None else [("Quantum travel", "量子航行")]
        self.fail = fail
        self.image_calls: list[tuple] = []
        self.batch_calls: list[list[str]] = []

    def translate_image(self, image, target_lang="zh-CN", *, max_lines=40, **kw):  # noqa: ARG002
        self.image_calls.append((len(image), target_lang, max_lines))
        if self.fail:
            raise self.fail
        return list(self.pairs)

    def translate_lines_batch(self, texts, source_lang="auto", target_lang="zh-CN",
                             keep_chat_prefix=False):  # noqa: ARG002
        self.batch_calls.append(list(texts))
        return [f"译:{t}" for t in texts]


class _App:
    def __init__(self, client, vision: bool):
        self.client = client
        self.use_cache = None

        class _S:
            ocr_vision = vision

        self.settings = _S()

    def make_client(self, use_cache=True):
        self.use_cache = use_cache
        return self.client

    def run_in_thread(self, fn, cb):
        try:
            cb(True, fn())
        except Exception as exc:  # noqa: BLE001
            cb(False, exc)


def _svc(vision: bool, client: _Client):
    from sc_translator.snapshot import SnapshotService

    svc = SnapshotService(_App(client, vision))
    svc._capture = _Capture()
    svc._ocr = _Ocr()
    return svc


def test_vision_on_uses_image_and_never_touches_local_ocr():
    client = _Client([("Quantum travel", "量子航行"), ("Bounty", "赏金")])
    svc = _svc(vision=True, client=client)
    res = svc._work(REGION, max_lines=40, use_cache=True)
    assert res.vision is True
    assert [ln.source for ln in res.lines] == ["Quantum travel", "Bounty"]
    assert [ln.translated for ln in res.lines] == ["量子航行", "赏金"]
    assert svc._ocr.calls == 0, "读图模式绝不能触发本地 OCR"
    assert client.batch_calls == [], "读图模式不该再走一遍文字批量翻译"
    assert client.image_calls and client.image_calls[0][1] == "zh-CN"
    assert client.image_calls[0][0] > 100, "应真的编码出 PNG 后再发"
    assert svc.app.use_cache is False, "图片结果不进文本缓存"


def test_vision_off_uses_local_ocr_then_batch_translate():
    client = _Client()
    svc = _svc(vision=False, client=client)
    svc._ocr = _OcrWith("Quantum travel")
    res = svc._work(REGION, max_lines=40, use_cache=True)
    assert res.vision is False
    assert client.image_calls == [] and len(client.batch_calls) == 1
    assert svc._ocr.calls == 1


class _OcrWith(_Ocr):
    def __init__(self, text):
        super().__init__()
        self.text = text

    def recognize(self, img):  # noqa: ARG002
        self.calls += 1

        class _R:
            def __init__(self, t):
                self.text = t

        return [_R(self.text)]


def test_vision_failure_reports_readable_error():
    from sc_translator.translate.client import ApiError

    svc = _svc(vision=True, client=_Client(fail=ApiError("HTTP 400: image_url 不支持")))
    res = svc._work(REGION, max_lines=40, use_cache=True)
    assert res.lines == [] and res.vision is True
    assert "读图翻译失败" in res.error and "image_url" in res.error


def test_vision_requires_region():
    svc = _svc(vision=True, client=_Client())
    res = svc._work({}, max_lines=10, use_cache=True)
    assert res.lines == [] and "框选" in res.error


# ---------------------------------------------------------------- 界面
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


def test_vision_checkbox_persists_and_greys_out_gpu(qapp, tmp_home):
    ctrl = _mk_ctrl(qapp, tmp_home)
    win = ctrl.mainwin
    assert win._ocr_vision.isChecked() is False
    assert win._ocr_gpu.isEnabled() is True

    win._ocr_vision.setChecked(True)
    assert ctrl.settings.ocr_vision is True
    assert win._ocr_gpu.isEnabled() is False, "读图模式下 GPU 开关没有意义"
    assert win._status.text()

    win._ocr_vision.setChecked(False)
    assert ctrl.settings.ocr_vision is False
    assert win._ocr_gpu.isEnabled() is True
    ctrl.shutdown()


def test_vision_checked_at_startup_greys_out_gpu(qapp, tmp_home):
    ctrl = _mk_ctrl(qapp, tmp_home, ocr_vision=True)
    assert ctrl.mainwin._ocr_vision.isChecked() is True
    assert ctrl.mainwin._ocr_gpu.isEnabled() is False
    ctrl.shutdown()
