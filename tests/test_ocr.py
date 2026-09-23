import numpy as np

from sc_translator.ocr import OcrEngine, OcrLine, cluster_lines, normalize_text


def _line(text, cy, cx=100, xleft=50, ytop=None, h=20, score=0.9):
    ytop = ytop if ytop is not None else cy - h // 2
    return OcrLine(text=text, cy=cy, cx=cx, xleft=xleft, ytop=ytop, height=h, score=score,
                   anchor_y=cy // 12, anchor_x=xleft // 20)


def test_normalize():
    assert normalize_text("  Hello   World  ") == "Hello World"
    assert normalize_text("ＡＢＣ") == "ABC"


def test_insert_word_spaces():
    from sc_translator.ocr import insert_word_spaces

    assert insert_word_spaces("NeedalifttoMicrotech?") == "Needaliftto Microtech?"
    assert insert_word_spaces("TradingatArea18") == "Tradingat Area 18"
    assert insert_word_spaces("Normal words") == "Normal words"


def test_wordninja_split_merged_lower():
    """词典分词：纯小写粘连长段应切出空格（全小写时 camelCase 帮不上）。"""
    from sc_translator.wordseg import split_merged_lower

    s = split_merged_lower("cansomeonelendmeasuperheavyarmorin")
    assert " " in s and "someone" in s and "armor" in s
    # 短于阈值的保持原样
    assert split_merged_lower("raggie") == "raggie"
    # 已是正常文本不受影响
    assert split_merged_lower("Trading at Area18") == "Trading at Area18"
    # 大小写混合（可能含名字/缩写）不拆
    assert split_merged_lower("NeedalifttoMicrotech?") == "NeedalifttoMicrotech?"


def test_cluster_splits_into_visual_lines_and_sorts():
    rows = [
        _line("word2", cy=20, xleft=150, cx=200),
        _line("word1", cy=20, xleft=20, cx=60),    # 同一行内按 x 排序拼接
        _line("second line", cy=60, xleft=30, cx=80),
        _line("second line", cy=60, xleft=30, cx=80),  # RapidOCR 式重复框应被去重
    ]
    out = cluster_lines(rows)
    assert len(out) == 2
    assert out[0].text == "word1 word2"
    assert out[1].text == "second line"
    assert out[0].cy < out[1].cy


def test_meaningless_filter_length():
    # 空/太短内容不构成有效行（有效行过滤现由 snapshot.filter_lines 负责，此处验证 normalizer 边界）
    assert normalize_text("") == ""


def test_low_contrast_enhancement_kicks_in():
    """低对比时增强被触发（标准差上升、不崩）；高对比不处理返回 None。"""
    from sc_translator.ocr import _enhance_low_contrast

    low = np.zeros((80, 240, 3), dtype=np.uint8)
    low[:] = (90, 90, 92)                 # 背景
    low[20:50, 20:200] = (102, 102, 104)  # 文字块（对比极低）
    out = _enhance_low_contrast(low)
    assert out is not None
    g = out[:, :, 0].astype(np.float32)
    assert float(np.abs(g - g.mean()).mean()) > 1.5
    # 高对比图不处理
    high = np.zeros((80, 240, 3), dtype=np.uint8)
    high[:] = (10, 10, 10)
    high[20:50, 20:200] = (230, 230, 230)
    assert _enhance_low_contrast(high) is None
