"""OpenAI 兼容（DeepSeek 等）翻译客户端。"""

from __future__ import annotations

import base64
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from .. import DEFAULT_MODEL
from .. import prompts as prompt_files
from .. import exchange_log
from .. import glossary
from ..textutil import cjk_ratio as _cjk_ratio
from .cache import TranslationCache

log = logging.getLogger(__name__)

LANG_HINT = {
    "auto": "可能是英文、日文或韩文（多为游戏界面/玩家聊天）",
    "en": "英文",
    "ja": "日文",
    "ko": "韩文",
    "zh": "简体中文",
}

# 翻译提示词来自 prompts/*.md（可编辑；缺失时回退内置默认）

_RETRY_STATUS = {429, 500, 502, 503, 504, 529}

# SC 聊天模式：保持 "[频道](玩家):" 前缀与频道/玩家名原样，只译正文
_CHAT_KEEP_TMPL = (
    "\n格式要求（聊天模式）：如果输入形如 [频道](玩家名):正文 的聊天行，"
    "请把 [频道] 与 (玩家名) 前缀、频道名和玩家名原样保留（不翻译），"
    "只把冒号后的正文翻译成{target}，整体只输出这一行译文。"
)

_NUMBERED_TMPL = (
    "\n批量翻译：把上面的 N 行逐行翻译成{target}。"
    "必须按顺序每行只输出一个译文，行首带原编号如 “3. 译文”，不要输出编号之外的任何文字或解释。"
)

#: 方案 C：让多模态模型直接读图（识别 + 翻译一次完成）。输出契约刻意写死，
#: 因为下游要把「原文/译文」分别放进浮窗（同 key 原地更新、可显示原文）。
#: 格式取自官方文档 https://api-docs.deepseek.com/zh-cn/guides/vision
_VISION_SYSTEM_TMPL = """你是游戏截图翻译引擎：先识别图片中的文字，再逐行翻译成{target}。

输出规则（严格遵守，覆盖其它习惯）：
1) 每行一条，格式为 `序号. 原文 => 译文`（`=>` 两侧各一个空格）；
2) 序号从 1 开始，按图中从上到下的顺序，不合并、不拆分行；
3) 只输出这些行：不要解释、不要标题、不要代码块围栏、不要额外说明；
4) 玩家名/地名/专有名词保留原文或用通用译名；聊天语气要口语化；
5) 原本已经是{target}的行，译文位置照原样重复一遍。"""


def parse_vision_pairs(raw: str, max_lines: int = 40) -> list[tuple[str, str]]:
    """解析模型输出的 ``序号. 原文 => 译文`` → ``[(原文, 译文)]``。

    容错：兼容 ``=>`` / ``→`` / ``⇒``；缺分隔符时把整行当译文（原文留空）——
    宁可退化显示，也不因为格式抖动丢掉整批内容。
    """
    out: list[tuple[str, str]] = []
    for ln in (raw or "").splitlines():
        s = ln.strip().strip("`")
        if not s or s.startswith("```"):
            continue
        s = re.sub(r"^\s*\d+\s*[.、:：)]\s*", "", s)      # 序号可有可无
        for sep in ("=>", "→", "⇒", "＝＞"):
            if sep in s:
                src, _, dst = s.partition(sep)
                out.append((src.strip().strip('"“”\'`'), dst.strip().strip('"“”\'`')))
                break
        else:
            out.append(("", s))
        if len(out) >= max_lines:
            break
    # 只要有一行带原文，就把"没分隔符的行"当成模型的说明文字丢掉；
    # 若一行都没有分隔符（模型只给了译文），则保留它们——宁可退化也不丢内容。
    with_src = [p for p in out if p[0]]
    return with_src if with_src else out


class ApiError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


