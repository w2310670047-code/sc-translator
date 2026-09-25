"""当 github.com:443 不通时，用 GitHub REST API 把本地提交推上去。

仅使用 api.github.com（国内通常可达），流程：
  1. 读远端 main 的 commit/tree
  2. 为每个改动文件创建 blob
  3. 基于远端 tree 创建新 tree
  4. 创建 commit（父提交 = 远端 main）
  5. 更新 refs/heads/main

用法：python tools/_api_push.py <local_commit_sha> <base_ref_sha>
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.request

REPO = "wangcangxing/sc-translator"
API = "https://api.github.com"
TOKEN = os.environ["GH_TOKEN"]


def call(method: str, path: str, payload: dict | None = None):
    url = API + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "dsh-api-push")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败: {out.stderr}")
    return out.stdout


def main() -> int:
    local = sys.argv[1]
    base_sha = sys.argv[2]
    message = git("log", "-1", "--pretty=%B", local).strip()

    changed = [p for p in git("diff", "--name-only", f"{base_sha}..{local}").splitlines() if p]
    deleted = [p for p in git("diff", "--name-only", "--diff-filter=D", f"{base_sha}..{local}").splitlines() if p]
    print(f"改动 {len(changed)} 个文件（删除 {len(deleted)}）")

    remote_commit = call("GET", f"/repos/{REPO}/git/commits/{base_sha}")
    base_tree = remote_commit["tree"]["sha"]

    entries = []
    for path in changed:
        if path in deleted:
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
            continue
        raw = subprocess.run(
            ["git", "show", f"{local}:{path}"], capture_output=True
        ).stdout                       # 二进制安全
        blob = call("POST", f"/repos/{REPO}/git/blobs",
                    {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print(f"  blob {path} -> {blob['sha'][:8]}")

    tree = call("POST", f"/repos/{REPO}/git/trees", {"base_tree": base_tree, "tree": entries})
    commit = call("POST", f"/repos/{REPO}/git/commits",
                  {"message": message, "tree": tree["sha"], "parents": [base_sha]})
    print(f"新提交 {commit['sha'][:8]}")

    # 已存在同名提交时（例如 git push 其实成功过），直接对齐 ref
    cur = call("GET", f"/repos/{REPO}/git/ref/heads/main")
    if cur["object"]["sha"] == commit["sha"]:
        print("远端已经是这个提交")
        return 0
    if cur["object"]["sha"] != base_sha:
        print(f"警告：远端 main 已前进到 {cur['object']['sha'][:8]}，仍按 base={base_sha[:8]} 提交")
    call("PATCH", f"/repos/{REPO}/git/refs/heads/main", {"sha": commit["sha"], "force": False})
    print("已更新 refs/heads/main")
    return 0


if __name__ == "__main__":
    sys.exit(main())
