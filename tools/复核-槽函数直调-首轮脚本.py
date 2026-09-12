"""QA 离屏界面流程测试（不弹窗）。

对应用户任务第 2 项：
  QT_QPA_PLATFORM=offscreen 下构造 AppController + init_ui，
  填入 motd 外文后调用 mainwin._translate_to_zh()，
  再填入中文调用 mainwin._translate_reply()，
  轮询 app.processEvents() 直到 _busy=False，
  断言 result 文本框非空、状态文本符合预期。

数据目录重定向到临时 home（保留真实 api_key.bin 与 sc_glossary.ini 的副本），
不会改动用户的 data/ 目录。脚本不会打印 API Key。
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

tmp_root = Path(tempfile.mkdtemp(prefix="sc_qa_offscreen_"))
tmp_home = tmp_root / "data"
tmp_home.mkdir(parents=True, exist_ok=True)
for name in ("settings.json", "api_key.bin", "cache.json", "sc_glossary.ini"):
    src = REAL_HOME / name
    if src.exists():
        shutil.copy2(src, tmp_home / name)
# 缓存清空，确保真的走 API（缓存命中也算通过，但要能分辨）
(tmp_home / "cache.json").write_text("{}", encoding="utf-8")
os.environ["SC_TRANSLATOR_HOME"] = str(tmp_home)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SC_TRANSLATOR_NO_HOTKEYS"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

from sc_translator import APP_DISPLAY_NAME, __version__, glossary  # noqa: E402
from sc_translator.app import AppController  # noqa: E402
from sc_translator.settings import Settings  # noqa: E402

MOTD = [
    "Server MOTD: Welcome to the Verse!",
    "Heading to Pyro now",
    "anyone up for a bounty run?",
]
REPLY_ZH = "你们这队人打得真菜，回家练练吧"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def wait_idle(win, app, timeout_s: float = 120.0) -> tuple[float, bool]:
    t0 = time.time()
    while win._busy and time.time() - t0 < timeout_s:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()
    return time.time() - t0, not win._busy


def main() -> int:
    app = QApplication(sys.argv[:1])
    settings = Settings().load()
    print(f"数据目录 = {tmp_home}")
    print(f"model={settings.model!r} api_base={settings.api_base!r} "
          f"glossary_enabled={settings.glossary_enabled} spicy_mode={settings.spicy_mode} "
          f"auto_copy_reply={settings.auto_copy_reply}")
    print(f"API Key 已载入 = {bool(settings.load_api_key())}")
    print(f"{APP_DISPLAY_NAME} v{__version__}")

    controller = AppController(app, settings)
    controller.init_ui()
    win = controller.mainwin
    win.show()
    app.processEvents()

    check("init_ui 构造主窗口成功", win is not None)
    check("术语表词条数 > 1000（应约 1239）", len(glossary._terms) > 1000,
          f"实际 {len(glossary._terms)} 条；configured={glossary.configured()}")
    check("术语表命中 Pyro -> 派罗星系",
          glossary.apply("Heading to Pyro now") == "Heading to 派罗星系 now",
          repr(glossary.apply("Heading to Pyro now")))
    print(f"术语表界面状态标签 = {win._gl_state.text()!r}")

    # ---------------- 1) 看懂：外 -> 中 ----------------
    win._in_en.setPlainText("\n".join(MOTD))
    check("窗口初始 _busy=False", win._busy is False)
    t0 = time.time()
    win._translate_to_zh()
    busy_after_click = win._busy
    check("点击后立即进入 busy 状态（异步，不卡 UI）", busy_after_click is True)
    elapsed, finished = wait_idle(win, app)
    total = time.time() - t0
    out_zh = win._result_en.toPlainText()
    status = win._status.text()
    print(f"--- 看懂（外->中）耗时 {total:.2f}s，状态={status!r}")
    print("输入：", MOTD)
    print("输出：", repr(out_zh))
    check("看懂：轮询结束 _busy=False", finished)
    check("看懂：结果文本框非空", bool(out_zh.strip()), f"len={len(out_zh)}")
    check("看懂：输出为中文", any("\u4e00" <= ch <= "\u9fff" for ch in out_zh))
    check("看懂：状态为「完成」", status == "完成", status)
    check("看懂：术语表命中「派罗星系」", "派罗星系" in out_zh, out_zh[:200])
    check("看懂：输出行数与输入一致（3 行）",
          len([x for x in out_zh.splitlines() if x.strip()]) == len(MOTD), repr(out_zh))

    # ---------------- 2) 回话：中 -> 英 ----------------
    win._out_zh.setPlainText(REPLY_ZH)
    win._reply_target.setCurrentText("English")
    t0 = time.time()
    win._translate_reply()
    elapsed2, finished2 = wait_idle(win, app)
    total2 = time.time() - t0
    out_en = win._result_en.toPlainText()
    status2 = win._status.text()
    clip = QApplication.clipboard().text()
    print(f"--- 回话（中->英）耗时 {total2:.2f}s，状态={status2!r}")
    print("输入：", REPLY_ZH)
    print("输出：", repr(out_en))
    check("回话：轮询结束 _busy=False", finished2)
    check("回话：结果文本框非空", bool(out_en.strip()), f"len={len(out_en)}")
    check("回话：输出为英文（无中日韩字符）",
          not any("\u4e00" <= ch <= "\u9fff" for ch in out_en), out_en[:200])
    check("回话：状态为「已复制译文」", status2 == "已复制译文", status2)
    check("回话：译文已写入剪贴板（auto_copy_reply）", clip.strip() == out_en.strip(),
          f"clip_len={len(clip)}")

    # ---------------- 3) 嘴臭开关落盘 ----------------
    before = settings.spicy_mode
    win._spicy.setChecked(True)
    app.processEvents()
    saved = Settings()
    saved.load()
    check("嘴臭开关写盘 True 生效", saved.spicy_mode is True, f"文件值={saved.spicy_mode}")
    win._spicy.setChecked(False)
    app.processEvents()
    saved2 = Settings()
    saved2.load()
    check("嘴臭开关写盘 False 生效", saved2.spicy_mode is False, f"文件值={saved2.spicy_mode}")
    print(f"嘴臭开关初始值={before}，切换后落盘={saved.spicy_mode}/{saved2.spicy_mode}")

    # ---------------- 4) 嘴臭模式下的回话（走真实 API 一次，验证 UI->spicy 链路）----------------
    win._spicy.setChecked(True)
    app.processEvents()
    win._out_zh.setPlainText("别跑啊，单挑")
    win._reply_target.setCurrentText("English")
    t0 = time.time()
    win._translate_reply()
    _, finished3 = wait_idle(win, app)
    out_spicy = win._result_en.toPlainText()
    status3 = win._status.text()
    print(f"--- 嘴臭回话（中->英）耗时 {time.time() - t0:.2f}s，状态={status3!r}")
    print("输入：别跑啊，单挑")
    print("输出：", repr(out_spicy))
    check("嘴臭回话：轮询结束 _busy=False", finished3)
    check("嘴臭回话：结果文本框非空", bool(out_spicy.strip()))
    check("嘴臭回话：输出为英文（无汉字）",
          not any("\u4e00" <= ch <= "\u9fff" for ch in out_spicy), out_spicy[:200])
    check("嘴臭回话：状态为「已复制译文」", status3 == "已复制译文", status3)
    win._spicy.setChecked(False)
    app.processEvents()

    try:
        controller.shutdown()
    except Exception as exc:  # noqa: BLE001
        print("shutdown 异常：", exc)

    failed = [r for r in results if not r[1]]
    print("\n==== 离屏界面汇总 ====")
    print(f"通过 {len(results) - len(failed)}/{len(results)}")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