# ---------------------------------------------------------------- 进程级复用
# 截图翻译每按一次热键都会新建一个客户端；如果每轮都重新探测 /models 定前缀、
# 重新建 TLS 连接，实测每次要多花 1~4.5 秒（日志里 4395ms / 1960ms 各一次）。
# 前缀按 base 缓存在进程级、连接用共享 Session 保持长连接，这两笔开销就没了。
_PREFIX_CACHE: dict[str, str] = {}
_PREFIX_LOCK = threading.Lock()
_SESSION: Optional[requests.Session] = None
_SESSION_LOCK = threading.Lock()


def shared_session() -> requests.Session:
    """进程级共享 Session：保持 TCP/TLS 长连接，省掉每次热键的握手。

    说明：会话可能被截图翻译线程与回话线程共用。这里不用 cookie，连接池
    本身是线程安全的，与"客户端长期存活"的既有行为一致。
    """
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None:
            _SESSION = requests.Session()
        return _SESSION


@dataclass
class ClientOptions:
    api_base: str = "https://api.deepseek.com"
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_s: int = 90
    max_retries: int = 3
    retry_base_s: float = 0.6
    spicy: bool = False  # 嘴臭模式：开启则译文使用嘴臭提示词（与正常译文分开缓存）
    # 供测试注入传输层；默认用 requests
    post: Optional[Callable] = None
    get: Optional[Callable] = None


