"""把发布附件补传到指定 Release（网络恢复后随时可重跑，幂等）。

用法：
    python tools/_upload_asset.py v0.4.3 dist/SCTranslator-v0.4.3-win64.zip

- 走 uploads.github.com（GitHub 规定），失败会打印原因并返回非零；
- 若同名附件已存在则跳过（先删旧的再传）；
- 需要环境变量 GH_TOKEN。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request

REPO = "w2310670047-code/sc-translator"
API = "https://api.github.com"


def _headers(extra: dict | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "dsh-upload",
    }
    if extra:
        h.update(extra)
    return h


def api(method: str, path: str):
    req = urllib.request.Request(API + path, method=method, headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body) if body.strip() else {}


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    tag, path = sys.argv[1], sys.argv[2]
    if not os.path.exists(path):
        print(f"文件不存在: {path}")
        return 2
    name = os.path.basename(path)
    local = sha256(path)
    size_mb = os.path.getsize(path) / 1e6
    rel = api("GET", f"/repos/{REPO}/releases/tags/{tag}")
    for a in rel.get("assets", []):
        if a["name"] == name:
            if a.get("digest") == f"sha256:{local}":
                print(f"已存在且摘要一致，跳过：{name}")
                return 0
            print(f"同名附件摘要不同，先删除旧的（id={a['id']}）")
            api("DELETE", f"/repos/{REPO}/releases/assets/{a['id']}")

    url = f"https://uploads.github.com/repos/{REPO}/releases/{rel['id']}/assets?name={name}"
    print(f"上传 {name}（{size_mb:.1f} MB）…", flush=True)
    with open(path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers=_headers({"Content-Type": "application/zip", "Content-Length": str(len(data))}),
    )
    try:
        with urllib.request.urlopen(req, timeout=1800) as resp:
            asset = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"上传失败：{type(exc).__name__}: {exc}")
        return 1
    ok = asset.get("digest") == f"sha256:{local}"
    print(f"上传完成：{asset['name']} digest 一致={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
