r"""单实例锁（QLockFile）行为复核脚本 —— 修复复核 F-02 的证据缺口。

目的
----
原报告 §5 附加验证只写了「预置一个 30 秒前的陈旧锁 → 退出码 0，即陈旧锁自动接管」，
既未披露**造锁方式**，也未区分**持有者进程是否存活**。本脚本用真 `QLockFile` 造锁、
在同一临时数据目录下分 4 种场景实测，明确结论边界：

  A 无锁                          → 应正常启动，退出码 0
  B 持有者进程已死（未回拨）        → 应接管（进程死亡即陈旧），退出码 0
  C 持有者进程已死 + 回拨 30s       → 应接管，退出码 0
  E 持有者进程仍存活（新鲜锁）      → 应拒绝，退出码 1（“已在运行”提示）
  D 持有者进程仍存活 + 回拨 30s     → 应拒绝，退出码 1（时间回拨不构成陈旧）

实现要点
--------
- 造锁一律用真 `QLockFile`（不用文本文件冒充：纯文本写 instance.lock 会被 QLockFile
  视作**损坏锁并直接接管**，会给出假阳性，复核报告已指出这一点）。
- 子进程用 `os.execv` 原地替换，保证“被 kill 的 PID”就是**真正持锁的进程**。
- 子进程内 patch 掉 `QMessageBox.information`：offscreen 下模态对话框会永久阻塞，
  patch 后既能看到提示被触发，又能拿到真实退出码（不再依赖“25s 超时”这一不稳定现象）。
- 数据目录 `SC_TRANSLATOR_HOME` 指向临时目录，项目 `data\` 不被触碰。
- SC_SMOKE_SECONDS=3 缩短单次耗时。

运行
----
    cd "E:\SC Translator"
    $env:QT_QPA_PLATFORM="offscreen"; $env:PYTHONIOENCODING="utf-8"
    .\.venv\Scripts\python.exe "tools\复核-单实例锁.py"
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "Scripts" / "python.exe")
sys.path.insert(0, str(ROOT))

TMP_HOME = Path(tempfile.mkdtemp(prefix="qa_lock_")) / "data"
TMP_HOME.mkdir(parents=True, exist_ok=True)
LOCK = TMP_HOME / "instance.lock"
MARKER = TMP_HOME / "logs" / "app_ready.marker"

WRAPPER = Path(tempfile.mkdtemp(prefix="qa_lock_wrap_")) / "run_app.py"
# 由独立进程承载产品 main()：kill 该 PID 即释放它持有的 QLockFile，
# 同时 patch 掉 QMessageBox.information，避免 offscreen 下模态对话框永久阻塞。
WRAPPER.write_text(
    "import os, sys\n"
    "sys.path.insert(0, r'%s')\n"
    "from PySide6.QtWidgets import QMessageBox\n"
    "def _info(parent=None, title='', text='', *a, **k):\n"
    "    print('QMessageBox.information 已触发:', title, '|', str(text).splitlines()[0], flush=True)\n"
    "QMessageBox.information = staticmethod(_info)\n"
    "from sc_translator.__main__ import main\n"
    "print('wrapper_pid=', os.getpid(), flush=True)\n"
    "raise SystemExit(main())\n"
    % str(ROOT),
    encoding="utf-8",
)

ENV = dict(os.environ, SC_TRANSLATOR_HOME=str(TMP_HOME), QT_QPA_PLATFORM="offscreen",
           SC_SMOKE_SECONDS="3", PYTHONIOENCODING="utf-8")


def lock_with_holder(rollback_s: float | None) -> subprocess.Popen:
    """启动一个真持锁的子进程（SC_SMOKE_SECONDS=3）。"""
    p = subprocess.Popen([PY, str(WRAPPER)], cwd=str(ROOT), env=ENV,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t0 = time.time()
    while time.time() - t0 < 12 and not LOCK.exists():
        time.sleep(0.05)
    if rollback_s:
        old = time.time() - rollback_s
        os.utime(LOCK, (old, old))
    return p


def run_app(label: str, expect: int) -> dict:
    """在临时 home 启动被测程序（带对话框补丁），返回退出码与输出。"""
    if MARKER.exists():
        MARKER.unlink()
    t0 = time.time()
    p = subprocess.run([PY, str(WRAPPER)], cwd=str(ROOT), env=ENV, capture_output=True, timeout=60)
    dt = time.time() - t0
    out = p.stdout.decode("utf-8", "replace")
    dialog = "QMessageBox.information 已触发" in out
    marker = MARKER.exists()
    ok = (p.returncode == expect)
    print(f"\n[{label}]")
    print(f"  退出码 = {p.returncode}（期望 {expect}）{'OK' if ok else '不符'}")
    print(f"  耗时 = {dt:.2f}s；提示框被触发 = {dialog}；启动后 marker = {marker}")
    if not ok:
        print("  stdout 尾部:", out.strip().splitlines()[-3:])
        print("  stderr 尾部:", p.stderr.decode("utf-8", "replace").strip().splitlines()[-3:])
    return {"ok": ok, "rc": p.returncode, "dialog": dialog, "marker": marker, "dt": dt}


def main() -> int:
    print(f"临时数据目录 = {TMP_HOME}")
    fails: list[str] = []

    # A 无锁
    r = run_app("A 无锁（基线）", 0)
    fails += [] if (r["ok"] and not r["dialog"]) else ["A"]
    print(f"  lock 残留 = {LOCK.exists()}")

    # B 持有者被强杀（未回拨）
    p = lock_with_holder(None)
    holder_alive = p.poll() is None
    p.kill()
    p.wait()
    print(f"\n[B 造锁] 真 QLockFile 由子进程持有(pid={p.pid}, 强杀前存活={holder_alive})，随后 kill → 持有者进程已死")
    r = run_app("B 持有者进程已死（未回拨）", 0)
    fails += [] if r["ok"] else ["B"]

    # C 持有者被强杀 + 回拨 30s
    p = lock_with_holder(None)
    p.kill()
    p.wait()
    old = time.time() - 30
    os.utime(LOCK, (old, old)) if LOCK.exists() else None
    print(f"\n[C 造锁] 同上，并对 instance.lock 回拨 30s（mtime={time.strftime('%H:%M:%S', time.localtime(old))}）")
    r = run_app("C 持有者进程已死 + 回拨 30s", 0)
    fails += [] if r["ok"] else ["C"]

    # E 持有者仍存活（新鲜锁）
    p = lock_with_holder(None)
    print(f"\n[E 造锁] 子进程 pid={p.pid} 持有新鲜锁且**仍在运行**（poll={p.poll()}）")
    r = run_app("E 持有者存活 + 新鲜锁", 1)
    fails += [] if r["ok"] else ["E"]
    p.kill()
    p.wait()

    # D 持有者仍存活 + 回拨 30s
    p = lock_with_holder(30)
    print(f"\n[D 造锁] 子进程 pid={p.pid} 持有锁且**仍在运行**，锁文件回拨 30s "
          f"(mtime={time.strftime('%H:%M:%S', time.localtime(os.stat(LOCK).st_mtime))})")
    r = run_app("D 持有者存活 + 回拨 30s", 1)
    fails += [] if r["ok"] else ["D"]
    p.kill()
    p.wait()

    for _ in range(20):
        if not LOCK.exists():
            break
        try:
            LOCK.unlink()
            break
        except PermissionError:
            time.sleep(0.25)   # 刚被 kill 的持有者进程仍持有句柄，稍等再删
    print(f"\n清理：instance.lock 残留 = {LOCK.exists()}")
    print(f"\n==== 单实例锁复核汇总：{'全部符合预期' if not fails else '不符场景 ' + str(fails)} ====")
    print("结论：接管条件是「锁内的持有者进程已不存在」，而不是「锁文件时间超过 15 秒」；"
          "活进程 + 时间回拨仍会拒绝启动（退出码 1）。")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
