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


# ---------------------------------------------------------------- 提速（第 21 轮）
def test_default_params_use_smaller_det_limit_and_single_thread():
    """默认检测尺寸 512（而非 RapidOCR 的 736）：默认会把短边放大到 736，实测多花 ~40%。"""
    from sc_translator.ocr import DET_LIMIT_SIDE_LEN

    kw = OcrEngine()._kwargs
    assert DET_LIMIT_SIDE_LEN == 512
    assert kw["det_limit_side_len"] == 512
    assert kw["intra_op_num_threads"] == 1, "单线程省 CPU 是刻意选择，别被顺手改掉"


def test_same_frame_skips_ocr_engine():
    """同一帧连续按热键时直接复用上次结果（哈希 ~0.2ms vs OCR 400ms+）。"""
    calls: list[tuple] = []

    class _Engine:
        def __call__(self, img):
            calls.append(img.shape)
            box = [[0, 0], [200, 0], [200, 20], [0, 20]]
            return ([[box, "Quantum travel to Crusader", 0.99]], 0.01)

    eng = OcrEngine()
    eng._engine = _Engine()
    img = np.full((60, 320, 3), 20, dtype=np.uint8)
    first = eng.recognize(img)
    second = eng.recognize(img.copy())            # 像素完全相同 = 同一画面
    assert [r.text for r in first] == ["Quantum travel to Crusader"], first
    assert [r.text for r in second] == [r.text for r in first]
    assert len(calls) == 1, f"同帧不该再跑引擎：{calls}"

    changed = img.copy()
    changed[0, 0] = (255, 0, 0)                   # 画面变了必须重新识别
    eng.recognize(changed)
    assert len(calls) == 2, calls
