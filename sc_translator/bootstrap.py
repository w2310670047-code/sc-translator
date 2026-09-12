"""首次运行自举：把随包资源释放到程序目录，保证打包后开箱可用。

只在目标文件缺失时写入，绝不覆盖用户已经改过/新增的提示词与术语表：
  <程序目录>\\prompts\\*.md        提示词（用户可编辑，改完重启生效）
  <程序目录>\\data\\sc_glossary.ini 官方术语表（专名预替换用）
源码运行时源目录与目标目录相同，函数实际是空操作。
"""

from __future__ import annotations

import logging
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)


def _copy_if_missing(src: Path, dst: Path) -> bool:
    try:
        if not src.is_file() or dst.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("释放 %s 失败（忽略）: %s", dst, exc)
        return False


def seed_prompts() -> int:
    """释放随包提示词到程序目录 prompts\\。返回释放的文件数。"""
    from .prompts import prompts_dir

    src = paths.bundled_prompts_dir()
    if not src.is_dir():
        return 0
    dst = prompts_dir()
    n = 0
    for f in sorted(src.glob("*.md")):
        if _copy_if_missing(f, dst / f.name):
            n += 1
    if n:
        log.info("已释放提示词 %d 个到 %s（可直接编辑，重启生效）", n, dst)
    return n


def seed_glossary() -> bool:
    """释放随包术语表到 data\\sc_glossary.ini。返回是否写入。"""
    src = paths.bundled_glossary_file()
    dst = paths.default_glossary_file()
    if src.resolve() == dst.resolve():
        return False
    ok = _copy_if_missing(src, dst)
    if ok:
        log.info("已释放术语表到 %s", dst)
    return ok


def run() -> None:
    """启动时调用一次（失败不影响程序运行）。"""
    try:
        seed_prompts()
    except Exception as exc:  # noqa: BLE001
        log.warning("提示词自举失败（忽略）: %s", exc)
    try:
        seed_glossary()
    except Exception as exc:  # noqa: BLE001
        log.warning("术语表自举失败（忽略）: %s", exc)
