from sc_translator.ocr import OcrLine
from sc_translator.pipeline import Pipeline, PipelineSettings


def _ocr_line(text, cy, x=100, h=22):
    return OcrLine(text=text, cy=cy, cx=x, xleft=x - 50, ytop=cy - h // 2, height=h,
                   score=0.95, anchor_y=cy // 12, anchor_x=(x - 50) // 20)


def _settings(stable=2):
    return PipelineSettings(stable_frames=stable, max_text_chars=800)


def test_new_text_needs_stable_frames_then_pending():
    p = Pipeline(_settings(stable=2))
    p.feed([_ocr_line("Welcome back, Citizen", cy=20)])
    assert p.visible_entries() == []          # 第一帧不稳定
    p.feed([_ocr_line("Welcome back, Citizen", cy=20)])
    ents = p.visible_entries()
    assert len(ents) == 1
    assert ents[0].pending is True            # 等待译文


def test_translation_applied_and_snapshot():
    p = Pipeline(_settings())
    line = _ocr_line("Quantum travel engaged", cy=30)
    p.feed([line])
    p.feed([line])
    assert p.pending_texts() == ["Quantum travel engaged"]
    assert p.apply_translation("Quantum travel engaged", "量子跃迁已启动")
    snap = p.snapshot()
    assert snap[0]["translated"] == "量子跃迁已启动"
    assert snap[0]["pending"] is False
    # 同文不重复翻译
    assert p.pending_texts() == []


def test_scrolled_out_line_removed_after_drop_frames():
    from sc_translator.pipeline import DEFAULT_DROP_ABSENT
    p = Pipeline(_settings())
    l1 = _ocr_line("First line", cy=20)
    p.feed([l1])
    p.feed([l1])
    p.apply_translation("First line", "第一行")
    # 模拟滚动：行 1 消失，行 2 出现
    l2 = _ocr_line("Second line", cy=80)
    p.feed([l2])
    p.feed([l2])
    p.feed([l2])
    assert p.pending_texts() == ["Second line"]
    keys = [e.key for e in p.visible_entries()]
    assert any(k.startswith("A") for k in keys)   # 第二行在
    # 继续缺帧直到第一行被移除（第一行已提交但不再出现）
    for _ in range(DEFAULT_DROP_ABSENT):
        p.feed([_ocr_line("Second line", cy=80)])
    texts = [e.text for e in p.visible_entries()]
    assert texts == ["Second line"]


def test_in_place_update_no_duplicate_key():
    p = Pipeline(_settings())
    a = _ocr_line("Health 100", cy=20)
    b = _ocr_line("Health 80", cy=20)   # 同锚点内容更新
    p.feed([a]); p.feed([a])
    p.feed([b]); p.feed([b])
    ents = p.visible_entries()
    assert len(ents) == 1
    assert ents[0].text == "Health 80"


def test_order_is_top_to_bottom():
    p = Pipeline(_settings())
    p.feed([_ocr_line("bottom", cy=120), _ocr_line("top", cy=10)])
    p.feed([_ocr_line("bottom", cy=120), _ocr_line("top", cy=10)])
    texts = [e.text for e in p.visible_entries()]
    assert texts == ["top", "bottom"]


def test_ignores_garbage_lines():
    p = Pipeline(_settings())
    from sc_translator.pipeline import _meaningful
    assert not _meaningful("-")
    assert not _meaningful("..")
    assert _meaningful("o7 commander")


def test_repeated_sentence_uses_memory_not_requeue():
    """相同句子再次出现（滚动后重现/两人同句）直接复用，不再进入待译。"""
    p = Pipeline(_settings())
    a = _ocr_line("Need a lift?", cy=20)
    p.feed([a]); p.feed([a])
    norm = p.pending_texts()[0]
    p.apply_translation(norm, "需要搭车吗？")
    # 模拟该行滚出区域后彻底移除
    for _ in range(4):
        p.feed([])
    assert p.visible_entries() == []
    # 同句在新位置再次出现
    b = _ocr_line("Need a lift?", cy=140)
    p.feed([b]); p.feed([b])
    ents = p.visible_entries()
    assert len(ents) == 1
    assert ents[0].translated == "需要搭车吗？"   # 直接复用旧译文
    assert ents[0].pending is False
    assert p.pending_texts() == []                # 不会重复请求


def test_ocr_jitter_variants_translated_once():
    """OCR 抖动变体(won'thave/won't have)不应触发重复翻译请求。"""
    p = Pipeline(_settings())
    a = _ocr_line("[Global](Viserion): I won'thave to pay to claim", cy=20)
    b = _ocr_line("[Global](Viserion): I won't have to pay to claim", cy=20)  # 同锚点近似变体
    p.feed([a])             # stable=1
    p.feed([b])             # 近似变体：stable=2 -> 提交一次
    pending = p.pending_texts()
    assert len(pending) == 1, pending
    norm = pending[0]
    p.apply_translation(norm, "我不用付费就能索赔")
    # 再来几个变体：不再产生新的待译
    for _ in range(3):
        p.feed([b])
    assert p.pending_texts() == []
    assert p.visible_entries()[0].translated == "我不用付费就能索赔"


def test_similar_sentence_elsewhere_reuses_translation():
    """近似文本（换行/OCR 差异导致的新行）不再重复请求，直接复用已译句。"""
    p = Pipeline(_settings())
    a = _ocr_line("[Global](Viserion): I won'thave to pay to claim insurance", cy=20)
    p.feed([a]); p.feed([a])
    norm = p.pending_texts()[0]
    p.apply_translation(norm, "我不必付费索赔保险")
    # 换行/变体导致出现在不同锚点的近似句
    b = _ocr_line("[Global](Viserion): I won't have to pay to claim insurance", cy=140)
    p.feed([b]); p.feed([b])
    ents = p.visible_entries()
    assert ents[1].translated == "我不必付费索赔保险"
    assert ents[1].pending is False
    assert p.pending_texts() == []   # 不会重复请求


def test_unchanged_line_never_requeues():
    """完全不变、已翻译的行反复出现（同帧/滚动重现）绝不产生新请求。"""
    p = Pipeline(_settings())
    a = _ocr_line("[全局]Odom: its a workaround simulator", cy=20)
    p.feed([a]); p.feed([a])
    norm = p.pending_texts()[0]
    p.apply_translation(norm, "这是个变通模拟器")
    # 再连续喂几十次一模一样的帧
    for _ in range(30):
        p.feed([a])
    assert p.pending_texts() == []
    assert p.visible_entries()[0].translated == "这是个变通模拟器"
    # 滚出再重现也不重复
    for _ in range(5):
        p.feed([])
    p.feed([a]); p.feed([a])
    assert p.pending_texts() == []
    assert p.visible_entries()[-1].translated == "这是个变通模拟器"


def test_chat_mode_filters_non_player_lines():
    from sc_translator.pipeline import PipelineSettings

    ps = PipelineSettings(stable_frames=2, chat_mode=True,
                          chat_pattern=r"\[[^\]\n]{0,24}\]\s*\([^()\n]{1,48}\)\s*[:：]\s*.+")
    p = Pipeline(ps)
    chat = _ocr_line("[Global](Viserion): hello everyone", cy=20)
    noise = _ocr_line("Welcome to Star Citizen, enjoy the verse", cy=150)  # 远距独立系统行
    p.feed([chat, noise]); p.feed([chat, noise])
    texts = [e.text for e in p.visible_entries()]
    assert texts == ["[Global](Viserion): hello everyone"]
    assert "Welcome to Star Citizen" not in " ".join(texts)


def test_name_on_separate_row_reassembles_body():
    """SC 常见布局：'[全局]名字:' 单独一行、正文在下一行——应并入同一条消息。"""
    from sc_translator.pipeline import PipelineSettings
    from sc_translator.settings import DEFAULT_CHAT_PATTERN

    ps = PipelineSettings(stable_frames=2, chat_mode=True, chat_pattern=DEFAULT_CHAT_PATTERN)
    p = Pipeline(ps)
    name = _ocr_line("[全局]Thomasu:", cy=20)
    body1 = _ocr_line("playing for 2 hours and 0 progress because of", cy=46)
    body2 = _ocr_line("disconnects D time well spent", cy=72)
    nxt = _ocr_line("[全局]Odom: its a workaround simulator", cy=110)
    p.feed([body2, name, nxt, body1])
    p.feed([body2, name, nxt, body1])
    texts = [e.text for e in p.visible_entries()]
    assert len(texts) == 2, texts
    assert texts[0].startswith("[全局]Thomasu:")
    assert "playing for 2 hours and 0 progress because of" in texts[0]
    assert "disconnects D time well spent" in texts[0]
    assert texts[1].startswith("[全局]Odom:")
    # 只有名字没有正文的行不会残留
    assert not any(t.strip().endswith(":") and len(t) < 24 for t in texts)


def test_wrapped_message_reassembled():
    """自动换行的长消息：续行并入同一消息再翻译，不再逐行拆散。"""
    from sc_translator.pipeline import PipelineSettings

    ps = PipelineSettings(stable_frames=2, chat_mode=True,
                          chat_pattern=r"\[[^\]\n]{0,24}\]\s*\([^()\n]{1,48}\)\s*[:：]\s*.+")
    p = Pipeline(ps)
    l1 = _ocr_line("[Global](Viserion): does anyone have a spare", cy=20)
    l2 = _ocr_line("quantum drive for my ship?", cy=46)   # 同一消息的折行
    l3 = _ocr_line("[Global](DeepFlier): I have one", cy=90)  # 下一条消息
    p.feed([l1, l2, l3])
    p.feed([l1, l2, l3])
    texts = [e.text for e in p.visible_entries()]
    assert len(texts) == 2, texts
    assert "does anyone have a spare quantum drive for my ship?" in texts[0]
    assert texts[1].endswith("I have one")
    # 拆行文本不会单独进入待译队列
    pending = p.pending_texts()
    assert not any("quantum drive for my ship?" == t for t in pending)
