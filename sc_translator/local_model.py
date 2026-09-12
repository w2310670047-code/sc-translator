"""本地 GGUF 翻译引擎（llama-cpp-python，CPU/GPU 均可）。

实验用途：DeepSeek API 往返太慢时的离线替代。
注意：进程被 CPU 亲和钉在单个小核时，务必先调用 cpu_pin.allow_current_thread()
把当前(翻译 worker)线程放到全部允许核上，否则本地推理会被单核拖到更慢。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from . import prompts as prompt_files

log = logging.getLogger(__name__)

_lock = threading.Lock()
_instance = None
_instance_key = ""
_gpu_layers = -1      # 资源控制：-1 全GPU / 0 纯CPU / N 前N层GPU
_cpu_threads = 4


def configure(gpu_layers: int = -1, cpu_threads: int = 4) -> None:
    """本地推理资源控制。改动后下次加载模型生效（模型已在内存则需重启翻译触发重载）。"""
    global _gpu_layers, _cpu_threads
    _gpu_layers = int(gpu_layers)
    _cpu_threads = max(1, int(cpu_threads))


class LocalModel:
    def __init__(self, path: str, n_ctx: int = 1024, n_threads: int = 4, n_gpu_layers: int = -1) -> None:
        from llama_cpp import Llama

        log.info("加载本地模型 %s (ctx=%d threads=%d gpu_layers=%d) ...",
                 path, n_ctx, n_threads, n_gpu_layers)
        t0 = time.monotonic()
        self.llm = Llama(
            model_path=path,
            n_ctx=n_ctx,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            n_batch=256,
            verbose=False,
        )
        # GPU(Vulkan/CUDA)首句要编译着色器：加载时预热，避免游戏里第一句卡顿
        try:
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "Hi"}], max_tokens=1, temperature=0
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("模型预热失败(忽略): %s", exc)
        log.info("模型加载完成(含预热)，耗时 %.1fs", time.monotonic() - t0)

    def generate(self, system: str, user: str, temperature: float = 0.3,
                 max_tokens: int = 256) -> str:
        out = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            return (out["choices"][0]["message"]["content"] or "").strip()
        except Exception:  # noqa: BLE001
            return ""


def get_model(path: str, n_ctx: int = 1024) -> LocalModel:
    global _instance, _instance_key, _gpu_layers, _cpu_threads
    key = f"{path}|{n_ctx}|gpu={_gpu_layers}|t={_cpu_threads}"
    with _lock:
        if _instance is not None and _instance_key == key:
            return _instance
        _instance = LocalModel(path, n_ctx=n_ctx, n_threads=_cpu_threads, n_gpu_layers=_gpu_layers)
        _instance_key = key
        return _instance


_LANG_HINT = {
    "auto": "可能是英文、日文或韩文（多为游戏界面/玩家聊天）",
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "zh": "简体中文",
}

DEFAULT_MODEL_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
    + DEFAULT_MODEL_FILE
)


def default_model_path() -> str:
    from .paths import home_dir

    d = home_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return str(d / DEFAULT_MODEL_FILE)


def model_ready(path: str) -> bool:
    try:
        import os

        return bool(path) and os.path.exists(path) and os.path.getsize(path) > 50 * 1024 * 1024
    except Exception:  # noqa: BLE001
        return False


def download_model(path: str, progress_cb=None, timeout_s: int = 1800) -> bool:
    """流式下载默认 GGUF 到 path。progress_cb(done_mb, total_mb)。"""
    import os

    import requests

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".part"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with requests.get(DEFAULT_MODEL_URL, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length") or 0)
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if progress_cb is not None:
                        progress_cb(done / 1024 / 1024, total / 1024 / 1024 if total else None)
        os.replace(tmp, path)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("模型下载失败: %s", exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:  # noqa: BLE001
            pass
        return False


def _system(target: str = "简体中文", src: str = "auto") -> str:
    hint = _LANG_HINT.get(src, "英文")
    return prompt_files.fill(prompt_files.normal_prompt(), src=hint, target=target)


_CHAT_KEEP_LOCAL = "若输入含 [频道](玩家): 前缀，请保留前缀与名字只译正文，只输出一行译文。"


def translate_line_local(path: str, text: str, source_lang: str = "auto",
                         target_lang: str = "zh-CN", keep_chat_prefix: bool = False) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    from .ocr import _cjk_ratio

    # 术语表预替换（专名先中文化，本地模型同样生效）
    from . import glossary

    if target_lang.lower().startswith("zh") and glossary.configured():
        text = glossary.apply(text)
    if target_lang.lower().startswith("zh") and _cjk_ratio(text) > 0.55:
        return text
    # 词典优先（本地模型也不浪费推理）
    from . import gamedict

    dhit = gamedict.lookup(text)
    if dhit:
        return dhit
    target = "简体中文" if target_lang.lower().startswith("zh") else target_lang
    model = get_model(path)
    system = _system(target=target, src=source_lang)
    if keep_chat_prefix:
        system += "\n" + _CHAT_KEEP_LOCAL
    return model.generate(system, text, max_tokens=max(96, int(len(text) * 1.8)))


def translate_lines_batch_local(path: str, texts: list[str], source_lang: str = "auto",
                                target_lang: str = "zh-CN", keep_chat_prefix: bool = False) -> list[str]:
    """本地模型暂不支持编号批量提示的可靠输出，逐条翻译保持对齐。"""
    return [translate_line_local(path, t, source_lang, target_lang, keep_chat_prefix) for t in texts]


_REPLY_TARGET = {"English": "English", "Japanese": "Japanese", "Korean": "Korean"}


def translate_reply_local(path: str, text: str, target_lang: str = "English") -> str:
    text = (text or "").strip()
    if not text:
        return ""
    target = _REPLY_TARGET.get(target_lang, target_lang)
    system = prompt_files.fill(prompt_files.reply_prompt(), target=target)
    model = get_model(path)
    return model.generate(system, text, temperature=0.4, max_tokens=max(128, int(len(text) * 3)))
