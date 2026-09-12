"""本地 OCR：RapidOCR（PaddleOCR onnx 模型，中英为主）。

输出为按“视觉行”聚类的文本行；每行给出用于跨帧匹配的锚点
（量化后的 y 中心 / x 左缘），供管线做行级稳定确认。
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class OcrLine:
    text: str
    cy: int          # 行中心 y（像素，区域坐标系）
    cx: int          # 行中心 x
    xleft: int
    ytop: int
    height: int
    score: float
    anchor_y: int    # 量化锚点，跨帧匹配用
    anchor_x: int

    def normalized(self) -> str:
        return normalize_text(self.text)


def normalize_text(text: str) -> str:
    """NFKC + 折叠空白，用于去重/比对。"""
    t = unicodedata.normalize("NFKC", text)
    return " ".join(t.split())


def insert_word_spaces(text: str) -> str:
    """RapidOCR 常把整行输出为无空格的一整块，这里做轻量分词：
    在 camelCase 边界、字母-数字边界补空格，便于翻译模型理解。"""
    if not text:
        return text
    s = text
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)     # NeedalifttoMicrotech -> Needaliftto Microtech
    s = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", s)     # Area18 -> Area 18
    s = re.sub(r"(?<=\d)(?=[A-Za-z])", " ", s)     # 18Area -> 18 Area
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _cjk_ratio(text: str) -> float:
    # 保留旧名以保证向后兼容；实现已移到 textutil（纯文字路径不再依赖 OCR 栈）
    from .textutil import cjk_ratio

    return cjk_ratio(text)


def _enhance_low_contrast(bgr: np.ndarray, std_threshold: float = 38.0):
    """低对比图增强：文字与背景颜色相近时，先 CLAHE+线性拉伸再识别。

    返回增强后的 BGR（或 None=对比度足够，不处理，省 CPU）。
    """
    if bgr is None or bgr.size == 0:
        return None
    try:
        import cv2

        small = cv2.resize(bgr, (0, 0), fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if float(gray.std()) >= std_threshold:
            return None  # 对比度足够
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l_ch, a_ch, b_ch = cv2.split(lab)
        l_ch = cv2.normalize(l_ch, None, 0, 255, cv2.NORM_MINMAX)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_ch = clahe.apply(l_ch)
        out = cv2.merge([l_ch, a_ch, b_ch])
        return cv2.cvtColor(out, cv2.COLOR_LAB2BGR)
    except Exception:  # noqa: BLE001
        return None


class OcrEngine:
    """RapidOCR 封装。实例在采样线程内创建、复用。

    实测（471×268、6 行英文）：onnxruntime 线程数对 CPU 影响巨大——
    intra=2 时单次识别烧 ~1.8 秒 CPU（≈3.4 核），intra=1 时仅 ~0.75 秒（≈1 核）。
    为保证整体占用低，默认固定单线程推理；代价是单次识别 wall 时间约 0.5~0.9 秒，
    配合 3 秒更新间隔平均占用约 25% 单核。
    """

    def __init__(self, **kwargs) -> None:
        self._engine = None
        kwargs.setdefault("intra_op_num_threads", 1)   # 关键：限制推理线程，CPU 大头
        kwargs.setdefault("inter_op_num_threads", 1)
        self._kwargs = kwargs

    def _ensure(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            log.info("初始化 RapidOCR（首次加载模型需数秒）...")
            self._engine = RapidOCR(**self._kwargs)
            log.info("RapidOCR 就绪")
        return self._engine

    def recognize(self, bgr: np.ndarray) -> list[OcrLine]:
        """BGR ndarray -> 按视觉行排序的 OcrLine 列表（空区域返回 []）。"""
        if bgr is None or bgr.size == 0:
            return []
        eng = self._ensure()
        enhanced = _enhance_low_contrast(bgr)
        if enhanced is not None:
            bgr = enhanced
        try:
            raw = eng(bgr)
        except Exception as exc:  # noqa: BLE001
            log.warning("OCR 调用失败: %s", exc)
            return []
        if not raw:
            return []
        # rapidocr-onnxruntime 返回 (result, elapse) 或新版直接 result
        result = raw[0] if isinstance(raw, (tuple, list)) and len(raw) == 2 and isinstance(raw[0], list) else raw
        rows: list[OcrLine] = []
        if result is None:
            return []
        for entry in result:
            try:
                if len(entry) >= 3:
                    box, text, score = entry[0], str(entry[1]), float(entry[2])
                elif len(entry) == 2:
                    box, text, score = entry[0], str(entry[1]), 1.0
                else:
                    continue
                pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
                if pts.shape[0] < 4:
                    continue
                xs, ys = pts[:, 0], pts[:, 1]
                top, bottom = float(ys.min()), float(ys.max())
                left, right = float(xs.min()), float(xs.max())
                text = normalize_text(text)
                if not text or len(text) > 400 or score < 0.35:
                    continue
                # 先词典分词（切粘连小写长段，无论该检测块内是否已有空格）
                from .wordseg import split_merged_lower

                text = normalize_text(split_merged_lower(text))
                if " " not in text and len(text) >= 8:
                    # 纯粘连块再补 camelCase/数字边界空格
                    text = normalize_text(insert_word_spaces(text))
                cx = int(round((left + right) / 2))
                cy = int(round((top + bottom) / 2))
                rows.append(
                    OcrLine(
                        text=text,
                        cy=cy,
                        cx=cx,
                        xleft=int(round(left)),
                        ytop=int(round(top)),
                        height=max(2, int(round(bottom - top))),
                        score=score,
                        anchor_y=int(round(cy / 12.0)),
                        anchor_x=int(round(left / 20.0)),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("OCR 行解析跳过: %s", exc)
        return cluster_lines(rows)


def cluster_lines(rows: list[OcrLine]) -> list[OcrLine]:
    """把检测框合并成视觉行（处理 RapidOCR 把一个词拆成多个框的情况），按上到下排序。"""
    if not rows:
        return []
    items = sorted(rows, key=lambda r: (r.cy, r.cx))
    clusters: list[list[OcrLine]] = []
    for r in items:
        if not clusters:
            clusters.append([r])
            continue
        last = clusters[-1]
        ref_top = min(x.ytop for x in last)
        ref_bot = max(x.ytop + x.height for x in last)
        # 竖直重叠判定
        overlap = min(ref_bot, r.ytop + r.height) - max(ref_top, r.ytop)
        vmin = min(ref_bot - ref_top, r.height)
        if vmin > 0 and overlap / vmin >= 0.35:
            # 同一位置的重复检测框直接跳过
            if any(x.text == r.text and abs(x.cy - r.cy) < 8 and abs(x.xleft - r.xleft) < 12 for x in last):
                continue
            last.append(r)
        else:
            clusters.append([r])
    out: list[OcrLine] = []
    for cl in clusters:
        cl = sorted(cl, key=lambda r: r.cx)
        text = " ".join(x.text for x in cl)
        text = normalize_text(text)
        if not text:
            continue
        top = min(x.ytop for x in cl)
        bottom = max(x.ytop + x.height for x in cl)
        left = min(x.xleft for x in cl)
        right = max(x.xleft + len(x.text) * 9 for x in cl)  # 粗略右缘（仅排序用）
        height = max(2, bottom - top)
        cy = (top + bottom) // 2
        out.append(
            OcrLine(
                text=text,
                cy=cy,
                cx=(left + right) // 2,
                xleft=left,
                ytop=top,
                height=height,
                score=min(1.0, max(x.score for x in cl)),
                anchor_y=int(round(cy / 12.0)),
                anchor_x=int(round(left / 20.0)),
            )
        )
    # 删除竖直重叠的近似重复检测
    out.sort(key=lambda r: (r.cy, r.cx))
    deduped: list[OcrLine] = []
    for r in out:
        dup = False
        for d in deduped:
            if abs(d.cy - r.cy) < 8 and abs(d.cx - r.cx) < 40 and d.normalized() == r.normalized():
                dup = True
                break
        if not dup:
            deduped.append(r)
    return deduped
