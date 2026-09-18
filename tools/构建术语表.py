"""从「英文 global.ini + 汉化文件」构建术语表（专名预替换用）。

用法::

    python tools/构建术语表.py <英文global.ini> <汉化文件.ini> [输出路径]

做法（与"直接全量导出"的区别）：

1. **按键的命名空间收专名**：物品/载具/地点/组织等键前缀才收；`pu_/dlg_/ph_/dxsm_/ui_` 这类
   整句对话与按键提示一律排除（否则会把 "We got a point" 这种句子也当成词条）。
2. **清洗译名**：汉化里大量条目是 `中文（English）` 或 `中文\nEnglish` 形式，
   先取出中文部分再去掉英文括注 —— 这类恰恰是最有用的专名（斯坦顿（Stanton））。
3. **专名形状判定**：每个词要么首字母大写，要么是 of/the/on 这类连接词，要么是 F7A/5a/EMP 这类型号。
4. **合并而非覆盖**：现有术语表全部保留；同名英文若在新汉化里有新译名则更新；只增不改结构。
5. 输出按类别分段（# 地名 / # 载具 / # 物品 / # 组织势力 / # 其它），加载器会忽略注释行。
"""

from __future__ import annotations

import collections
import io
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------- 规则
#: 只在这些键命名空间里找专名（小写前缀匹配）
NAME_PREFIXES = (
    "item_name", "item_subtype", "item_displaytype", "item_name_", "items_name",
    "vehicle_name", "vehicle_named", "event_shipname", "ship_name",
    "mission_location", "area_name", "location_", "outpost_", "landing_",
    "ui_pregame_port_", "port_", "spaceport", "hangar_",
    "manufacturer_name", "repscope_", "organization", "faction",
    "mineabletype_", "items_commodities_", "commodity_", "harvestable_",
    "stanton", "pyro", "nyx", "terra", "sol_", "castra", "ellis", "odin",
    "hurston", "arccorp", "microtech", "crusader", "levski", "orison",
)
#: 这些命名空间整体排除（整句对话 / 按键提示 / 数值 HUD）
PROSE_PREFIXES = (
    "pu_", "dlg_", "ph_", "dxsm_", "dxsh_", "mg_", "input_", "hint", "hud_",
    "pause_", "ea_", "dfm_", "chat_", "mobiglas_", "asd_", "mission_", "sc_",
)
CONNECTORS = {
    "of", "the", "and", "at", "in", "on", "de", "la", "le", "von", "van", "del",
    "der", "el", "al", "du", "des", "di", "da", "dos", "y", "e",
}
CJK = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD = re.compile(r"[A-Za-z]{2,}")
PLACEHOLDER = re.compile(r"[%{}<>]|\\n|\\t")
SENTENCE_END = re.compile(r"[.!?。！？]\s*$")
PAREN_ASCII = re.compile(r"[（(]\s*[A-Za-z0-9 '\-._/&:]+?\s*[)）]")
MODEL_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*$")

#: 类别 -> 键前缀（用于输出分段）
CATEGORIES = [
    ("地名/地点", ("stanton", "pyro", "nyx", "terra", "sol_", "castra", "ellis", "odin",
                   "mission_location", "area_name", "location_", "outpost_", "landing_",
                   "ui_pregame_port_", "port_", "spaceport", "hangar_", "hurston",
                   "arccorp", "microtech", "crusader", "levski", "orison")),
    ("载具/飞船", ("vehicle_", "event_shipname", "ship_name")),
    ("物品/装备", ("item_", "items_")),
    ("组织/势力", ("manufacturer_", "repscope_", "organization", "faction")),
]

#: 人工确认过的译名：新汉化若给出不同写法也不覆盖（斯坦顿星系 / 派罗星系 是本项目明确选定的）
PROTECTED_TERMS = {"stanton", "pyro"}

#: 这些键空间里出现的是"类型名/属性名"，不是专名（shoes/helmet/jacket…）
EXCLUDE_SINGLE_PREFIXES = (
    "item_displaytype_", "item_type", "item_subtype", "port_name", "item_name_eyes_",
    "items_displaytype", "item_nameglass",
)

