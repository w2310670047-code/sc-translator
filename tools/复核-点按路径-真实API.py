r"""真实点按版离屏界面流程测试（QA 复测，独立于产品代码）。

用途
----
修复复核 F-01：原 `%TEMP%\qa_offscreen_ui.py` 直接调用槽函数
（`win._translate_to_zh()` / `win._translate_reply()`），证据无法支撑「点按按钮」的表述。
本脚本改为**真实点按**（`QPushButton.click()`，走 `clicked` 信号 → 槽函数），
并保留原断言口径：轮询 `app.processEvents()` 直到 `_busy=False` →
断言 `_result_en` 非空 + 状态文本为「完成」/「已复制译文」。

覆盖的按钮（均通过查找文本获得，不引用私有属性直调槽）：
  「翻译到中文」（看懂）、「翻译并复制」（回话）、嘴臭复选框（toggled 信号）。
另外启用与 `tools\复核-点按路径.py` 相同的防护：把 QMessageBox 静态方法替换为记录器，
避免任何意外模态对话框在 offscreen 下阻塞。

数据隔离：数据目录重定向到临时 home（复制真实 api_key.bin / sc_glossary.ini，
cache.json 置空），项目 data\ 不被写入；不打印 API Key。

运行
----
    cd "E:\SC Translator"
    $env:QT_QPA_PLATFORM="offscreen"; $env:SC_TRANSLATOR_NO_HOTKEYS="1"; $env:PYTHONIOENCODING="utf-8"
    .\.venv\Scripts\python.exe "tools\复核-点按路径-真实API.py"
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_HOME = ROOT / "data"
sys.path.insert(0, str(ROOT))

tmp_home = Path(tempfile.mkdtemp(prefix="qa_click_api_")) / "data"
tmp_home.mkdir(parents=True, exist_ok=True)
for _n in ("settings.json", "api_key.bin", "sc_glossary.ini"):
    if (REAL_HOME / _n).exists():
        shutil.copy2(REAL_HOME / _n, tmp_home / _n)
(tmp_home / "cache.json").write_text("{}", encoding="utf-8")
os.environ["SC_TRANSLATOR_HOME"] = str(tmp_home)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SC_TRANSLATOR_NO_HOTKEYS"] = "1"

from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QPushButton  # noqa: E402

from sc_translator.app import AppController  # noqa: E402
from sc_translator.settings import Settings  # noqa: E402

# ---- 防护：任何模态对话框只记录不显示（offscreen 下对话框会永久阻塞）----
_dialogs: list[str] = []
for _n in ("information", "warning", "critical"):
    def _mk(n=_n):
        def _f(parent=None, title="", text="", *a, **k):
            _dialogs.append(f"{n}: {title} | {text}")
        return _f

    setattr(QMessageBox, _n, staticmethod(_mk()))

MOTD = [
    "Server MOTD: Welcome to the Verse!",
    "Heading to Pyro now",
    "anyone up for a bounty run?",
]
REPLY_ZH = "你们这队人打得真菜，回家练练吧"
SPICY_ZH = "别跑啊，单挑"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    settings = Settings().load()
    print(f"数据目录 = {tmp_home}")
    print(f"model={settings.model!r} api_base={settings.api_base!r} glossary_enabled={settings.glossary_enabled}")
    print(f"API Key 已载入 = {bool(settings.load_api_key())}")

    ctrl = AppController(app, settings)
    ctrl.init_ui()
    win = ctrl.mainwin
    win.show()
    app.processEvents()

    def find_btn(text: str):
        return next((b for b in win.findChildren(QPushButton) if b.text() == text), None)

    def wait_idle(timeout_s: float = 120.0):
        t0 = time.time()
        while win._busy and time.time() - t0 < timeout_s:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()
        return not win._busy

    btn_zh = find_btn("翻译到中文")
    btn_reply = find_btn("翻译并复制")
    spicy_box = next((c for c in win.findChildren(QCheckBox) if "嘴臭模式" in c.text()), None)
    check("按文本找到按钮「翻译到中文」", btn_zh is not None)
    check("按文本找到按钮「翻译并复制」", btn_reply is not None)
    check("按文本找到「嘴臭模式」复选框", spicy_box is not None)

    # ---------------- 1) 点按「翻译到中文」（真实 API 1 次批量）----------------
    win._in_en.setPlainText("\n".join(MOTD))
    win._result_en.setPlainText("")
    t0 = time.time()
    btn_zh.click()
    check("点按后同步进入 busy（信号→槽已连线）", win._busy is True)
    finished = wait_idle()
    dt = time.time() - t0
    out_zh = win._result_en.toPlainText()
    status = win._status.text()
    print(f"--- 点按「翻译到中文」耗时 {dt:.2f}s，状态={status!r}")
    print("输入：", MOTD)
    print("输出：", repr(out_zh))
    check("看懂：轮询结束 _busy=False", finished)
    check("看懂：_result_en 非空", bool(out_zh.strip()), f"len={len(out_zh)}")
    check("看懂：输出为中文", any("\u4e00" <= ch <= "\u9fff" for ch in out_zh))
    check("看懂：状态为「完成」", status == "完成", status)
    check("看懂：术语表命中「派罗星系」", "派罗星系" in out_zh, out_zh[:200])
    check("看懂：输出行数与输入一致（3 行）",
          len([x for x in out_zh.splitlines() if x.strip()]) == len(MOTD))

    # ---------------- 2) 点按「翻译并复制」（真实 API 1 次回话）----------------
    win._out_zh.setPlainText(REPLY_ZH)
    win._reply_target.setCurrentText("English")
    win._result_en.setPlainText("")
    t0 = time.time()
    btn_reply.click()
    check("点按「翻译并复制」后同步进入 busy", win._busy is True)
    finished2 = wait_idle()
    dt2 = time.time() - t0
    out_en = win._result_en.toPlainText()
    status2 = win._status.text()
    clip = QApplication.clipboard().text()
    print(f"--- 点按「翻译并复制」耗时 {dt2:.2f}s，状态={status2!r}")
    print("输入：", REPLY_ZH)
    print("输出：", repr(out_en))
    check("回话：轮询结束 _busy=False", finished2)
    check("回话：_result_en 非空", bool(out_en.strip()), f"len={len(out_en)}")
    check("回话：输出为英文（无中日韩字符）",
          not any("\u4e00" <= ch <= "\u9fff" for ch in out_en), out_en[:200])
    check("回话：状态为「已复制译文」", status2 == "已复制译文", status2)
    check("回话：译文入剪贴板（auto_copy_reply）", clip.strip() == out_en.strip(), f"clip_len={len(clip)}")

    # ---------------- 3) 勾选嘴臭复选框 + 点按回话（真实 API 1 次）----------------
    spicy_box.setChecked(True)                     # 触发 toggled 信号
    app.processEvents()
    saved = Settings()
    saved.load()
    check("勾选嘴臭复选框写盘 spicy_mode=True", saved.spicy_mode is True, f"文件值={saved.spicy_mode}")
    win._out_zh.setPlainText(SPICY_ZH)
    win._result_en.setPlainText("")
    t0 = time.time()
    btn_reply.click()
    finished3 = wait_idle()
    out_sp = win._result_en.toPlainText()
    status3 = win._status.text()
    print(f"--- 勾选嘴臭后点按「翻译并复制」耗时 {time.time() - t0:.2f}s，状态={status3!r}")
    print("输入：", SPICY_ZH)
    print("输出：", repr(out_sp))
    check("嘴臭：轮询结束 _busy=False", finished3)
    check("嘴臭：_result_en 非空", bool(out_sp.strip()))
    check("嘴臭：输出为英文（无汉字）",
          not any("\u4e00" <= ch <= "\u9fff" for ch in out_sp), out_sp[:200])
    check("嘴臭：状态为「已复制译文」", status3 == "已复制译文", status3)

    spicy_box.setChecked(False)
    app.processEvents()
    saved2 = Settings()
    saved2.load()
    check("取消勾选写盘 spicy_mode=False", saved2.spicy_mode is False, f"文件值={saved2.spicy_mode}")
    check("全程无意外模态对话框", not _dialogs, str(_dialogs))

    try:
        ctrl.shutdown()
    except Exception as exc:  # noqa: BLE001
        print("shutdown 异常：", exc)

    failed = [r for r in results if not r[1]]
    print("\n==== 真实点按 + 真实 API 汇总 ====")
    print(f"通过 {len(results) - len(failed)}/{len(results)}；真实 API 请求 3 次")
    for name, ok, detail in failed:
        print(f"  FAIL: {name} :: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
