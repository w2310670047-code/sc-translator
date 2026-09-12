"""Settings 与 API Key 存储测试。"""

from sc_translator.settings import Settings


def test_settings_roundtrip(tmp_home):
    s = Settings().load()
    s.api_base = "https://example.com/v1"
    s.model = "test-model"
    s.region = {"logical": {"x": 1, "y": 2, "w": 3, "h": 4}, "physical": {"left": 1}, "dpr": 1.0, "label": "屏幕1"}
    s.save()
    s2 = Settings().load()
    assert s2.api_base == "https://example.com/v1"
    assert s2.model == "test-model"
    assert s2.region["logical"]["w"] == 3


def test_api_key_dpapi_roundtrip(tmp_home):
    s = Settings().load()
    s.save_api_key("sk-12345")
    assert s.load_api_key() == "sk-12345"
    # 文件不是明文
    raw = (tmp_home / "api_key.bin").read_bytes()
    assert b"sk-12345" not in raw
    # 清空即删除
    s.save_api_key("")
    assert not (tmp_home / "api_key.bin").exists()