#: 单词条目里的高频通用词白名单：这些是确实有用的专名，允许高频
ALLOWED_SINGLE = {
    "stanton", "pyro", "nyx", "terra", "sol", "castra", "ellis", "odin", "virgil",
    "uee", "vanduul", "xian", "banu", "aegis", "anvil", "drake", "misc", "origin",
    "rsi", "argo", "mirai", "crusader", "hurston", "arccorp", "microtech", "lorville",
    "orison", "levski", "klescher", "consolidated",
}

#: 单词条目的整词频上限（超过即视为通用词）
SINGLE_WORD_MAX_FREQ = 50


def parse_ini(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    with io.open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] in "#;" or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            if key.lower().endswith(",p"):
                key = key[:-2]
            out.setdefault(key.lower(), val.strip())
    return out


def load_glossary(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def clean_zh(value: str) -> str:
    """把汉化值清洗成纯中文：取中文行、去掉英文括注与尾部英文残留。"""
    v = value.replace("\\n", "\n").split("\n")[0].strip()
    for _ in range(3):                       # 可能有多层括注
        new = PAREN_ASCII.sub("", v).strip()
        if new == v:
            break
        v = new
    v = re.sub(r"\s{2,}", " ", v).strip(" -—·、,")
    # 去掉尾部英文：既处理"中文 English"，也处理"中文English"（矿物名常见：拉腊尼特石Laranite）
    v = re.sub(r"\s+[A-Za-z][A-Za-z0-9 '\-.]{2,}\s*$", "", v).strip()
    t = re.sub(r"[A-Za-z][A-Za-z0-9 '\-.]{3,}$", "", v).strip()
    if len(CJK.findall(t)) >= 2:              # 确保去掉英文后仍是中文，才采用
        v = t
    return v


def is_name_like(en: str) -> bool:
    words = [w for w in en.split() if w]
    if not (1 <= len(words) <= 5) or not (3 <= len(en) <= 45):
        return False
    if PLACEHOLDER.search(en) or SENTENCE_END.search(en):
        return False
    caps = 0
    for w in words:
        core = w.strip("-'’.")
        if not core:
            return False
        if w[0].isupper():
            caps += 1
            continue
        if core.lower() in CONNECTORS:
            continue
        if MODEL_CODE.match(core) and (any(c.isdigit() for c in core) or core.isupper()) and len(core) <= 6:
            continue                          # F7A / 5a / OM-1 / EMP
        return False
    return caps >= 1


def in_namespace(key: str) -> bool:
    k = key.lower()
    if any(k.startswith(p) for p in PROSE_PREFIXES):
        return False
    return any(k.startswith(p) for p in NAME_PREFIXES)


def category_of(key: str) -> str:
    k = key.lower()
    for name, prefixes in CATEGORIES:
        if any(k.startswith(p) for p in prefixes):
            return name
    return "其它专名"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    en_path, zh_path = sys.argv[1], sys.argv[2]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_path = sys.argv[3] if len(sys.argv) > 3 else os.path.join(root, "assets", "sc_glossary.ini")

    en = parse_ini(en_path)
    zh = parse_ini(zh_path)
    keys = set(en) & set(zh)
    print(f"英文键 {len(en)}  汉化键 {len(zh)}  可配对 {len(keys)}")

    # 整词频表：用于区分"专名"与"通用词"（generic 词在 9 万条里出现成百上千次）
    with io.open(en_path, encoding="utf-8-sig", errors="replace") as fh:
        raw = fh.read().lower()
    word_freq = collections.Counter(re.findall(r"[a-z0-9']+", raw))

    def freq_of(term: str) -> int:
        words = [w for w in re.findall(r"[a-z0-9']+", term.lower()) if w]
        if not words:
            return 10 ** 9
        return word_freq.get(words[0], 0) if len(words) == 1 else min(word_freq.get(w, 0) for w in words)

    # 1) 收集专名候选
    cand: dict[str, tuple[str, str]] = {}      # en_lower -> (zh, key)
    skipped_generic = 0
    for k in keys:
        if not in_namespace(k):
            continue
        e = en[k].replace("\\n", " ").strip().strip("\"'“”‘’")
        if not is_name_like(e):
            continue
        z = clean_zh(zh[k])
        if not z or not CJK.search(z) or ASCII_WORD.search(z) or len(z) > 20 or z.lower() == e.lower():
            continue
        # 编号丢失保护：英文带编号而中文里没有数字 -> 替换后会丢信息（如 L5-B 站台号）
        if re.search(r"\d", e) and not re.search(r"\d", z):
            continue
        if len(e.split()) == 1:                 # 单词条目：只留专名，挡掉 shoes/helmet/black 这类
            if k.lower().startswith(EXCLUDE_SINGLE_PREFIXES):
                skipped_generic += 1
                continue
            if e.lower() not in ALLOWED_SINGLE and freq_of(e) > SINGLE_WORD_MAX_FREQ:
                skipped_generic += 1
                continue
        prev = cand.get(e.lower())
        # 同一英文取更短更干净的中文（*_short 键通常更规范）
        if prev is None or (len(z), len(k)) < (len(prev[0]), len(prev[1])):
            cand[e.lower()] = (z, k)
    print(f"专名候选 {len(cand)}（单词通用词已挡掉 {skipped_generic}）")

    # 2) 合并现有术语表（保留全部；同名更新要避开人工确认过的译名与"被截短"的译名）
    base = load_glossary(out_path)
    print(f"现有术语表 {len(base)}")
    updated, added, kept = [], [], 0
    merged: dict[str, tuple[str, str]] = {}    # en_lower -> (zh, key)
    for k, v in base.items():
        new = cand.get(k)
        if new is None or new[0] == v:
            merged[k] = (v, "")
            continue
        new_zh = new[0]
        # 保护 1：人工确认过的译名
        # 保护 2：新译名是旧译名的前缀（多为截短，如 斯坦顿星系 -> 斯坦顿）
        if k in PROTECTED_TERMS or (len(new_zh) < len(v) and v.startswith(new_zh)):
            merged[k] = (v, "")
            kept += 1
            continue
        updated.append((k, v, new_zh))
        merged[k] = (new_zh, new[1])
    for k, (z, key) in cand.items():
        if k not in merged:
            added.append((k, z))
            merged[k] = (z, key)
    print(f"新增 {len(added)}  译名更新 {len(updated)}  保护未改 {kept}  合计 {len(merged)}")

    # 3) 写文件（按类别分段）
    by_cat: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for k, (z, key) in merged.items():
        by_cat[category_of(key) if key else "既有词条（保留）"].append((k, z))
    with io.open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"# SC 术语表：聊天专名预替换（每行 英文 = 规范中文译名，可自行增删）\n")
        fh.write(f"# 来源：{os.path.basename(en_path)}（英文原文） + {os.path.basename(zh_path)}（汉化）\n")
        fh.write(f"# 生成时间：{datetime.now():%Y-%m-%d %H:%M}；共 {len(merged)} 条\n")
        fh.write(f"# 匹配规则：大小写不敏感 + 词边界，多词条目优先\n\n")
        for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
            fh.write(f"# ---------------- {cat}（{len(items)}）----------------\n")
            for k, z in sorted(items, key=lambda kv: (-len(kv[0]), kv[0])):
                fh.write(f"{k} = {z}\n")
            fh.write("\n")
    print(f"已写入 {out_path}")

    print("\n=== 译名更新样本（前 20）===")
    for k, old, new in updated[:20]:
        print(f"  {k[:38]:40} {old[:14]:16} -> {new}")
    print("\n=== 新增样本（前 20）===")
    for k, z in added[:20]:
        print(f"  {k[:38]:40} -> {z}")
    print("\n=== 分类统计 ===")
    for cat, items in sorted(by_cat.items(), key=lambda kv: -len(kv[1])):
        print(f"  {cat:12} {len(items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
