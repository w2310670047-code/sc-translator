"""诊断：HTTP 200 但 content 为空时，DeepSeek 到底把内容放在哪里。

打印原始 JSON（选择性地打印 reasoning_content / content / finish_reason），
并对比 thinking 开关的效果。
"""

import json
import sys

sys.path.insert(0, r"E:\SC Translator")
from sc_translator.settings import Settings

import requests

s = Settings().load()
key = s.load_api_key()
base = (s.api_base or "https://api.deepseek.com").rstrip("/")
if not base.endswith("/v1"):
    base += "/v1"
print("base:", base)
print("key 已配置:", bool(key), "| settings.model:", repr(s.model))

models = requests.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=20).json()
ids = [m["id"] for m in models.get("data", [])]
print("可用模型:", ids)


def probe(model: str, thinking_disabled: bool):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "把下面这句翻译成中文，只输出译文：Hello, this is a translation test."}],
        "temperature": 0.2,
        "stream": False,
    }
    if thinking_disabled:
        payload["thinking"] = {"type": "disabled"}
    r = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    print(f"\n=== model={model} thinking_disabled={thinking_disabled} -> HTTP {r.status_code} ===")
    try:
        data = r.json()
    except Exception:
        print("  非 JSON 响应:", r.text[:300])
        return
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    print("  finish_reason :", choice.get("finish_reason"))
    print("  usage         :", data.get("usage"))
    print("  content       :", repr((msg.get("content") or "")[:120]))
    rc = msg.get("reasoning_content")
    if rc is not None:
        print("  reasoning_content 长度:", len(rc), " 开头:", repr(rc[:80]))
    else:
        print("  reasoning_content: (无此字段)")
    print("  message keys  :", list(msg.keys()))


for model in ids or ["deepseek-flash"]:
    probe(model, thinking_disabled=False)
    probe(model, thinking_disabled=True)
