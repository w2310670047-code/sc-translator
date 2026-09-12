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
        with self._lock:
            self._data[k] = [translated, time.time()]
            self._dirty += 1
            if len(self._data) > self._MAX:
                for old in sorted(self._data, key=lambda x: self._data[x][1])[: len(self._data) - self._MAX]:
                    self._data.pop(old, None)
            if self._dirty >= 25:
                self._dirty = 0
                self.flush()

    def flush(self) -> None:
        with self._lock:
            snapshot = {k: v for k, v in self._data.items()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:  # noqa: BLE001
            log.debug("写缓存失败: %s", exc)
