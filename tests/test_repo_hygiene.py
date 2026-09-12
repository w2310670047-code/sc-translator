"""仓库卫生回归：防止把本机运行痕迹误提交（曾真实发生过一次）。

背景：一次 `git add -A` 把 DSH 视觉路由的截图目录 `.dsh-vision-router/` 一起提交了
（本地agent截图落盘在项目根，且当时 .gitignore 没覆盖），已重写历史清除。
这个测试用来保证**同类事故不再发生**。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 绝不允许出现在仓库里的路径模式（本机痕迹 / 凭据 / 构建产物）
FORBIDDEN = [
    r"(^|/)\.dsh-vision-router/",
    r"(^|/)\.agent-teams/",
    r"(^|/)data/",
    r"(^|/)logs/",
    r"(^|/)\.venv/",
    r"(^|/)dist/",
    r"(^|/)build/",
    r"(^|/)\.gh_token$",
    r"(^|/)tokens\.txt$",
    r"present\.png$",
    r"\.log$",
]

# 允许存在的二进制/图片（随包资源）
ALLOWED_IMAGES = {
    "assets/icon.ico",
    "assets/sc_glossary.ini",
}


def _tracked_files() -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None          # 不是 git 仓库（例如解压后的发行包）→ 跳过
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def test_no_local_traces_are_tracked():
    files = _tracked_files()
    if files is None:
        return
    bad: list[str] = []
    for f in files:
        for pat in FORBIDDEN:
            if re.search(pat, f.replace("\\", "/")):
                bad.append(f)
                break
    assert not bad, "本机痕迹/构建产物被提交了：" + ", ".join(bad)


def test_only_whitelisted_binaries_are_tracked():
    """图片等二进制文件只允许白名单内的（防止截图/缓存混入）。"""
    files = _tracked_files()
    if files is None:
        return
    binary_ext = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".exe", ".dll", ".zip", ".pyc")
    bad = [
        f
        for f in files
        if f.lower().endswith(binary_ext) and f.replace("\\", "/") not in ALLOWED_IMAGES
    ]
    assert not bad, "未在白名单里的二进制文件被提交了：" + ", ".join(bad)


def test_local_user_paths_are_not_committed():
    """已跟踪文本文件里不允许出现本机用户目录路径（Windows 用户名泄漏）。"""
    files = _tracked_files()
    if files is None:
        return
    hits: list[str] = []
    for f in files:
        p = ROOT / f
        if p.suffix.lower() in (".png", ".ico", ".zip", ".exe", ".dll", ".pyc"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"[Cc]:\\Users\\(?!<)[A-Za-z0-9_.-]+", text) or re.search(
            r"/Users/(?!<)[A-Za-z0-9_.-]+/", text
        ):
            hits.append(f)
    assert not hits, "这些文件泄漏了本机用户目录路径：" + ", ".join(hits)


def test_gitignore_covers_the_vision_router_dir():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="ignore")
    for need in (".dsh-vision-router/", "data/", "dist/", "build/", ".venv/"):
        assert need in gi, f".gitignore 缺少 {need}"
