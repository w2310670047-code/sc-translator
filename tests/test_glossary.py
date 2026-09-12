"""SC 术语表(专名预替换)测试。"""

from sc_translator import glossary

_TERMS = """Stanton = 斯坦顿星系
Pyro = 派罗星系
Pyro System = 派罗星系(全)
Microtech = 微科技
"""


def test_apply_replaces_terms(tmp_path):
    p = tmp_path / "g.ini"
    p.write_text(_TERMS, encoding="utf-8")
    assert glossary.load(str(p)) == 4
    assert glossary.apply("Heading to Stanton") == "Heading to 斯坦顿星系"
    assert glossary.apply("I am in Pyro now") == "I am in 派罗星系 now"
    # 多词词条优先
    assert glossary.apply("Traveling to the Pyro System") == "Traveling to the 派罗星系(全)"
    # 大小写不敏感
    assert "派罗" in glossary.apply("see you in PYRO")
    # 嵌在更长单词里的子串不受影响
    assert "Stantons" == glossary.apply("Stantons")
    assert "Microtechnology" == glossary.apply("Microtechnology")
    assert glossary.apply("Visit Microtech") == "Visit 微科技"
    glossary.clear()


def test_defaults_and_boundary(tmp_path):
    glossary.clear()
    glossary.ensure_defaults()
    assert glossary.configured()
    assert glossary.apply("meet at Stanton") == "meet at 斯坦顿星系"
    assert glossary.apply("say Stantonville") == "say Stantonville"
    glossary.clear()
    assert not glossary.configured()
    assert glossary.apply("Stanton") == "Stanton"


def test_load_missing_returns_zero(tmp_path):
    assert glossary.load(str(tmp_path / "x.ini")) == 0
    assert glossary.configured() is False
