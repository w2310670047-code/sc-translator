r"""复核反例：证明「点按按钮」路径未被 tester 脚本覆盖，并给出可复现的补齐方式。

背景
----
`docs/测试报告.md` 第 2 节标注的脚本是 `%TEMP%\qa_offscreen_ui.py`，
其实际调用如下（该方法**绕过了 QPushButton 与 signal/slot 连线**）：

    win._translate_to_zh()      # 直接调用槽函数
    win._translate_reply()

也就是说，报告中的「点击后立即进入 busy 状态」等断言，验证的是
「调用槽函数 -> 写文本框」，并没有验证
「点按 QPushButton -> clicked 信号 -> 槽函数 -> 写文本框」。

本脚本用**假客户端**（不发起任何真实 API 请求、不需要 Key）补齐该缺口：
先按 tester 的方式（直调槽）跑一遍，再按真实点按（`QPushButton.click()`）跑一遍，
对比两者的可观测差异。

运行
----
    cd "E:\SC Translator"
    $env:QT_QPA_PLATFORM="offscreen"; $env:SC_TRANSLATOR_NO_HOTKEYS="1"; $env:PYTHONIOENCODING="utf-8"
    .\.venv\Scripts\python.exe tools\复核-点按路径.py

预期：两组断言均通过，但只有第二组能证明「按钮 -> 槽」连线正确。
若把 main_window.py 中 `self._btn_reply.clicked.connect(self._translate_reply)`
删掉，第二组会立刻失败，而第一组仍然通过 —— 这正是原脚本的盲区。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

REAL_HOME = ROOT / "data"
tmp_home = Path(tempfile.mkdtemp(prefix="verify_click_")) / "data"
tmp_home.mkdir(parents=True, exist_ok=True)
# 关键：settings.json 提供 api_base/model/glossary 配置，api_key.bin 让 _persist_api() 通过。
# 这里只借用密钥文件的存在性，脚本不会打印 Key，也不会发起真实请求（客户端被替换为假客户端）。
import shutil  # noqa: E402

for _n in ("settings.json", "api_key.bin", "sc_glossary.ini"):
    if (REAL_HOME / _n).exists():
        shutil.copy2(REAL_HOME / _n, tmp_home / _n)
(tmp_home / "cache.json").write_text("{}", encoding="utf-8")
os.environ["SC_TRANSLATOR_HOME"] = str(tmp_home)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["SC_TRANSLATOR_NO_HOTKEYS"] = "1"

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from sc_translator.app import AppController  # noqa: E402
from sc_translator.settings import Settings  # noqa: E402

_dialogs: list[str] = []
for _n in ("information", "warning", "critical"):
    def _mk(n=_n):
        def _f(parent=None, title="", text="", *a, **k):
            _dialogs.append(f"{n}: {title} | {text}")
        return _f
    from PySide6.QtWidgets import QMessageBox

    setattr(QMessageBox, _n, staticmethod(_mk()))

_calls: list[str] = []


class _FakeClient:
    def __init__(self):
        self.opts = type("O", (), {"model": "fake"})()

    def list_models(self):
        _calls.append("list_models")
        return ["fake-model"]

    def translate_lines_batch(self, lines, source_lang="auto", target_lang="zh-CN"):
        _calls.append(f"batch:{len(lines)}")
        return [f"【假译文{i + 1}】{t}" for i, t in enumerate(lines)]

    def translate_reply(self, text, target_lang="English", spicy=False):
        _calls.append(f"reply:{target_lang}:spicy={bool(spicy)}")
        return f"FAKE_REPLY({target_lang},{'spicy' if spicy else 'normal'})"


app = QApplication.instance() or QApplication(sys.argv[:1])
ctrl = AppController(app, Settings().load())
ctrl.init_ui()
ctrl.make_client = lambda use_cache=True: _FakeClient()  # type: ignore[assignment]
win = ctrl.mainwin
win.show()
app.processEvents()

fails: list[str] = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def drain(timeout=30.0):
    import time

    t0 = time.time()
    while win._busy and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def find(text):
    return next((b for b in win.findChildren(QPushButton) if b.text() == text), None)


def group_a_direct_slot():
    """tester 的方式：直调槽函数（绕过按钮与信号连线）。"""
    print("\nA) tester 原脚本方式：直调槽函数（不点按钮）")
    win._in_en.setPlainText("Heading to Pyro now")
    win._result_en.setPlainText("")
    _calls.clear()
    win._translate_to_zh()
    check("槽函数被调用后立即 busy", win._busy is True)
    drain()
    check("结果文本框被写入", win._result_en.toPlainText().strip() != "",
          repr(win._result_en.toPlainText()))


def group_b_real_click():
    """补齐方式：真实 QPushButton.click()，走 clicked 信号。"""
    print("\nB) 补齐方式：真实点按 QPushButton.click()（走 clicked 信号）")
    btn = find("翻译到中文")
    check("找到按钮「翻译到中文」", btn is not None)
    win._in_en.setPlainText("Heading to Pyro now\nanyone up for a bounty run?")
    win._result_en.setPlainText("")
    _calls.clear()
    btn.click()
    app.processEvents()
    check("点按后触发后台批量翻译（证明按钮->槽已连线）",
          any(c.startswith("batch:") for c in _calls), str(_calls))
    drain()
    check("点按后结果文本框被写入（按钮->槽->文本框 链路完整）",
          "【假译文1】" in win._result_en.toPlainText(),
          repr(win._result_en.toPlainText()))

    btn2 = find("翻译并复制")
    win._out_zh.setPlainText("别跑啊，单挑")
    win._result_en.setPlainText("")
    _calls.clear()
    btn2.click()
    app.processEvents()
    check("点按「翻译并复制」触发 translate_reply",
          any(c.startswith("reply:") for c in _calls), str(_calls))
    drain()
    check("点按后回话译文写入文本框",
          "FAKE_REPLY" in win._result_en.toPlainText(),
          repr(win._result_en.toPlainText()))
    check("点按后译文进入剪贴板",
          QApplication.clipboard().text().strip() == win._result_en.toPlainText().strip())


group_a_direct_slot()
group_b_real_click()

ctrl.shutdown()
print(f"\n==== 反例脚本汇总：{'全部通过' if not fails else 'FAIL ' + str(fails)} ====")
print("说明：A 组即使删除 main_window.py 里的 clicked.connect(...) 仍会通过；B 组才会失败。")
raise SystemExit(1 if fails else 0)