class OpenAiCompatClient:
    def __init__(self, opts: Optional[ClientOptions] = None, cache: Optional[TranslationCache] = None,
                 session: Optional[requests.Session] = None) -> None:
        self.opts = opts or ClientOptions()
        self._no_thinking = False      # 网关拒绝 thinking 参数后置位，之后不再发送
        self.cache = cache
        self._session = session or shared_session()
        self._prefix_lock = threading.Lock()
        self._prefix: Optional[str] = None  # 实际可用前缀，如 .../v1
        self._log = logging.getLogger(__name__ + ".OpenAiCompatClient")

    # ---------- 传输 ----------
    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.opts.api_key:
            h["Authorization"] = f"Bearer {self.opts.api_key}"
        return h

    def _do_post(self, url: str, payload: dict) -> requests.Response:
        if self.opts.post:
            return self.opts.post(url, payload=payload, headers=self._headers())
        return self._session.post(url, json=payload, headers=self._headers(), timeout=self.opts.timeout_s)

    def _do_get(self, url: str) -> requests.Response:
        if self.opts.get:
            return self.opts.get(url, headers=self._headers())
        return self._session.get(url, headers=self._headers(), timeout=self.opts.timeout_s)

    def base_url(self) -> str:
        b = (self.opts.api_base or "").strip().rstrip("/")
        if not b:
            raise ApiError("未填写 API 地址(api_base)")
        return b

    def resolve_prefix(self) -> str:
        """找到可用的 API 前缀：优先 {base}，失败且不含 /v1 时尝试 {base}/v1。

        结果按 base 缓存在**进程级**（不是每个客户端各自缓存）：按需截图翻译
        每次热键都会新建客户端，若每轮都探测一次 /models，实测每次白等 1~4.5 秒。
        换服务商=换 base 字符串，会自然重新探测。
        """
        with self._prefix_lock:
            if self._prefix is not None:
                return self._prefix
        base = self.base_url()
        with _PREFIX_LOCK:
            cached = _PREFIX_CACHE.get(base)
        if cached:
            with self._prefix_lock:
                self._prefix = cached
            return cached
        candidates = [base]
        if not base.endswith("/v1"):
            candidates.append(base + "/v1")
        last_err: Optional[Exception] = None
        for c in candidates:
            try:
                resp = self._do_get(c + "/models")
                if resp.status_code < 400:
                    with self._prefix_lock:
                        self._prefix = c
                    with _PREFIX_LOCK:
                        _PREFIX_CACHE[base] = c
                    self._log.info("API 前缀确定为: %s", c)
                    return c
                last_err = ApiError(f"GET {c}/models -> HTTP {resp.status_code}", resp.status_code)
            except requests.RequestException as exc:
                last_err = exc
        raise ApiError(f"无法访问模型列表({self.base_url()}/models): {last_err}")

    def list_models(self) -> list[str]:
        prefix = self.resolve_prefix()
        resp = self._do_get(prefix + "/models")
        if resp.status_code >= 400:
            raise ApiError(f"获取模型列表失败 HTTP {resp.status_code}", resp.status_code)
        try:
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception as exc:  # noqa: BLE001
            raise ApiError(f"模型列表解析失败: {exc}") from exc

    # ---------- 翻译 ----------
    #: 默认开启 Thinking 的模型族：翻译不需要思考（会让 content 为空/变慢/双倍计费）
    # 官方文档：DeepSeek 模型思考模式**默认打开**（effort 默认 high），因此按厂商前缀判断更稳；
    # 若某个网关/模型不接受该参数，会 400，我们自动去掉参数重试（见 _chat）。
    THINKING_MODELS = ("deepseek", "thinking")

    @classmethod
    def needs_thinking_off(cls, model: str) -> bool:
        # 用"包含"而不是"前缀"：网关常带前缀（如 openrouter/deepseek-v4-pro）
        name = (model or "").lower()
        if not name:
            return False
        return any(token in name for token in cls.THINKING_MODELS)

    @staticmethod
    def _empty_diag(data: dict, payload: dict) -> str:
        """把"为什么空"写进日志：模型、finish_reason、思考 token、输出预算、用户文本。"""
        try:
            choice = (data.get("choices") or [{}])[0]
            finish = choice.get("finish_reason")
            usage = data.get("usage") or {}
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            user_last = ""
            for m in reversed(payload.get("messages", [])):
                if m.get("role") == "user":
                    user_last = str(m.get("content", ""))[:120]
                    break
            return (
                f"model={payload.get('model')!r} finish_reason={finish!r} "
                f"max_tokens={payload.get('max_tokens')} reasoning_tokens={reasoning} "
                f"thinking={payload.get('thinking')} user_text={user_last!r}"
            )
        except Exception:  # noqa: BLE001
            return f"model={payload.get('model')!r}（诊断信息解析失败）"

    @staticmethod
    def _empty_hint(data: dict) -> str:
        """给用户看的原因（区分"思考吃满预算"与其它情况）。"""
        try:
            choice = (data.get("choices") or [{}])[0]
            finish = choice.get("finish_reason")
            usage = data.get("usage") or {}
            reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
            if finish == "length" or reasoning:
                return (
                    f"模型把输出预算花在思考上了（reasoning_tokens={reasoning}，"
                    f"finish_reason={finish}），已自动改用“关闭思考”重试仍未成功。"
                )
            if finish:
                return f"finish_reason={finish}。"
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _chat(self, messages: list[dict], temperature: float = 0.3, max_tokens: int = 512) -> str:
        prefix = self.resolve_prefix()
        model = self.opts.model or DEFAULT_MODEL
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        # deepseek-v4* / deepseek-flash 等默认开启 Thinking：
        # 思考会吃掉 max_tokens 导致 content 为空（HTTP 200 但没内容），实时翻译必须显式关闭。
        # 见 https://api-docs.deepseek.com/guides/thinking_mode
        thinking_off = self.needs_thinking_off(model) and not self._no_thinking
        if thinking_off:
            payload["thinking"] = {"type": "disabled"}
        last: Optional[Exception] = None
        tried_force_off = thinking_off
        for attempt in range(self.opts.max_retries + 1):
            try:
                resp = self._do_post(prefix + "/chat/completions", payload)
                if resp.status_code == 200:
                    data = resp.json()
                    content = ""
                    try:
                        content = data["choices"][0]["message"].get("content") or ""
                    except Exception:  # noqa: BLE001
                        pass
                    content = content.strip()
                    if content:
                        # 记录返回内容（诊断乱码/编码问题用，repr 可看不可见字符）
                        log.debug("API 返回内容 len=%d repr=%.220r", len(content), content)
                        return content

                    diag = self._empty_diag(data, payload)
                    if not tried_force_off and not self._no_thinking:
                        # 兜底：本次没关思考（可能是没见过的模型名），关掉再试一次
                        tried_force_off = True
                        payload["thinking"] = {"type": "disabled"}
                        log.warning("模型返回空内容，改用 thinking=disabled 重试：%s", diag)
                        continue
                    log.warning("模型返回空内容(HTTP 200)：%s", diag)
                    raise ApiError(
                        "模型返回了空内容（HTTP 200）："
                        + self._empty_hint(data)
                        + "可在主窗口点“测试”，或改用 deepseek-flash / deepseek-v4-pro 以外的模型再试。",
                        200,
                    )
                if resp.status_code in (400, 422) and "thinking" in payload and "thinking" in resp.text.lower():
                    # 有些 OpenAI 兼容网关不认识 thinking 参数（实测官方 API 认识，取值 adaptive/enabled/disabled）
                    self._no_thinking = True
                    payload.pop("thinking", None)
                    log.warning("该服务不接受 thinking 参数，去掉后重试：%s", resp.text[:140])
                    continue
                if resp.status_code in _RETRY_STATUS and attempt < self.opts.max_retries:
                    time.sleep(self.opts.retry_base_s * (2 ** attempt))
                    continue
                raise ApiError(f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            except ApiError:
                raise
            except requests.RequestException as exc:
                last = exc
                if attempt < self.opts.max_retries:
                    time.sleep(self.opts.retry_base_s * (2 ** attempt))
        raise ApiError(f"请求失败: {last}")

    def _system(self, target: str = "简体中文", src: str = "auto") -> str:
        hint = LANG_HINT.get(src, "英文")
        base = prompt_files.fill(prompt_files.normal_prompt(), src=hint, target=target)
        if self.opts.spicy:
            base += "\n" + prompt_files.fill(prompt_files.spicy_prompt())
        return base

    def _chat_system(self, target: str = "简体中文", src: str = "auto", keep_chat_prefix: bool = False) -> str:
        base = self._system(target=target, src=src)
        if keep_chat_prefix:
            base += prompt_files.fill(_CHAT_KEEP_TMPL, target=target)
        return base

    def _cache_model(self) -> str:
        parts = [self.opts.model or DEFAULT_MODEL]
        if self.opts.spicy:
            parts.append("#spicy")
        return "".join(parts)

    def translate_line(self, text: str, source_lang: str = "auto", target_lang: str = "zh-CN",
                       keep_chat_prefix: bool = False) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        # 术语表：SC 专名先就地换成中文（Stanton->斯坦顿星系），再走后续，避免 AI 翻错
        if target_lang.lower().startswith("zh") and glossary.configured():
            text = glossary.apply(text)
        # 已经是目标中文的内容直接原样返回，不浪费 API
        if target_lang.lower().startswith("zh") and _cjk_ratio(text) > 0.55:
            return text
        model = self.opts.model or DEFAULT_MODEL
        style = "spicy" if self.opts.spicy else "normal"
        cache_model = self._cache_model() + ("#chat" if keep_chat_prefix else "")
        # 词典优先：静态 UI 词条直接命中，零 API
        if not self.opts.spicy and target_lang.lower().startswith("zh"):
            from .. import gamedict

            dhit = gamedict.lookup(text)
            if dhit:
                exchange_log.record("dict", model, text, out=dhit, style=style, cached=True)
                return dhit
        if self.cache is not None:
            hit = self.cache.get(cache_model, source_lang, text)
            if hit is not None:
                exchange_log.record("realtime", model, text, out=hit, style=style, cached=True)
                return hit
        target = "简体中文" if target_lang.lower().startswith("zh") else target_lang
        messages = [
            {"role": "system", "content": self._chat_system(target=target, src=source_lang, keep_chat_prefix=keep_chat_prefix)},
            {"role": "user", "content": text},
        ]
        # 预算下限给足：思考模型（若没能关闭思考）会先花掉一部分，短句也要留余量
        max_tokens = max(256, min(1024, int(len(text) * 2.5)))
        try:
            out = self._chat(messages, temperature=0.3, max_tokens=max_tokens)
        except ApiError as exc:
            exchange_log.record("realtime", model, text, error=str(exc), style=style)
            raise
        # 清理模型可能附加的引号/前缀；术语表兜底替换漏网英文词条
        out = out.strip().strip('"').strip("“”‘’")
        if target_lang.lower().startswith("zh") and glossary.configured():
            out = glossary.apply(out)
        if self.cache is not None:
            self.cache.put(cache_model, source_lang, text, out)
        exchange_log.record("realtime", model, text, out=out, style=style)
        return out

    def translate_lines_batch(self, texts: list[str], source_lang: str = "auto", target_lang: str = "zh-CN",
                              keep_chat_prefix: bool = False) -> list[str]:
        """一次 API 调用翻译多行（编号行，返回对齐列表）。

        中文化内容直接透传；单行/解析缺失时回退逐条翻译，保证结果与输入一一对应。
        """
        texts = [(t or "").strip() for t in texts]
        results: list[str] = []
        target = "简体中文" if target_lang.lower().startswith("zh") else target_lang
        cache_model = self._cache_model() + ("#chat" if keep_chat_prefix else "")
        style = "spicy" if self.opts.spicy else "normal"
        # 术语表预替换（SC 专名先中文化再送译）
        if target_lang.lower().startswith("zh") and glossary.configured():
            texts = [glossary.apply(t) for t in texts]

        # 先处理“已经是中文”的行 + 命中缓存的行
        todo_idx: list[int] = []
        for i, t in enumerate(texts):
            if not t:
                results.append("")
            elif target_lang.lower().startswith("zh") and _cjk_ratio(t) > 0.55:
                results.append(t)
            elif not self.opts.spicy and target_lang.lower().startswith("zh"):
                from .. import gamedict

                dhit = gamedict.lookup(t)
                if dhit:
                    results.append(dhit)
                elif self.cache is not None:
                    hit = self.cache.get(cache_model, source_lang, t)
                    if hit is not None:
                        results.append(hit)
                    else:
                        results.append("")
                        todo_idx.append(i)
                else:
                    results.append("")
                    todo_idx.append(i)
            elif self.cache is not None:
                hit = self.cache.get(cache_model, source_lang, t)
                if hit is not None:
                    results.append(hit)
                else:
                    results.append("")
                    todo_idx.append(i)
            else:
                results.append("")
                todo_idx.append(i)
        if not todo_idx:
            return results

        model = self.opts.model or DEFAULT_MODEL
        lines = [texts[i] for i in todo_idx]
        numbered = "\n".join(f"{k + 1}. {t}" for k, t in enumerate(lines))
        messages = [
            {"role": "system", "content": self._chat_system(target=target, src=source_lang, keep_chat_prefix=keep_chat_prefix)
             + prompt_files.fill(_NUMBERED_TMPL, target=target)},
            {"role": "user", "content": numbered},
        ]
        max_tokens = min(4096, 256 + int(sum(min(700, len(t) * 2.5) for t in lines)))
        try:
            raw = self._chat(messages, temperature=0.3, max_tokens=max_tokens)
        except ApiError as exc:
            for i in todo_idx:
                exchange_log.record("realtime", model, texts[i], error=str(exc), style=style)
            raise

        parsed: dict[int, str] = {}
        import re

        for ln in raw.splitlines():
            m = re.match(r"^\s*(\d+)\s*[.、:：]\s*(.+)$", ln.strip())
            if m:
                parsed[int(m.group(1))] = m.group(2).strip().strip('"').strip("“”‘’")
        # 回填；缺的行逐条兜底（走单行翻译，含缓存），保证长度一致
        for idx, i in enumerate(todo_idx, start=1):
            out = parsed.get(idx)
            if out is None:
                out = self.translate_line(texts[i], source_lang=source_lang, target_lang=target_lang,
                                          keep_chat_prefix=keep_chat_prefix)
            if target_lang.lower().startswith("zh") and glossary.configured():
                out = glossary.apply(out)
            results[i] = out
            if self.cache is not None:
                self.cache.put(cache_model, source_lang, texts[i], out)
            exchange_log.record("realtime", model, texts[i], out=out, style=style)
        return results

    def translate_image(self, image: bytes, target_lang: str = "zh-CN", *, max_lines: int = 40,
                        detail: str = "low", mime: str = "image/png") -> list[tuple[str, str]]:
        """方案 C：一次请求完成「读图 + 翻译」，返回 ``[(原文, 译文)]``（不经过本地 OCR）。

        官方格式（docs /guides/vision）：``content`` 是块数组，图片走
        ``{"type":"image_url","image_url":{"url":"data:image/png;base64,...","detail":"low"}}``。
        ``detail="low"`` 会把图缩到 512×512——我们的框选通常比这更小，等于零损失而更省 token；
        官方写明**每张图 token 上限 1024**，内联图计入 48 MiB 请求体限制。
        """
        if not image:
            return []
        target = "简体中文" if target_lang.lower().startswith("zh") else target_lang
        b64 = base64.b64encode(image).decode("ascii")
        system = _VISION_SYSTEM_TMPL.replace("{target}", target)
        if self.opts.spicy:
            system += "\n" + prompt_files.fill(prompt_files.spicy_prompt())
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": "识别并翻译这张截图里的所有文字。"},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}", "detail": detail}},
            ]},
        ]
        model = self.opts.model or DEFAULT_MODEL
        style = "spicy" if self.opts.spicy else "normal"
        max_tokens = min(4096, 256 + max(1, max_lines) * 60)
        try:
            raw = self._chat(messages, temperature=0.2, max_tokens=max_tokens)
        except ApiError as exc:
            exchange_log.record("vision", model, f"<image {len(image)}B>", error=str(exc), style=style)
            raise
        pairs = parse_vision_pairs(raw, max_lines=max_lines)
        exchange_log.record("vision", model, f"<image {len(image)}B>", out=raw, style=style)
        if not pairs:
            raise ApiError(
                "模型没有按 `序号. 原文 => 译文` 的格式返回可解析内容"
                "（原始输出已记入 data\\logs\\exchange.log；可先关掉「模型直接读图」用本地 OCR）"
            )
        return pairs

    def translate_reply(self, text: str, target_lang: str = "English", spicy: bool = False) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        target = {"English": "English", "Japanese": "Japanese", "Korean": "Korean"}.get(target_lang, target_lang)
        system = prompt_files.fill(prompt_files.reply_prompt(), target=target)
        if spicy:
            system += (
                "\n风格要求（嘴臭模式已开启）：用" + target
                + "翻成嘴臭版——嘲讽挑衅的竞技垃圾话(trash talk)语气，"
                "可用 ggez/noob/1v1 me/back to lobby 之类说法，"
                "但禁止真正脏话辱骂、人身攻击与歧视内容。"
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]
        model = self.opts.model or DEFAULT_MODEL
        style = "spicy" if spicy else "normal"
        try:
            out = self._chat(messages, temperature=0.4, max_tokens=max(256, int(len(text) * 3)))
        except ApiError as exc:
            exchange_log.record("reply", model, text, error=str(exc), style=style)
            raise
        exchange_log.record("reply", model, text, out=out, style=style)
        return out
