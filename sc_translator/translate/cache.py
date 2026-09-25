"""本地翻译缓存：key=(model, src_lang, 原文) -> 译文，内存 LRU + 文件持久化。"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Optional

from ..paths import cache_file

log = logging.getLogger(__name__)


class TranslationCache:
    _MAX = 4000

    def __init__(self, path=None) -> None:
        self.path = path or cache_file()
        self._data: dict[str, list] = {}  # hash -> [text, ts]
        self._lock = threading.Lock()
        self._dirty = 0
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if isinstance(v, list) and len(v) == 2:
                        self._data[k] = v
        except Exception as exc:  # noqa: BLE001
            log.warning("读取翻译缓存失败: %s", exc)

    @staticmethod
    def _key(model: str, src_lang: str, text: str) -> str:
        return hashlib.sha1(f"{model}|{src_lang}|{text}".encode("utf-8")).hexdigest()[:20]

    def get(self, model: str, src_lang: str, text: str) -> Optional[str]:
        k = self._key(model, src_lang, text)
        with self._lock:
            v = self._data.get(k)
            if v:
                v[1] = time.time()
                return v[0]
        return None

    def put(self, model: str, src_lang: str, text: str, translated: str) -> None:
        k = self._key(model, src_lang, text)
        need_flush = False
        with self._lock:
            self._data[k] = [translated, time.time()]
            self._dirty += 1
            if len(self._data) > self._MAX:
                for old in sorted(self._data, key=lambda x: self._data[x][1])[: len(self._data) - self._MAX]:
                    self._data.pop(old, None)
            if self._dirty >= 25:
                self._dirty = 0
                need_flush = True
        # 落盘必须在**锁外**调用：flush() 自己也要拿这把锁，而 threading.Lock
        # 不可重入 —— 锁内调用等于同一线程自我死锁（实测第 25 次 put 永久卡死
        # 工作线程，界面表现为永远停在"正在识别并翻译"，关窗时主线程抢同一把锁
        # 又会冻住 → Windows 显示"Python 未响应"）。
        if need_flush:
            self.flush()

    def flush(self, timeout: Optional[float] = None) -> bool:
        """把内存缓存写盘；返回是否真的写成。

        ``timeout`` 秒内拿不到锁就放弃（返回 False），而不是干等。
        退出流程用它兜底：万一还有别的线程卡在持锁位置，
        宁可丢一次缓存也不能让主线程冻结。
        """
        if timeout is None:
            acquired = self._lock.acquire()
        else:
            acquired = self._lock.acquire(timeout=timeout)
        if not acquired:
            log.warning("缓存锁被占用，跳过本次落盘（不影响本次使用）")
            return False
        try:
            snapshot = {k: v for k, v in self._data.items()}
        finally:
            self._lock.release()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return True
        except Exception as exc:  # noqa: BLE001
            log.debug("写缓存失败: %s", exc)
            return False
