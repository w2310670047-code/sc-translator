import numpy as np

from sc_translator.patrol import ChangeDetector, diff_score, to_signature


def _frame(w=200, h=80, color=(40, 40, 40)):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def test_signature_shape_and_diff():
    a = to_signature(_frame())
    assert a.dtype == np.uint8
    assert a.shape[0] > 0
    # 相同图片差异为 0
    assert diff_score(to_signature(_frame()), to_signature(_frame())) == 0.0
    # 明显不同差异大
    b = _frame(color=(255, 255, 255))
    assert diff_score(to_signature(_frame()), to_signature(b)) > 0.3


def test_change_detector_detects_change_then_settles():
    d = ChangeDetector(min_fraction=0.01)
    assert d.update(to_signature(_frame())) is False  # 首帧无对比
    assert d.update(to_signature(_frame())) is False
    assert d.update(to_signature(_frame(color=(80, 80, 80)))) is True
    assert d.unchanged_frames() == 0
    assert d.update(to_signature(_frame(color=(80, 80, 80)))) is False
    assert d.unchanged_frames() == 1


def test_one_small_text_line_triggers():
    """新增一行小面积文字也应被判定为变化（强变化像素占比度量）。"""
    from PIL import Image, ImageDraw, ImageFont

    def render(lines):
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 22)
        img = Image.new("RGB", (760, 170), (15, 18, 24))
        d = ImageDraw.Draw(img)
        y = 10
        for ln in lines:
            d.text((14, y), ln, fill=(226, 232, 240), font=font)
            y += 40
        arr = np.asarray(img)[:, :, ::-1].copy()
        return to_signature(arr)

    det = ChangeDetector()
    a = render(["first line", "second line"])
    assert det.update(a) is False
    # 加入第三行（新增约 1/3 高度的局部变化）
    b = render(["first line", "second line", "third line here"])
    assert det.update(b) is True
