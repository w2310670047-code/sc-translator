"""真实 API 最小验证（不进 UI，总共 ≤6 次请求）。

覆盖用户任务第 3 项：
  1) translate_lines_batch 外→中（含 "Heading to Pyro now" 验证术语表命中「派罗星系」）
  2) translate_reply 中→英（正常）
  3) translate_reply(spicy=True) 中→英（嘴臭）

数据目录重定向到临时 home（复制真实 api_key.bin / sc_glossary.ini），
不改动项目 data/ 下的 settings.json / cache.json；脚本不打印 API Key。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

REAL_HOME = Path(r"E:\SC Translator\data")
ROOT = Path(r"E:\SC Translator")
sys.path.insert(0, str(ROOT))

tmp_root = Path(tempfile.mkdtemp(prefix="sc_qa_api_"))
tmp_home = tmp_root / "data"
tmp_home.mkdir(parents=True, exist_ok=True)
for name in ("settings.json", "api_key.bin", "sc_glossary.ini"):
    src = REAL_HOME / name
    if src.exists():
        shutil.copy2(src, tmp_home / name)
os.environ["SC_TRANSLATOR_HOME"] = str(tmp_home)

from sc_translator import glossary  # noqa: E402
from sc_translator.settings import Settings  # noqa: E402
from sc_translator.translate.client import ClientOptions, OpenAiCompatClient  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    s = Settings().load()
    key = s.load_api_key()
    print(f"数据目录={tmp_home}")
    print(f"model={s.model!r} api_base={s.api_base!r} key_loaded={bool(key)} key_len={len(key)}")
    if not key:
        print("没有可用的 API Key，无法做真实 API 验证")
        return 2

    if s.glossary_enabled and s.glossary_path:
        n = glossary.load(s.glossary_path)
        glossary.ensure_defaults()
        print(f"术语表加载 {n} 条，实际生效 {len(glossary._terms)} 条")

    opts = ClientOptions(api_base=s.api_base, api_key=key, model=s.model or "deepseek-chat", spicy=False)
    cl = OpenAiCompatClient(opts)

    # ---- 1) 外 -> 中 批量（1 次请求）----
    lines = ["Server MOTD: Welcome to the Verse!", "Heading to Pyro now", "anyone up for a bounty run?"]
    t0 = time.time()
    try:
        outs = cl.translate_lines_batch(lines, source_lang="auto", target_lang="zh-CN")
        dt = time.time() - t0
        print(f"--- 1) 批量外->中 耗时 {dt:.2f}s")
        for a, b in zip(lines, outs):
            print(f"    IN : {a}\n    OUT: {b}")
        joined = "\n".join(outs)
        check("批量外->中 返回行数一致", len(outs) == len(lines), f"{len(outs)}/{len(lines)}")
        check("批量外->中 译文非空", all(o.strip() for o in outs))
        check("术语表命中：输出含「派罗星系」", "派罗星系" in joined, joined[:200])
        check("术语表未漏英文 Pyro", "Pyro" not in joined, joined[:200])
    except Exception as exc:  # noqa: BLE001
        check("批量外->中", False, f"{type(exc).__name__}: {exc}")

    # ---- 2) 中 -> 英 回话（1 次请求）----
    zh = "你们这队人打得真菜，回家练练吧"
    t0 = time.time()
    try:
        out = cl.translate_reply(zh, "English", spicy=False)
        dt = time.time() - t0
        print(f"--- 2) 回话正常 中->英 耗时 {dt:.2f}s\n    IN : {zh}\n    OUT: {out}")
        check("回话正常：非空", bool(out.strip()))
        check("回话正常：输出英文（无汉字）",
              not any("\u4e00" <= ch <= "\u9fff" for ch in out), out[:200])
    except Exception as exc:  # noqa: BLE001
        check("回话正常 中->英", False, f"{type(exc).__name__}: {exc}")

    # ---- 3) 中 -> 英 嘴臭回话（1 次请求）----
    t0 = time.time()
    try:
        out_sp = cl.translate_reply("别跑啊，单挑", "English", spicy=True)
        dt = time.time() - t0
        print(f"--- 3) 嘴臭回话 中->英 耗时 {dt:.2f}s\n    IN : 别跑啊，单挑\n    OUT: {out_sp}")
        check("嘴臭回话：非空", bool(out_sp.strip()))
        check("嘴臭回话：输出英文（无汉字）",
              not any("\u4e00" <= ch <= "\u9fff" for ch in out_sp), out_sp[:200])
    except Exception as exc:  # noqa: BLE001
        check("嘴臭回话 中->英", False, f"{type(exc).__name__}: {exc}")

    failed = [r for r in results if not r[1]]
    print("\n==== 真实 API 汇总 ====")
    print(f"通过 {len(results) - len(failed)}/{len(results)}；实际请求 3 次")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
