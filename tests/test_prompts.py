"""提示词文件加载器测试：目录加载、注释剔除、占位替换、缺文件回退。"""

from sc_translator import prompts


def _setup(tmp_path, files: dict[str, str]):
    pdir = tmp_path / "prompts_here"
    pdir.mkdir(exist_ok=True)
    for name, content in files.items():
        (pdir / name).write_text(content, encoding="utf-8")
    return pdir


def test_loads_from_dir_and_strips_comments(tmp_path, monkeypatch):
    pdir = _setup(tmp_path, {
        "translation_normal.md": (
            "<!-- 这是给人看的说明，不应发给模型 -->\n"
            "把{src}文本翻译成{target}。\n"
            "规则：只输出译文。"
        ),
    })
    monkeypatch.setenv("SC_PROMPTS_DIR", str(pdir))
    prompts.refresh()
    text = prompts.normal_prompt()
    assert "给人看的说明" not in text
    assert "把{src}文本翻译成{target}" in text
    assert prompts.fill(text, src="英文", target="简体中文") == "把英文文本翻译成简体中文。\n规则：只输出译文。"


def test_hash_lines_and_blank_compressed(tmp_path, monkeypatch):
    pdir = _setup(tmp_path, {
        "reply.md": "# 标题注释\n<!-- c -->\n你是回话翻译器。\n\n\n翻译成{target}。",
    })
    monkeypatch.setenv("SC_PROMPTS_DIR", str(pdir))
    prompts.refresh()
    text = prompts.reply_prompt()
    assert "标题注释" not in text
    assert "\n\n\n" not in text  # 多个连续空行被压缩为最多一个
    assert prompts.fill(text, target="English").endswith("翻译成English。")


def test_falls_back_to_builtin_defaults(tmp_path, monkeypatch):
    empty = tmp_path / "empty_prompts"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("SC_PROMPTS_DIR", str(empty))
    prompts.refresh()
    normal = prompts.normal_prompt()
    spicy = prompts.spicy_prompt()
    reply = prompts.reply_prompt()
    assert "本地化翻译引擎" in normal
    assert "嘴臭" in spicy and "垃圾话" in spicy
    assert "回话" in reply or "聊天翻译器" in reply
