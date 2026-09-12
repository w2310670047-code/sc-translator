"""应用数据路径管理。

运行时数据默认放在【程序所在文件夹】下的 data 目录（便携模式，可整体拷贝迁移）：
  data/settings.json   主设置
  data/api_key.bin     经 Windows DPAPI 加密的 API Key
  data/cache.json      翻译缓存
  data/logs/           运行日志（startup.log / sc_translator.log）
只有当程序被当作已安装包运行（找不到随同分发的 run.bat 标记）时，
才退回 %APPDATA%\\SCTranslator。
环境变量 SC_TRANSLATOR_HOME 始终可强制重定向（测试用）。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from . import APP_NAME

log = logging.getLogger(__name__)

# 包内自带资源（随安装/源码分发）
RESOURCE_DIR = Path(__file__).resolve().parent / "resources"


def _program_root() -> Path:
    """包所在目录的上一级（源码运行时为项目根；打包后为 exe 所在目录）。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def home_dir() -> Path:
    override = os.environ.get("SC_TRANSLATOR_HOME")
    if override:
        p = Path(override)
    elif getattr(__import__("sys"), "frozen", False):
        p = _program_root() / "data"          # 打包后：便携模式（exe 同级 data\）
    elif (_program_root() / "run.bat").exists():
        p = _program_root() / "data"
    else:
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def migrate_legacy_data() -> None:
    """一次性迁移旧的 %APPDATA%\\SCTranslator 数据到新的程序目录 data\\。

    仅在新位置尚不存在 settings.json 时执行；已存在则跳过（不覆盖）。
    """
    try:
        new = home_dir()
        if (new / "settings.json").exists():
            return
        old = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
        if not old.exists():
            return
        copied = 0
        for name in ("settings.json", "api_key.bin", "cache.json", "glossary.json"):
            src = old / name
            if src.exists() and not (new / name).exists():
                shutil.copy2(src, new / name)
                copied += 1
        for sub in ("logs", "templates"):
            src = old / sub
            if src.exists() and src.is_dir() and not (new / sub).exists():
                shutil.copytree(src, new / sub)
                copied += 1
        if copied:
            log.info("已从 %s 迁移运行时数据到 %s（%d 项）", old, new, copied)
    except Exception as exc:  # noqa: BLE001
        log.warning("旧数据迁移失败（可忽略）: %s", exc)


def settings_file() -> Path:
    return home_dir() / "settings.json"


def api_key_file() -> Path:
    return home_dir() / "api_key.bin"


def cache_file() -> Path:
    return home_dir() / "cache.json"


def logs_dir() -> Path:
    p = home_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_file() -> Path:
    return logs_dir() / "sc_translator.log"


def templates_dir() -> Path:
    p = home_dir() / "templates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_template_path() -> Path:
    return templates_dir() / "sc_chat.json"


def glossary_path() -> Path:
    return home_dir() / "glossary.json"


def default_glossary_file() -> Path:
    """随包术语表（sc_glossary.ini）：程序目录 data\\ 下，首次运行自动释放。"""
    return home_dir() / "sc_glossary.ini"


def bundled_prompts_dir() -> Path:
    """随包提示词目录（打包后位于 _MEIPASS\\prompts；源码运行时为项目 prompts\\）。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "prompts"
    return _program_root() / "prompts"


def bundled_glossary_file() -> Path:
    """随包术语表源文件（仓库内 assets\\sc_glossary.ini；打包后 _MEIPASS\\assets\\）。"""
    import sys

    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)) / "assets" / "sc_glossary.ini"
    return _program_root() / "assets" / "sc_glossary.ini"


def bundled_template(name: str) -> Path:
    return RESOURCE_DIR / "templates" / name
