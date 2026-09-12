"""游戏聊天码（中文 <-> 星际公民 @码）回归测试。

关键锚点：用本机真实汉化 global.ini（若存在）验证
``你好吗`` -> ``[zh] @IH@E8@AP``，这是社区实现的既定输出。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sc_translator import gamecode

# 迷你码表：与原格式一致（码 = 序号 base36，最少两位）
FAKE_TABLE = "\n".join(
    [
        "00=一",
        "01=乙",
        "0A=八",
        "AP=吗",
        "E8=好",
        "IH=你",
        "100=测",   # 3 位码
        "101=试",   # 3 位码
    ]
)


@pytest.fixture()
def table():
    gamecode.load_text(FAKE_TABLE, src="<test>")
    yield
    gamecode.clear()


# ------------------------------------------------------------------ 编码
def test_encode_matches_community_output(table):
    """核心锚点：中文 -> @码，码与码之间无分隔，前面带 [zh] 前缀。"""
    assert gamecode.encode("你好吗") == "[zh] @IH@E8@AP"
    assert gamecode.encode("好吗") == "[zh] @E8@AP"


def test_encode_keeps_ascii_and_separates(table):
    """ASCII/标点直通；与码相邻时补一个空格。"""
    assert gamecode.encode("你好吗 ok") == "[zh] @IH@E8@AP ok"
    assert gamecode.encode("go 好") == "[zh] go @E8"
    # 全角标点属于 Unicode P，按社区实现原样直通
    assert gamecode.encode("你好吗？") == "[zh] @IH@E8@AP ？"
    # 英文句点/问号同样直通
    assert gamecode.encode("ok?") == "[zh] ok?"


def test_encode_unknown_char_becomes_space(table):
    """码表未覆盖的字符丢成空格（与原实现一致，不报错）。"""
    out = gamecode.encode("你龘好")
    assert out.startswith("[zh] @IH")
    assert "龘" not in out
    assert out.endswith("@E8")


def test_encode_three_char_codes(table):
    assert gamecode.encode("测试") == "[zh] @100@101"


def test_encode_empty(table):
    assert gamecode.encode("") == ""
    assert gamecode.encode("   ") == ""


def test_encode_without_table_raises():
    gamecode.clear()
    with pytest.raises(gamecode.GameCodeError):
        gamecode.encode("你好")


# ------------------------------------------------------------------ 解码
def test_decode_roundtrip(table):
    for src in ("你好吗", "你好吗 ok", "ok 好吗", "测试你好"):
        assert gamecode.decode(gamecode.encode(src)).replace(" ", "") == src.replace(" ", "")


def test_decode_accepts_lowercase_and_missing_prefix(table):
    assert gamecode.decode("@ih@e8@ap") == "你好吗"
    assert gamecode.decode("[ZH] @IH@E8@AP") == "你好吗"
    assert gamecode.decode("  [zh]   @IH@E8@AP  ") == "你好吗"


def test_decode_prefers_longest_valid_code(table):
    """3 位码优先：@100 是「测」而不是 @10 前缀。"""
    assert gamecode.decode("[zh] @100@101") == "测试"
    assert gamecode.decode("[zh] @101") == "试"


def test_decode_keeps_unknown_at_tokens(table):
    """未命中的 @token 原样保留（避免把玩家名乱码化）。"""
    assert gamecode.decode("[zh] @IH @ZZZ") == "你 @ZZZ"
    assert gamecode.decode("hi @there") == "hi @there"


def test_decode_does_not_split_player_handle(table):
    """@Bob 这类玩家名不能被拆成「@BO(仿)+b」——编码器保证码后面必接空格/结束。"""
    # 造一个 @0A + 'b' 的歧义场景：0A 是有效码（八），但整段 0Ab 不是码
    assert gamecode.decode("[zh] @0Ab") == "@0Ab"
    assert gamecode.decode("[zh] @0A") == "八"
    assert gamecode.decode("Pyro 见 @Bob").endswith("@Bob")


def test_decode_strips_padding_around_fullwidth_punct(table):
    """全角标点两侧的填充空格去掉；用户自己打的中文空格保留。"""
    assert gamecode.decode(gamecode.encode("你，好")) == "你，好"
    assert gamecode.decode(gamecode.encode("你好 吗")) == "你好 吗"
    assert gamecode.decode(gamecode.encode("你 好")) == "你 好"


def test_decode_keeps_en_line(table):
    raw = "[zh] @IH@E8@AP\n[en] How are you"
    out = gamecode.decode(raw)
    assert out.startswith("你好吗")
    assert "[en] How are you" in out


def test_looks_encoded(table):
    assert gamecode.looks_encoded("[zh] @IH@E8@AP")
    assert gamecode.looks_encoded("@IH@E8@AP")
    assert gamecode.looks_encoded("@ZZZ@QQ") is False   # 无有效码
    assert gamecode.looks_encoded("hello there") is False


# ------------------------------------------------------------------ 码表解析
def test_parse_ini_block_only_reads_between_markers():
    ini = "\n".join(
        [
            "@ui_test=别的本地化键",
            "_starcitizen_doctor_localization_community_input_method_version=0.0.1",
            "IH=你",
            "E8=好",
            "_starcitizen_doctor_localization_version=4.2.0",
            "AP=吗",          # 块外，必须忽略
        ]
    )
    pairs, ver = gamecode.parse_ini_text(ini)
    assert pairs == {"IH": "你", "E8": "好"}
    assert ver == "0.0.1"
    assert "AP" not in pairs


def test_parse_ini_without_block_returns_empty():
    pairs, ver = gamecode.parse_ini_text("@a=b\nc=d\n")
    assert pairs == {} and ver == ""


def test_load_global_ini_reports_missing_block(tmp_path: Path):
    p = tmp_path / "global.ini"
    p.write_text("@ui_x=y\n", encoding="utf-8")
    with pytest.raises(gamecode.GameCodeError):
        gamecode.load_global_ini(p)


def test_load_global_ini_real_format(tmp_path: Path):
    p = tmp_path / "global.ini"
    p.write_text(
        "_starcitizen_doctor_localization_community_input_method_version=9.9.9\n"
        "IH=你\nE8=好\nAP=吗\n"
        "_starcitizen_doctor_localization_version=1\n",
        encoding="utf-8",
    )
    assert gamecode.load_global_ini(p) == 3
    assert gamecode.version() == "9.9.9"
    assert gamecode.encode("你好吗") == "[zh] @IH@E8@AP"
    gamecode.clear()


# ------------------------------------------------------------------ 自动检测
def test_autodetect_finds_ini_under_sc_layout(tmp_path: Path):
    """构造 <root>\\StarCitizen\\LIVE\\data\\Localization\\chinese_(simplified)\\global.ini。"""
    ini = (
        tmp_path
        / "games"
        / "StarCitizen"
        / "LIVE"
        / "data"
        / "Localization"
        / "chinese_(simplified)"
        / "global.ini"
    )
    ini.parent.mkdir(parents=True)
    ini.write_text(
        "_starcitizen_doctor_localization_community_input_method_version=1\nIH=你\n"
        "_starcitizen_doctor_localization_version=1\n",
        encoding="utf-8",
    )
    found = gamecode.find_global_inis([tmp_path])
    assert ini in found
    assert gamecode.autodetect([tmp_path]) == ini


def test_autodetect_skips_ini_without_block(tmp_path: Path):
    """没有码表块的 global.ini 不算数（避免选了没装社区输入法的汉化）。"""
    ini = (
        tmp_path
        / "StarCitizen"
        / "LIVE"
        / "data"
        / "Localization"
        / "chinese_(simplified)"
        / "global.ini"
    )
    ini.parent.mkdir(parents=True)
    ini.write_text("@ui_x=y\n", encoding="utf-8")
    assert gamecode.autodetect([tmp_path]) is None


def test_resolve_path_prefers_configured(tmp_path: Path, monkeypatch):
    ini = tmp_path / "global.ini"
    ini.write_text(
        "_starcitizen_doctor_localization_community_input_method_version=1\nIH=你\n"
        "_starcitizen_doctor_localization_version=1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SC_GAMECODE_INI", str(tmp_path / "nope.ini"))
    assert gamecode.resolve_path(str(ini)) == ini


# ------------------------------------------------------------------ 真实数据锚点
REAL_INI_CANDIDATES = [
    Path(r"D:\star citizen game\StarCitizen\LIVE\data\Localization\chinese_(simplified)\global.ini"),
    Path(r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\data\Localization\chinese_(simplified)\global.ini"),
]


@pytest.mark.parametrize("ini", REAL_INI_CANDIDATES)
def test_real_installed_hanhua_matches_example(ini: Path):
    """本机真实汉化数据：你好吗 -> [zh] @IH@E8@AP（不存在则跳过）。"""
    if not ini.is_file():
        pytest.skip(f"本机没有 {ini}")
    gamecode.load_global_ini(ini)
    try:
        assert gamecode.size() > 5000, "真实码表应有数千字"
        assert gamecode.encode("你好吗") == "[zh] @IH@E8@AP"
        assert gamecode.decode("[zh] @IH@E8@AP") == "你好吗"
        # 码表里每个码都能解回同一个字
        assert gamecode.decode(gamecode.encode("斯坦顿星系")) == "斯坦顿星系"
    finally:
        gamecode.clear()
