"""采样管线（线程内运行，不依赖 Qt，便于单测）。

流程：
  region 截图 -> 像素签名 diff 巡逻
      -> 变化或定时巡检时跑 OCR
      -> 行稳定确认（连续 N 帧一致才提交，吸收 OCR 抖动）
      -> 内容变化的行进入翻译队列（同文合并、缓存命中直接回填）
      -> 输出“有序快照”给悬浮框
      -> 消失的行延迟移除

嘴臭模式不在本模块处理：它只是一个设置开关，翻译客户端按开关选择
“正常提示词 / 嘴臭提示词”两套之一（每次请求按当时设置生效）。
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from .ocr import OcrLine, normalize_text
from .patrol import ChangeDetector, to_signature

log = logging.getLogger(__name__)

DEFAULT_DROP_ABSENT = 3   # 连续缺帧达到该值才移除该行
MIN_ALNUM = 1             # 行文本至少要包含的字母/数字/CJK 数

# SC 常见布局：“[频道]玩家:” 或 “[频道](玩家):” 单独一行（正文在下一行）的名字头
_NAME_ONLY_RE = re.compile(
    r"^\s*(?:\[[^\]\n]{0,24}\]\s*)?(?:\([^()\n]{1,48}\)|[^:：()\n]{1,64})\s*[:：]\s*$"
)


@dataclass
class LiveEntry:
    """悬浮框中的一个可见行。key 稳定；text 变化视为同一行内容更新。"""
    key: str
    text: str
    translated: str = ""
    pending: bool = False

    def to_dict(self) -> dict:
        return {"key": self.key, "text": self.text, "translated": self.translated, "pending": self.pending}


@dataclass
class PipelineSettings:
    sample_ms: int = 220
    stable_frames: int = 2
    max_text_chars: int = 800
    source_lang: str = "auto"
    target_lang: str = "zh-CN"
    ocr_interval_s: float = 1.5   # 活跃间隔：最近有文字时两次 OCR 最小间隔(秒)，跟手
    ocr_idle_s: float = 5.0       # 空闲退避：连续无文字时两次 OCR 最小间隔(秒)，省 CPU
    text_gate: bool = True        # 文本存在预判门：明显无字形的变化不跑 OCR
    idle_sample_s: float = 1.5    # 静止无事件时的巡检间隔(秒)
    chat_mode: bool = False       # SC聊天模式：只翻译形如 [频道](玩家):正文 的玩家消息
    chat_pattern: str = ""        # 聊天行匹配正则（chat_mode=True 时生效）


@dataclass
class Callbacks:
    on_snapshot: Callable[[list[dict]], None]
    on_status: Callable[[dict], None] = lambda s: None
    on_error: Callable[[str], None] = lambda s: None


class _EntryState:
    __slots__ = ("key", "text", "display_text", "translated", "pending", "stable", "absent", "committed")

    def __init__(self, key: str, text: str):
        self.key = key
        self.text = text          # 最近一次观察到的文本
        self.display_text = ""    # 已提交展示的文本
        self.translated = ""
        self.pending = False
        self.stable = 0
        self.absent = 0
        self.committed = False    # 是否已进入展示列表


def _meaningful(text: str) -> bool:
    t = normalize_text(text)
    if len(t) < 2 or len(t) > 4000:
        return False
    return sum(1 for ch in t if ch.isalnum()) >= MIN_ALNUM


def _similar(a: str, b: str) -> bool:
    """判定两条归一化文本是否只是 OCR 抖动的近似重复（如 won'thave / won't have）。

    仅对较长的拉丁文本做相似度比较，避免把真正的改动当成抖动。
    """
    if a == b:
        return True
    if not a or not b or len(a) < 6 or len(b) < 6:
        return False
    if abs(len(a) - len(b)) > max(4, len(a) // 5):
        return False
    try:
        import difflib

        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.88
    except Exception:  # noqa: BLE001
        return False


class Pipeline:
    """OCR 帧状态机：帧 -> 稳定提交 -> 快照。不含截图/OCR/翻译。

    chat_mode=True 时只放行匹配 “[频道](玩家):正文” 的行（过滤系统/UI 噪音）。
    """

    def __init__(self, settings: PipelineSettings):
        self.s = settings
        self._view: dict[str, _EntryState] = {}
        self._order: list[str] = []
        self.dirty = False
        self._chat_re = None
        # 会话内“已翻译句”记忆：相同句子再次出现直接复用，不重复请求 API（含滚动后重现）
        self._known: dict[str, str] = {}
        self._known_order: list[str] = []
        self._known_cap = 300
        if settings.chat_pattern:
            try:
                import re as _re

                self._chat_re = _re.compile(settings.chat_pattern)
            except Exception as exc:  # noqa: BLE001
                log.warning("聊天行正则无效: %s", exc)
                self._chat_re = None

    # ---------------- 会话内句子记忆（含近似复用） ----------------
    def memorize(self, norm_text: str, translated: str) -> None:
        if not norm_text or not translated:
            return
        if norm_text not in self._known:
            self._known_order.append(norm_text)
        self._known[norm_text] = translated
        if len(self._known_order) > self._known_cap:
            old = self._known_order.pop(0)
            self._known.pop(old, None)

    def known_translation(self, norm_text: str) -> Optional[str]:
        """精确或近似匹配已译句子（OCR 抖动/换行差异也复用，不再重复请求）。"""
        exact = self._known.get(norm_text)
        if exact is not None:
            return exact
        if not norm_text or len(norm_text) < 8:
            return None
        best: Optional[str] = None
        best_key = None
        for key in self._known_order:
            if abs(len(key) - len(norm_text)) > max(6, len(norm_text) // 4):
                continue
            if _similar(key, norm_text):
                best = self._known.get(key)
                best_key = key
                break
        if best is not None and best_key is not None:
            # 记录别名，下次秒命中
            self.memorize(norm_text, best)
            return best
        return None

    def apply_translation_similar(self, norm_text: str, translated: str) -> bool:
        """回填时也按近似匹配，避免 OCR 变体把条目卡在“翻译中”。"""
        changed = False
        if not translated:
            return changed
        self.memorize(norm_text, translated)
        for st in self.visible_entries():
            if not st.pending:
                continue
            dn = normalize_text(st.display_text)
            if dn == norm_text or (len(dn) >= 8 and len(norm_text) >= 8 and _similar(dn, norm_text)):
                st.translated = translated
                st.pending = False
                self.memorize(dn, translated)
                changed = True
        if changed:
            self.dirty = True
        return changed

    def _is_start(self, norm: str) -> bool:
        """消息开头：正文同行 或 名字:单独成行（正文在后续行）。"""
        if self._chat_re is None:
            return False
        try:
            if self._chat_re.match(norm):
                return True
            return _NAME_ONLY_RE.match(norm) is not None
        except Exception:  # noqa: BLE001
            return False

    def _is_name_only(self, norm: str) -> bool:
        try:
            return _NAME_ONLY_RE.match(norm) is not None
        except Exception:  # noqa: BLE001
            return False

    def _merge_wrapped(self, lines: list[OcrLine]) -> list[OcrLine]:
        """重组消息块（处理自动换行 + “名字:”单独一行 + 正文在下一行的 SC 布局）：
        - “名字:正文”同行开头：其后的紧贴折行并入
        - “名字:”（无正文）开头：其后的紧贴行作为正文并入
        直到下一条消息头或纵向间距过大(>48px)才结束。
        """
        if not lines or self._chat_re is None:
            return lines
        ordered = sorted(lines, key=lambda r: (r.cy, r.cx))
        out: list[OcrLine] = []
        carry: Optional[OcrLine] = None
        carry_last_cy = -10**9
        for ln in ordered:
            norm = ln.normalized()
            if self._is_start(norm):
                if carry is not None:
                    out.append(carry)
                    carry = None
                carry = ln
                carry_last_cy = ln.cy
            elif carry is not None and (ln.cy - carry_last_cy) <= 48:
                # 续行：并入消息正文（与上一条并入行的间距 ≤2 行高）
                carry = OcrLine(
                    text=f"{carry.text} {ln.text}",
                    cy=carry.cy,
                    cx=carry.cx,
                    xleft=carry.xleft,
                    ytop=carry.ytop,
                    height=max(carry.height, (ln.ytop + ln.height) - carry.ytop),
                    score=min(carry.score, ln.score),
                    anchor_y=carry.anchor_y,
                    anchor_x=carry.anchor_x,
                )
                carry_last_cy = ln.cy
            else:
                if carry is not None:
                    out.append(carry)
                    carry = None
                out.append(ln)
        if carry is not None:
            out.append(carry)
        # “名字:”后没有正文的空行不会有意义，交给上层过滤
        return out

    # ---------------- 帧处理 ----------------
    def feed(self, lines: list[OcrLine]) -> None:
        lines = [l for l in lines if _meaningful(l.text) and len(l.normalized()) <= self.s.max_text_chars]
        lines = self._merge_wrapped(lines)
        if self.s.chat_mode and self._chat_re is not None:
            # 只保留“名字:正文”同行的完整消息（重组后无正文的名字行会被丢弃）
            lines = [l for l in lines if self._chat_re.match(l.normalized())]
        seen: set[str] = set()

        for line in lines:
            text = line.normalized()
            key = self._find_existing(line, seen)
            if key is None:
                key = self._new_key(line)
                self._view[key] = _EntryState(key, text)
                self._insert_ordered(key, line.anchor_y)
            st = self._view[key]
            seen.add(key)
            if st.text == text:
                st.stable += 1
                st.absent = 0
            elif _similar(st.text, text):
                # OCR 抖动变体：视为同一句，继续累计确认，不重置、不重复请求
                st.absent = 0
                st.stable += 1
            else:
                st.text = text
                st.stable = 1
                st.absent = 0

        to_remove: list[str] = []
        for key, st in self._view.items():
            if key not in seen:
                st.absent += 1
                if st.absent >= DEFAULT_DROP_ABSENT:
                    to_remove.append(key)
        for key in to_remove:
            self._remove(key)
        self._commit_stable()

    def _new_key(self, line: OcrLine) -> str:
        base = f"A{line.anchor_y}x{line.anchor_x}"
        if base not in self._view:
            return base
        n = 0
        while f"{base}#{n}" in self._view:
            n += 1
        return f"{base}#{n}"

    def _find_existing(self, line: OcrLine, used: set[str]) -> Optional[str]:
        """锚点邻近或文本相等匹配，容忍轻微 OCR 抖动。"""
        text = line.normalized()
        exact_text_key = None
        best_key = None
        for key, st in self._view.items():
            if key in used or st.absent >= DEFAULT_DROP_ABSENT:
                continue
            ay = self._anchor_of(key)[0]
            if abs(ay - line.anchor_y) <= 2:
                if st.text == text:
                    return key
                if best_key is None and abs(self._anchor_of(key)[1] - line.anchor_x) <= 1:
                    best_key = key
            elif st.text == text and exact_text_key is None:
                exact_text_key = key
        return best_key or exact_text_key

    def _insert_ordered(self, key: str, anchor_y: int) -> None:
        pos = len(self._order)
        for i, k in enumerate(self._order):
            if self._anchor_of(k)[0] > anchor_y:
                pos = i
                break
        self._order.insert(pos, key)

    @staticmethod
    def _anchor_of(key: str) -> tuple[int, int]:
        try:
            tag = key.split("#")[0][1:]
            y, x = tag.split("x")
            return int(y), int(x)
        except Exception:
            return 0, 0

    def _remove(self, key: str) -> None:
        self._view.pop(key, None)
        if key in self._order:
            self._order.remove(key)
        self.dirty = True

    def _commit_stable(self) -> None:
        # 聊天模式用单帧提交：新消息一出现就立刻处理，不等第二帧确认（滚动太快等不起）
        need = 1 if self.s.chat_mode else self.s.stable_frames
        for key in list(self._order):
            st = self._view.get(key)
            if st is None:
                continue
            if st.stable >= need and st.committed and st.text != st.display_text:
                st.display_text = st.text
                # 相同句子之前已翻译过 -> 直接复用，不再请求
                known = self.known_translation(normalize_text(st.display_text))
                st.translated = known or ""
                st.pending = known is None
                self.dirty = True
            elif st.stable >= need and not st.committed:
                st.committed = True
                st.display_text = st.text
                known = self.known_translation(normalize_text(st.display_text))
                st.translated = known or ""
                st.pending = known is None
                self.dirty = True
            if not st.committed and st.absent >= DEFAULT_DROP_ABSENT:
                self._remove(key)

    # ---------------- 输出 ----------------
    def visible_entries(self) -> list[_EntryState]:
        return [self._view[k] for k in self._order if k in self._view and self._view[k].committed]

    def snapshot(self) -> list[dict]:
        return [LiveEntry(e.key, e.display_text, e.translated, e.pending).to_dict() for e in self.visible_entries()]

    def apply_translation(self, norm_text: str, translated: str) -> bool:
        return self.apply_translation_similar(norm_text, translated)

    def apply_translation_failed(self, norm_text: str) -> bool:
        """翻译失败：终止 pending，用占位文案提示（真实原因见日志/主窗口）。"""
        changed = False
        for st in self.visible_entries():
            if st.pending and normalize_text(st.display_text) == norm_text:
                st.translated = "（翻译失败：无译文，详见日志）"
                st.pending = False
                changed = True
        if changed:
            self.dirty = True
        return changed

    def pending_texts(self) -> list[str]:
        seen: set[str] = set()
        out = []
        for st in self.visible_entries():
            if st.pending:
                n = normalize_text(st.display_text)
                if n not in seen:
                    seen.add(n)
                    out.append(n)
        return out

    def take_dirty(self) -> bool:
        d = self.dirty
        self.dirty = False
        return d

    def clear(self) -> None:
        self._view.clear()
        self._order.clear()
        self.dirty = True


# ======================================================================
# ======================================================================
# 线程（两档调度 + 文本门 + 批量翻译请求）
# ======================================================================

class SamplingThread(threading.Thread):
    """采样线程。

    调度（仿 ow-translate-lite 的两档节奏）：
    - 最近有文字(had_rows)或有待确认帧(confirm_left) -> “活跃”档，OCR 最短间隔 ps.ocr_interval_s
    - 连续无文字 -> “空闲退避”档，OCR 最短间隔 ps.ocr_idle_s
    - 文本存在预判门(ps.text_gate)：明显没有字形像素的变化不跑 OCR
    """

    def __init__(
        self,
        ps: PipelineSettings,
        phys_rect: dict,
        capture,
        ocr_engine: object,
        request_translation_batch: Callable[[list[str]], None],
        results: "queue.Queue[tuple[str, Optional[str]]]",
        callbacks: Callbacks,
    ) -> None:
        super().__init__(name="SamplingThread", daemon=True)
        self.ps = ps
        self.phys_rect = dict(phys_rect)
        self._capture = capture
        self._ocr = ocr_engine
        self._request_batch = request_translation_batch
        self._results = results
        self.cb = callbacks
        self._stop_ev = threading.Event()
        self.pipeline = Pipeline(ps)
        self._counters = {"ocr": 0, "translate_req": 0, "translate_done": 0, "rows": 0, "snapshots": 0}

    def stop(self) -> None:
        self._stop_ev.set()

    @staticmethod
    def _text_fraction(sig: np.ndarray) -> float:
        """签名灰图中“类字形”像素占比：明显亮(>170)或明显暗(<70)。"""
        if sig is None or sig.size == 0:
            return 0.0
        return float(((sig > 170) | (sig < 70)).mean())

    def run(self) -> None:
        ps = self.ps
        log.info("采样线程启动 区域=%s 活跃间隔=%.1fs 空闲退避=%.1fs",
                 self.phys_rect, ps.ocr_interval_s, ps.ocr_idle_s)
        detector = ChangeDetector()
        last_ocr = -1.0
        last_status = 0.0
        confirm_left = 0       # 变化后还需补跑的确认次数（保证同文两帧稳定）
        had_rows = False       # 最近一次 OCR 是否见到文字（决定活跃/空闲档）
        empty_run = 0
        gap_active = max(0.4, ps.ocr_interval_s)
        gap_idle = max(2.0, ps.ocr_idle_s)
        try:
            while not self._stop_ev.is_set():
                self._drain_results()

                frame = self._capture.grab(self.phys_rect)
                if frame is None:
                    time.sleep(0.3)
                    continue
                sig = to_signature(frame)
                changed = detector.update(sig)
                now = time.monotonic()
                if changed:
                    confirm_left = 2

                # ---- 是否跑本轮 OCR ----
                cur_gap = gap_active if (had_rows or confirm_left > 0) else gap_idle
                do_ocr = False
                if last_ocr < 0:
                    do_ocr = True                      # 启动先识别一次
                elif changed and now - last_ocr >= 0.25:
                    # 有变化立即识别（只受绝对下限约束），不被空闲退避拖慢
                    do_ocr = True
                elif confirm_left > 0 and now - last_ocr >= cur_gap:
                    do_ocr = True                      # 补跑确认（按当前档位间隔）
                if do_ocr and ps.text_gate and last_ocr >= 0 and not had_rows:
                    # 文本门：无字形像素（鼠标/背景晃动等噪声）不跑 OCR，等真正文字出现
                    if self._text_fraction(sig) < 0.0012:
                        do_ocr = False

                if do_ocr:
                    lines = self._ocr.recognize(frame)
                    if confirm_left > 0:
                        confirm_left -= 1
                    last_ocr = now
                    had_rows = bool(lines)
                    self._counters["ocr"] += 1
                    if not lines:
                        empty_run += 1
                        if empty_run in (1, 10, 50, 200):
                            log.warning(
                                "OCR 连续 %d 次未识别到文字：区域可能为空/黑屏/截错位置，请用“区域OCR自检”确认",
                                empty_run,
                            )
                    else:
                        empty_run = 0
                        log.debug("OCR 识别到 %d 行: %s", len(lines), [l.text[:40] for l in lines[:5]])
                    self.pipeline.feed(lines)
                    self._counters["rows"] = len(self.pipeline.visible_entries())
                    pending = self.pipeline.pending_texts()
                    if pending:
                        self._request_batch(pending)
                        self._counters["translate_req"] += len(pending)
                    if self.pipeline.take_dirty():
                        self.cb.on_snapshot(self.pipeline.snapshot())
                        self._counters["snapshots"] += 1

                if now - last_status > 1.0:
                    last_status = now
                    self.cb.on_status(dict(self._counters))

                # ---- 节流睡眠 ----
                if changed:
                    delay = ps.sample_ms / 1000.0
                else:
                    next_t: Optional[float] = None
                    if confirm_left > 0 or had_rows:
                        next_t = last_ocr + gap_active
                    if last_ocr >= 0 and next_t is None:
                        next_t = last_ocr + gap_idle
                    if next_t is None:
                        delay = max(0.1, ps.idle_sample_s)
                    else:
                        delay = min(max(0.05, next_t - now), max(0.1, ps.idle_sample_s))
                time.sleep(max(0.03, delay))
        except Exception as exc:  # noqa: BLE001
            log.exception("采样线程异常")
            self.cb.on_error(f"采样线程异常: {exc}")
        finally:
            log.info("采样线程退出")

    # --- 内部 ---
    def _drain_results(self) -> None:
        while True:
            try:
                norm, translated = self._results.get_nowait()
            except queue.Empty:
                return
            if translated:
                if self.pipeline.apply_translation(norm, translated):
                    self._counters["translate_done"] += 1
                    self.cb.on_snapshot(self.pipeline.snapshot())
                    self._counters["snapshots"] += 1
            else:
                if self.pipeline.apply_translation_failed(norm):
                    self.cb.on_snapshot(self.pipeline.snapshot())
                    self._counters["snapshots"] += 1
            self.pipeline.take_dirty()


class TranslationWorker(threading.Thread):
    """串行翻译 worker：以“批”为单位消费。

    支持 translate_batch(list->list)（一次 API 调用多行）；未提供时退化为逐条调用。
    """

    def __init__(
        self,
        translate_call: Callable[[str], str],
        translate_batch: Optional[Callable[[list[str]], list[str]]],
        result_cb: Callable[[str, Optional[str]], None],
        done_cb: Callable[[str], None],
        fail_cb: Optional[Callable[[list[str]], None]] = None,
        shared_q: Optional["queue.PriorityQueue"] = None,
    ) -> None:
        super().__init__(name="TranslationWorker", daemon=True)
        self._translate_call = translate_call
        self._translate_batch = translate_batch
        self._result_cb = result_cb
        self._done_cb = done_cb
        self._fail_cb = fail_cb
        # 优先级队列：批次序号越大(越新)越先处理 -> put(-seq)；None 为停止哨兵
        self._q: "queue.PriorityQueue" = shared_q if shared_q is not None else queue.PriorityQueue()

    def enqueue(self, seq: int, norms: list[str]) -> None:
        self._q.put((-seq, seq, norms))

    def stop(self) -> None:
        self._q.put((0, 0, None))

    def run(self) -> None:
        log.info("翻译 worker 启动（batch=%s）", self._translate_batch is not None)
        while True:
            item = self._q.get()
            if item is None or item[2] is None:
                break
            norms = item[2]
            try:
                if self._translate_batch is not None:
                    outs = self._translate_batch(norms)
                else:
                    outs = [self._translate_call(n) for n in norms]
                for n, o in zip(norms, outs):
                    self._result_cb(n, o if o else None)
            except Exception as exc:  # noqa: BLE001
                log.warning("批量翻译失败 %d 行: %s", len(norms), exc)
                for n in norms:
                    self._result_cb(n, None)
                if self._fail_cb is not None:
                    try:
                        self._fail_cb(norms)
                    except Exception:  # noqa: BLE001
                        pass
            finally:
                for n in norms:
                    try:
                        self._done_cb(n)
                    except Exception:  # noqa: BLE001
                        pass
        log.info("翻译 worker 退出")


class Coordinator:
    """组装采样线程与翻译 worker：批请求去重、失败节流、启停。"""

    def __init__(
        self,
        ps: PipelineSettings,
        phys_rect: dict,
        capture,
        ocr_engine: object,
        translate_call: Callable[[str, str], str],
        callbacks: Callbacks,
        translate_batch: Optional[Callable[[list[str], str], list[str]]] = None,  # (norms, src) -> list
    ) -> None:
        self.ps = ps
        self._results: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
        self._inflight: set[str] = set()
        self._failed: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._retry_after_s = 20.0
        self._seq = 0

        def do_translate(norm: str) -> str:
            return translate_call(norm, ps.source_lang)

        def do_translate_batch(norms: list[str]) -> list[str]:
            if translate_batch is not None:
                out = translate_batch(norms, ps.source_lang)
                with self._lock:
                    for n in norms:
                        self._failed.pop(n, None)
                return out
            return [do_translate(n) for n in norms]

        def on_result(norm: str, translated: Optional[str]) -> None:
            self._results.put((norm, translated))

        def on_done(norm: str) -> None:
            with self._lock:
                self._inflight.discard(norm)

        def on_batch_failed(norms: list[str]) -> None:
            now = time.monotonic()
            with self._lock:
                for n in norms:
                    self._failed[n] = now

        def _near_same(a: str, b: str) -> bool:
            if a == b:
                return True
            if not a or not b or len(a) < 12 or len(b) < 12:
                return False
            if abs(len(a) - len(b)) > max(5, len(a) // 6):
                return False
            return _similar(a, b)

        self._sent: list[str] = []      # 近期已发/在途文本（跨位置近似去重）
        self._sent_cap = 160

        def request_translation_batch(norms: list[str]) -> None:
            now = time.monotonic()
            with self._lock:
                todo = []
                for n in norms:
                    if n in self._inflight:
                        continue
                    if now - self._failed.get(n, 0.0) < self._retry_after_s:
                        continue
                    # 跨位置近似去重：同一条消息的滚动/OCR变体不再重复请求
                    dup = False
                    for act in list(self._inflight):
                        if _near_same(n, act):
                            dup = True
                            break
                    if not dup:
                        for sent in self._sent:
                            if _near_same(n, sent):
                                dup = True
                                break
                    if dup:
                        continue
                    self._inflight.add(n)
                    self._sent.append(n)
                    todo.append(n)
                if len(self._sent) > self._sent_cap:
                    del self._sent[: len(self._sent) - self._sent_cap]
                self._seq += 1
                seq = self._seq
            if todo:
                self._worker.enqueue(seq, todo)

        self._shared_q: "queue.PriorityQueue" = queue.PriorityQueue()
        self._worker = TranslationWorker(
            do_translate, do_translate_batch if translate_batch is not None else None,
            on_result, on_done, fail_cb=on_batch_failed, shared_q=self._shared_q,
        )
        self._worker2 = TranslationWorker(
            do_translate, do_translate_batch if translate_batch is not None else None,
            on_result, on_done, fail_cb=on_batch_failed, shared_q=self._shared_q,
        )
        self._workers = [self._worker, self._worker2]
        self._sampler = SamplingThread(
            ps, phys_rect, capture, ocr_engine, request_translation_batch, self._results, callbacks
        )
        self._warm_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        for w in self._workers:
            w.start()
        self._sampler.start()
        ocr = self._sampler._ocr

        def warm():
            try:
                ocr.recognize(np.zeros((24, 24, 3), dtype=np.uint8))
                log.info("OCR 模型预热完成")
            except Exception as exc:  # noqa: BLE001
                log.warning("OCR 预热失败（稍后会自动重试）: %s", exc)

        self._warm_thread = threading.Thread(target=warm, name="OcrWarm", daemon=True)
        self._warm_thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        self._sampler.stop()
        for w in self._workers:
            w.stop()
        self._sampler.join(timeout=6)
        for w in self._workers:
            w.join(timeout=6)
        if self._warm_thread is not None:
            self._warm_thread.join(timeout=2)
        log.info("管线已停止")

    @property
    def running(self) -> bool:
        return self._sampler.is_alive()
