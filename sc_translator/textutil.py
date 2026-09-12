"""轻量文本工具（不依赖 numpy/cv2 等重型库，打包体积友好）。

原先 _cjk_ratio 放在 ocr.py 里，导致纯文字翻译路径间接依赖 OCR 全栈
（numpy / opencv / rapidocr）；现在抽到本模块，打包时可将 OCR 全部排除。
"""

from __future__ import annotations


def cjk_ratio(text: str) -> float:
    """汉字占比（0~1）。用于判断某段文字是否已经是中文。"""
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / len(text)
