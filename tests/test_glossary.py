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

# ------------------------------------------------------------------ 加载与性能回归
def test_large_glossary_is_not_silently_truncated(tmp_path, monkeypatch):
    """回归：加载上限曾是 4000 且按文件顺序截断，导致 8000+ 条的术语表只装了一半、
    短专名（Stanton/Pyro）全被丢掉、一个都替换不上。"""
    from sc_translator import glossary

    path = tmp_path / "big.ini"
    lines = [f"term number {i} = 词条{i}" for i in range(9000)]
    lines.append("stanton = 斯坦顿星系")
    path.write_text("\n".join(lines), encoding="utf-8")
    n = glossary.load(str(path))
    assert n == 9001, f"应全部载入，实际 {n}"
    assert glossary.apply("go to stanton now") == "go to 斯坦顿星系 now"


def test_pattern_compiled_lazily(tmp_path):
    """回归：8000+ 词条的正则编译约 0.9 秒，不能放在启动路径（窗口会晚出现）。"""
    from sc_translator import glossary

    path = tmp_path / "lazy.ini"
    path.write_text("\n".join(f"term {i} here = 词条{i}" for i in range(3000)), encoding="utf-8")
    glossary.load(str(path))
    assert glossary._pattern is None, "加载时不应立即编译正则"
    assert glossary.apply("term 5 here") == "词条5", "首次 apply 应自动编译并生效"
    assert glossary._pattern is not None