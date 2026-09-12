"""提示词文件加载。

提示词默认放在程序文件夹下的 prompts\\ 目录（.md / .txt 皆可，程序读取纯文本）：
  prompts/translation_normal.md   正常翻译提示词（{src} {target} 占位）
  prompts/translation_spicy.md    嘴臭模式附加提示（开启时追加到 normal 之后）
  prompts/reply.md                回话翻译提示词（{target} 占位）

规则：
- HTML 注释（<!-- ... -->）与以 # 开头的行会被剔除，不会发给模型；
- 缺失/读取出错时回退到内置默认提示词并记录日志；
- 修改文件后需重启程序生效；
- 可用环境变量 SC_PROMPTS_DIR 指向其它提示词目录。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# 内置默认（文件缺失时的回退，与随包 prompts/*.md 内容一致）
DEFAULTS = {
    "translation_normal.md": (
        "你是游戏本地化翻译引擎。把给定的{src}文本翻译成{target}。\n"
        "规则：1) 只输出译文本身，禁止解释、注释、引号或额外内容；"
        "2) 保留玩家名/地名/专有名词原文或通用译名；"
        "3) 译文要自然、简洁，保持原文语气（聊天语气要口语化）；"
        "4) 若原文已经主要是{target}，则原样返回；"
        "5) 不要翻译明显的错误/纯乱码。"
    ),
    "translation_spicy.md": (
        "风格要求（嘴臭模式已开启）：把译文翻成嘴臭版本——嘲讽拉满、阴阳怪气、竞技垃圾话味道，"
        "可以口语化使用“你/菜/就这/多练练/别丢人了/回炉重造”等玩家互怼说法，"
        "把对方语气里的攻击性翻得更嚣张；但禁止真正的脏话辱骂、人身攻击、种族歧视内容，"
        "保持游戏文化内的‘嘴臭’。"
    ),
    "reply.md": (
        "你是游戏聊天翻译器。把玩家的中文消息翻译成{target}用于在游戏内聊天发送。"
        "要求自然口语化，只输出译文本身，不要引号或解释。"
    ),
}

_COMMENT_BLOCK = re.compile(r"<!--.*?-->", re.S)
_HASH_LINE = re.compile(r"^#.*$", re.M)


def prompts_dir() -> Path:
    env = os.environ.get("SC_PROMPTS_DIR")
    if env:
        return Path(env)
    import sys

    if getattr(sys, "frozen", False):
        # 打包后：优先 exe 同级 prompts\，便于用户编辑
        return Path(sys.executable).resolve().parent / "prompts"
    root = Path(__file__).resolve().parent.parent
    return root / "prompts"  # 不存在也没关系，走默认回退


_cache: dict[str, Optional[str]] = {}


def refresh() -> None:
    """清空缓存（运行中修改提示词后需要重启才会重新加载）。"""
    _cache.clear()


def _read_clean(name: str) -> str:
    """读取并清洗提示词文件；失败返回 None。"""
    path = prompts_dir() / name
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        log.warning("读取提示词 %s 失败: %s", path, exc)
        return None
    raw = _COMMENT_BLOCK.sub("", raw)
    raw = _HASH_LINE.sub("", raw)
    # 压缩多余空行
    lines = [ln.rstrip() for ln in raw.splitlines()]
    out_lines: list[str] = []
    prev_blank = False
    for ln in lines:
        blank = not ln.strip()
        if blank and prev_blank:
            continue
        out_lines.append(ln)
        prev_blank = blank
    text = "\n".join(out_lines).strip()
    return text or None


def get(name: str) -> str:
    """返回提示词文本（含占位符）。优先读文件，缺失回退内置默认。"""
    if name not in _cache:
        text = _read_clean(name)
        if text is None:
            text = DEFAULTS.get(name)
            if text is None:
                raise KeyError(name)
            log.info("提示词文件 %s 缺失，使用内置默认", name)
        _cache[name] = text
    return _cache[name]


def fill(template: str, **placeholders: str) -> str:
    """把 {key} 占位符替换为实际值（不引入 format 语法冲突）。"""
    for key, value in placeholders.items():
        template = template.replace("{" + key + "}", value)
    return template


def normal_prompt() -> str:
    return get("translation_normal.md")


def spicy_prompt() -> str:
    return get("translation_spicy.md")


def reply_prompt() -> str:
    return get("reply.md")
