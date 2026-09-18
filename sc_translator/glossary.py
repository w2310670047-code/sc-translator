"""SC 术语表（专有名词预替换层）。

解决 “Stanton 被翻成奇怪中文 / 地名保留英文” 这类聊天翻译错误：
翻译前把已知词条就地替换为中文（Stanton -> 斯坦顿星系、Pyro -> 派罗星系…），
再交给 AI 润色整句；译文返回后再兜底替换一次，确保输出不再出现漏网英文词条。

规则：
- 词条文件为 ini/纯文本：每行 `Stanton = 斯坦顿星系`
- 匹配按词边界、忽略大小写；多词词条优先（Pyro System > Pyro）
- 不替换嵌在更长单词里的子串（Stantons 不受影响）
- 聊天中若玩家名恰好叫 Pyro 会被替换——可把该玩家加入词条文件注释或把词条写成长句
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

log = logging.getLogger(__name__)

_terms: dict[str, str] = {}
_pattern: Optional[re.Pattern] = None
_loaded_path: Optional[str] = None
_pattern_dirty = False


def configured() -> bool:
    return bool(_terms)


def load(path: str, max_entries: int = 20000) -> int:
    """载入术语表。max_entries 只是防爆上限（默认 20000，足够装下官方全量专名）。

    注意：正则编译推迟到**首次 apply** 时才做（8000+ 词条的编译约 0.5 秒，
    放启动路径会拖慢窗口出现；放首次翻译时几乎无感）。
    """
    global _terms, _pattern, _loaded_path, _pattern_dirty
    _terms = {}
    _pattern = None
    _loaded_path = None
    _pattern_dirty = False
    if not path or not os.path.exists(path):
        return 0
    count = 0
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for raw in fh:
                if count >= max_entries:
                    log.warning("术语表条目超过上限 %d，多余部分被忽略", max_entries)
                    break
                line = raw.strip()
                if not line or line.startswith(("#", ";", "//")) or "=" not in line:
                    continue
                en, zh = line.split("=", 1)
                en = en.strip()
                zh = zh.strip()
                if len(en) >= 2 and zh:
                    _terms[en.lower()] = zh
                    count += 1
    except Exception as exc:  # noqa: BLE001
        log.warning("术语表加载失败 %s: %s", path, exc)
        return 0
    _loaded_path = path
    _pattern_dirty = True
    log.info("SC 术语表已加载：%d 词条 (%s)", count, path)
    return count


def _ensure_pattern() -> None:
    global _pattern_dirty
    if _pattern_dirty or (_pattern is None and _terms):
        _compile()
        _pattern_dirty = False


def _compile() -> None:
    global _pattern
    if not _terms:
        _pattern = None
        return
    keys = sorted(_terms, key=lambda k: (len(k), k), reverse=True)  # 长词/多词优先
    parts = "|".join(re.escape(k) for k in keys)
    _pattern = re.compile(rf"(?<![A-Za-z])({parts})(?![A-Za-z])", re.IGNORECASE)


def clear() -> None:
    global _terms, _pattern, _loaded_path, _pattern_dirty
    _terms = {}
    _pattern = None
    _loaded_path = None
    _pattern_dirty = False


def apply(text: str) -> str:
    """把已知词条替换为中文（词边界匹配）。未配置/无命中原样返回。"""
    if not text or not _terms:
        return text
    _ensure_pattern()
    if _pattern is None:
        return text

    def _rep(m: "re.Match[str]") -> str:
        key = m.group(1).lower()
        return _terms.get(key, m.group(1))

    try:
        return _pattern.sub(_rep, text)
    except Exception:  # noqa: BLE001
        return text


SAMPLE = """# SC 术语表：聊天预替换用（每行 英文词条 = 规范中文译名，可多词）
# 词条越“短且专名化”越好（地名/物品/载具/组织…），整句或太泛的词不要放。

# --- 地名/星系（示例已确认） ---
Stanton = 斯坦顿星系
Pyro = 派罗星系
# Crusader = <你的规范译名>          # 例：Crusader 系统/星球
# Hurston = <你的规范译名>
# Microtech = <你的规范译名>

# --- 物品/装备（把译名补在等号后） ---
# Quantanium = 
# MedPen = 

# --- 载具/飞船（SC 多数船名保持英文；需要直译的才加） ---
# Constellation = 
# Freelancer = 

# --- 组织/其它专名 ---
# Nine Tails = 
"""

# 内置默认词条（已与你确认的常用译名；用户文件可覆盖或增删）
DEFAULT_TERMS = {
    "Stanton": "斯坦顿星系",
    "Pyro": "派罗星系",
}


def ensure_defaults() -> None:
    """把内置默认词条并入（文件里没有才补）。"""
    global _pattern
    changed = False
    for k, v in DEFAULT_TERMS.items():
        if k.lower() not in _terms:
            _terms[k.lower()] = v
            changed = True
    if changed:
        _compile()


def write_sample(path: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("写术语表模板失败: %s", exc)
        return False


def build_full_from_pairs(src_path: str, out_path: str, max_entries: int = 4000) -> int:
    """从“英文值=中文值”配对文件(如 sc_full_dict.ini)挖掘句中可替换词条。

    筛选（保证安全替换）：
    - en 无数字/占位/过长，1~6 词
    - zh 含中文且不含残存英文字母（全译完成）
    - 按 en 长度降序取前 max_entries（长词/多词优先，避免短词过度替换）
    """
    import re as _re

    stop = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are", "it", "at", "by"}
    en_re = _re.compile(r"[A-Za-z][A-Za-z '-]{2,59}")
    zh_re = _re.compile(r"[\u4e00-\u9fff]")
    ascii_letters = _re.compile(r"[A-Za-z]")
    digit = _re.compile(r"\d")
    cand: dict[str, str] = {}
    try:
        with open(src_path, "r", encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(("#", ";", "//")) or "=" not in line:
                    continue
                en, zh = line.split("=", 1)
                en = en.strip()
                zh = zh.strip()
                if ("\n" in en) or ("\n" in zh) or not en or not zh:
                    continue
                words = en.lower().split()
                if not (1 <= len(words) <= 6):
                    continue
                if len(en) < 4 or len(en) > 60 or digit.search(en):
                    continue
                if not en_re.fullmatch(en):
                    continue
                if any(w in stop for w in words) and len(words) == 1:
                    continue
                if not zh_re.search(zh) or ascii_letters.search(zh):
                    continue  # 只收“完整译成中文”的
                cand.setdefault(en.lower(), zh)
    except Exception as exc:  # noqa: BLE001
        log.warning("挖掘词条失败: %s", exc)
        return 0
    chosen = sorted(cand.items(), key=lambda kv: (len(kv[0]), kv[1]), reverse=True)[:max_entries]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("# SC 大词表（由英文/中文 global.ini 配对自动挖掘，可自行增删）\n")
        for en, zh in chosen:
            fh.write(f"{en} = {zh}\n")
    log.info("已生成大词表：%d 词条 -> %s", len(chosen), out_path)
    return len(chosen)
