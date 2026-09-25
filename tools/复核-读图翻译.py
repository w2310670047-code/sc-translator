"""读图翻译（方案 C）真机复核：真实 API、一次请求，验证官方 vision 格式能用。

用法：
    python tools/复核-读图翻译.py [--lines N]

检查项：
1. 请求被接受（HTTP 200，没有格式类 400）；
2. 返回能按 `序号. 原文 => 译文` 解析成 [(原文, 译文)]；
3. 打印耗时与原始输出长度（原始输出同时写进 data\\logs\\exchange.log）。

说明：这会花一次真实请求（图片 token 官方上限 1024/张，detail=low 会缩到 512×512）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

LINES = [
    "[GLOBAL] Crispy Packs:890 ready to go",
    "Quantum travel to Crusader",
    "Bounty mission updated",
    "[GLOBAL] Amygdalaa: pull up, valakkar near Pyro",
    "890 jump needs an escort",
    "Party invite accepted",
]


def make_image(n: int) -> np.ndarray:
    img = np.full((282, 499, 3), 18, dtype=np.uint8)
    y = 16
    for t in LINES[:n]:
        cv2.putText(img, t, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (215, 215, 215), 1, cv2.LINE_AA)
        y += 28
    return img


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lines", type=int, default=6)
    args = ap.parse_args()

    from sc_translator import DEFAULT_MODEL
    from sc_translator.settings import Settings
    from sc_translator.translate.client import ClientOptions, OpenAiCompatClient

    s = Settings().load()
    key = s.load_api_key()
    model = s.model or DEFAULT_MODEL
    print(f"服务商 base={s.api_base} 模型={model} 嘴臭={s.spicy_mode} Key={'已配置' if key else '未配置'}", flush=True)
    if not key:
        print("未配置 API Key，无法复核", flush=True)
        return 2

    img = make_image(max(1, min(args.lines, len(LINES))))
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        print("PNG 编码失败", flush=True)
        return 1
    png = buf.tobytes()
    print(f"图片 {img.shape[1]}x{img.shape[0]}，PNG {len(png) / 1024:.1f} KB", flush=True)

    client = OpenAiCompatClient(ClientOptions(api_base=s.api_base, api_key=key, model=model))
    t0 = time.time()
    try:
        pairs = client.translate_image(png, target_lang="zh-CN", max_lines=args.lines)
    except Exception as exc:  # noqa: BLE001
        print(f"失败：{type(exc).__name__}: {exc}", flush=True)
        return 1
    ms = int((time.time() - t0) * 1000)

    print(f"耗时 {ms}ms，解析出 {len(pairs)} 行：", flush=True)
    for i, (src, dst) in enumerate(pairs, 1):
        print(f"  {i}. 原文={src!r}  译文={dst!r}", flush=True)

    empty_src = sum(1 for src, _ in pairs if not src)
    ok = bool(pairs) and empty_src == 0
    if empty_src:
        print(f"注意：有 {empty_src} 行没解析出原文（模型没按 `原文 => 译文` 输出）", flush=True)
    print("结论:", "通过" if ok else "未通过", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
