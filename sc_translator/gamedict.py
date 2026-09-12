"""SC 静态翻译词典（词典优先层）。

加载用户提供的 bilingual 词典（.ini/纯文本，每行 `英文文本 = 中文译文`），
OCR 行命中时直接返回中文——不消耗 API、零网络延迟。

查找策略（按顺序）：
1) 归一化全等（折叠空白/去首尾标点）
2) “去空白变体”匹配（处理 OCR 丢空格，如 AcceptContract）
3) 前缀/子串后缀宽松匹配已在 UI 文案中常见，但为控制误伤仅用 1-2。
词典为整行级；聊天等动态文本不在词典里，自然走 AI。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger(__name__)

_normal = re.compile(r"\s+")
_trail = re.compile(r"[\s:：,.!?。！？，、;；'\"]+$")
_lead = re.compile(r"^[\s:：,.!?。！？，、;；'\"]+")
_COMMENT = re.compile(r"^\s*(#|//|;|;)")

_cache: dict[str, str] = {}          # normalized 全等表
_cache_nospace: dict[str, str] = {}  # 去空白表（长度>=6 才建，避免短词冲突）
_loaded_path: Optional[str] = None


def _norm(text: str) -> str:
    t = _normal.sub(" ", text).strip().casefold()
    t = _lead.sub("", _trail.sub("", t))
    return t


def _nospace(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", _norm(text))


def configured() -> bool:
    return bool(_cache)


def load(path: str, max_entries: int = 30000) -> dict:
    """加载词典。path 不存在/为空返回空表并置未配置。"""
    global _cache, _cache_nospace, _loaded_path
    empty = {}
    if not path or not os.path.exists(path):
        _loaded_path = None
        _cache = empty
        _cache_nospace = empty
        return empty
    cache: dict[str, str] = {}
    nospace: dict[str, str] = {}
    count = 0
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                if count >= max_entries:
                    break
                line = raw.strip()
                if not line or _COMMENT.match(line) or "=" not in line:
                    continue
                en, zh = line.split("=", 1)
                en_n = _norm(en)
                zh_v = zh.strip()
                if not en_n or not zh_v:
                    continue
                cache[en_n] = zh_v
                if len(en_n) >= 6:
                    nospace[_nospace(en_n)] = zh_v
                count += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("词典加载失败 %s: %s", path, exc)
        _loaded_path = None
        _cache = empty
        _cache_nospace = empty
        return empty
    _cache = cache
    _cache_nospace = nospace
    _loaded_path = path
    log.info("翻译词典已加载：%d 词条 (%s)", count, path)
    return cache


def clear() -> None:
    global _cache, _cache_nospace, _loaded_path
    _cache = {}
    _cache_nospace = {}
    _loaded_path = None


def builtin_path() -> str:
    from .paths import RESOURCE_DIR

    return str(RESOURCE_DIR / "preset_dict.ini")


def merge_builtin() -> int:
    """合并内置预设词条（用户词典未覆盖的键）。返回预设新增数。"""
    extra: dict[str, str] = {}
    try:
        with open(builtin_path(), "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or _COMMENT.match(line) or "=" not in line:
                    continue
                en, zh = line.split("=", 1)
                n = _norm(en)
                v = zh.strip()
                if n and v:
                    extra[n] = v
    except Exception as exc:  # noqa: BLE001
        log.warning("内置预设词典读取失败: %s", exc)
        return 0
    added = 0
    for k, v in extra.items():
        if k not in _cache:
            _cache[k] = v
            if len(k) >= 6:
                _cache_nospace[_nospace(k)] = v
            added += 1
    return added


def lookup(text: str) -> Optional[str]:
    """整行命中词典 -> 中文；未命中返回 None（交给 AI）。"""
    if not text or not _cache:
        return None
    n = _norm(text)
    hit = _cache.get(n)
    if hit is not None:
        return hit
    if len(n) >= 6:
        hit = _cache_nospace.get(_nospace(n))
        if hit is not None:
            return hit
    return None


SAMPLE = (
    "# SC 翻译词典模板：每行一个词条，等号前为屏幕英文原文，等号后为中文译文。\n"
    "# 程序会对 OCR 结果做整行匹配；聊天/动态文本不受影响。\n\n"
    "Accept Contract = 接受合同\n"
    "Quantum Travel = 量子跃迁\n"
    "Cargo Space = 货舱空间\n"
    "Claim Ship = 索赔飞船\n"
)


def export_builtin(path: str) -> bool:
    """把内置预设完整导出到 path（便于编辑成个人词典）。"""
    try:
        import shutil

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        shutil.copyfile(builtin_path(), path)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("导出预设失败: %s", exc)
        return False


def _read_ini_map(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip("\n").strip("\r")
            if not line or _COMMENT.match(line) or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if key:
                out[key] = val.strip()
    return out


def build_pair_dictionary(en_path: str, zh_path: str, out_path: str,
                          max_en_chars: int = 320) -> tuple[int, int]:
    """英文/中文两份 global.ini 按 key 配对 -> “英文值=中文值”词典文件。

    跳过：值含换行、纯数字/占位、过于长、英值无拉丁字母、空值。返回(写入数, 跳过数)。
    """
    import re as _re

    en_map = _read_ini_map(en_path)
    zh_map = _read_ini_map(zh_path)
    latin = _re.compile(r"[A-Za-z]")
    written = skipped = 0
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# 由英文/中文 global.ini 自动配对生成（SC Translator 词典）\n")
        for key in en_map:
            if key not in zh_map:
                skipped += 1
                continue
            en_v = en_map[key]
            zh_v = zh_map[key]
            if ("\n" in en_v) or ("\n" in zh_v) or not en_v or not zh_v:
                skipped += 1
                continue
            if not latin.search(en_v) or len(en_v) > max_en_chars:
                skipped += 1
                continue
            fh.write(f"{en_v} = {zh_v}\n")
            written += 1
    return written, skipped


def write_sample(path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("写词典模板失败: %s", exc)
        return False
