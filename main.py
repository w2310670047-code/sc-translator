"""SC Translator 打包入口（PyInstaller 用）。

源码运行请用 `run.bat` 或 `python -m sc_translator`；本文件只做进程入口转发。
"""

from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    from sc_translator.__main__ import main as app_main

    return app_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()   # 打包后避免子进程重复启动
    sys.exit(main())
