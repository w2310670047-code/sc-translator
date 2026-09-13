"""实测 DeepSeek thinking 参数规范（文档站本机不可达，用真实响应当依据）。

矩阵：不带参数 / disabled / enabled / 非法值 / 第三方网关常见写法，
记录 HTTP 状态、content、reasoning_content、reasoning_tokens、finish_reason、耗时。
"""

import sys
import time

sys.path.insert(0, r"E:\SC Translator")

import requests

from sc_translator.settings import Settings

s = Settings().load()
key = s.load_api_key()
base = (s.api_base or "https://api.deepseek.com").rstrip("/")
if not base.endswith("/v1"):
    base += "/v1"

VARIANTS = [
    ("不带 thinking", None),
    ("disabled", {"type": "disabled"}),
    ("enabled", {"type": "enabled"}),
    ("非法 type=off", {"type": "off"}),
    ("空对象 {}", {}),
]

for model in ("deepseek-flash", "deepseek-v4-pro"):
    print(f"\n########## model={model} ##########")
    for label, thinking in VARIANTS:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "只输出译文：Hello, this is a translation test."}],
            "max_tokens": 256,
            "stream": False,
        }
        if thinking is not None:
            payload["thinking"] = thinking
        t0 = time.time()
        try:
            r = requests.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload, timeout=90,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  {label:14} -> 请求异常 {type(exc).__name__}: {exc}")
            continue
        ms = (time.time() - t0) * 1000
        if r.status_code != 200:
            body = r.text[:160].replace("\n", " ")
            print(f"  {label:14} -> HTTP {r.status_code} ({ms:.0f}ms) {body}")
            continue
        d = r.json()
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        usage = d.get("usage") or {}
        rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        print(
            f"  {label:14} -> HTTP 200 ({ms:.0f}ms) content={len(msg.get('content') or '')}字 "
            f"reasoning字段={'有' if 'reasoning_content' in msg else '无'} "
            f"reasoning_tokens={rt} finish={ch.get('finish_reason')} "
            f"completion_tokens={usage.get('completion_tokens')}"
        )
