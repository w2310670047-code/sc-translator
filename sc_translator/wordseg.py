"""英文粘连词分词：RapidOCR 常把整行输出为无空格的一整段（尤其全小写），
翻译前先用词典(wordninja)把连续小写字母长段切分，显著提升翻译质量。

仅处理 ≥14 个纯小写英文字母的连续片段（避免拆散玩家名/ID/缩写）；
无词库或出错时原样返回（不阻塞）。
"""

from __future__ import annotations

import logging
import re
import threading

log = logging.getLogger(__name__)

_lock = threading.Lock()
_wordninja = None
_load_attempted = False

_MIN_RUN = 14
_RUN_RE = re.compile(r"(?<![A-Za-z])([a-z]{%d,})(?![A-Za-z])" % _MIN_RUN)


def _ensure() -> bool:
    global _wordninja, _load_attempted
    if _wordninja is None and not _load_attempted:
        try:
            import wordninja

            _wordninja = wordninja
        except Exception as exc:  # noqa: BLE001
            log.warning("wordninja 不可用，粘连分词关闭: %s", exc)
        finally:
            _load_attempted = True
    return _wordninja is not None


def split_merged_lower(text: str) -> str:
    """把 text 中连续纯小写长段按单词切分（加空格）。"""
    if not text or len(text) < _MIN_RUN:
        return text
    if not _ensure():
        return text

    def _repl(m: "re.Match[str]") -> str:
        word = m.group(1)
        try:
            parts = _wordninja.split(word)
        except Exception:  # noqa: BLE001
            return word
        if len(parts) > 1:
            return " ".join(parts)
        return word

    try:
        return _RUN_RE.sub(_repl, text)
    except Exception as exc:  # noqa: BLE001
        log.debug("分词失败，原样返回: %s", exc)
        return text
