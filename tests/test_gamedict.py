"""SC 翻译词典(词典优先层)测试。"""

from sc_translator import gamedict

_DICT = """# 注释
Accept Contract = 接受合同
Quantum Travel = 量子跃迁
Cargo Space = 货舱空间
Claim Ship = 索赔飞船
Arrive at OM-1 Marker = 抵达 OM-1 标记点
"""


def test_load_and_lookup(tmp_path):
    p = tmp_path / "dict.ini"
    p.write_text(_DICT, encoding="utf-8")
    data = gamedict.load(str(p))
    assert len(data) >= 5
    assert gamedict.lookup("Accept Contract") == "接受合同"
    # 空白/大小写差异仍命中
    assert gamedict.lookup("  accept   contract  ") == "接受合同"
    # 丢空格变体命中（OCR 常见）
    assert gamedict.lookup("AcceptContract") == "接受合同"
    # 未命中返回 None
    assert gamedict.lookup("I need a ride") is None
    gamedict.clear()


def test_unconfigured_lookup_none(tmp_path):
    gamedict.clear()
    assert gamedict.lookup("Anything") is None
    # 不存在的路径 -> 空
    assert gamedict.load(str(tmp_path / "nope.ini")) == {}
    gamedict.clear()


def test_write_sample(tmp_path):
    p = tmp_path / "s.ini"
    assert gamedict.write_sample(str(p)) is True
    assert p.exists()
    gamedict.clear()


def test_build_pair_dictionary(tmp_path):
    en = tmp_path / "en.ini"
    zh = tmp_path / "zh.ini"
    en.write_text("k1=Accept Contract\nk2=Quantum Drive\nk3=Some Big Mission\nk4=hello\nk5=数值 123\nk6=One\n",
                  encoding="utf-8")
    zh.write_text("k1=接受合同\nk2=量子引擎\nk3=任务很长\nk5=数字值\nk6=一个带\n换行\n", encoding="utf-8")
    out = tmp_path / "full.ini"
    written, skipped = gamedict.build_pair_dictionary(str(en), str(zh), str(out))
    # k1/k2/k3 可配对；k4 无中文、k5 占位无字母 跳过；k6 中文包换行被切出片段仍配出(现实产物，接受)
    assert written == 4
    assert "Accept Contract = 接受合同" in out.read_text(encoding="utf-8")
    gamedict.clear()
