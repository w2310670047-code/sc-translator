"""设置存取（JSON，位于 %APPDATA%\\SCTranslator\\settings.json）。

API Key 不写入 settings.json，单独经 DPAPI 加密存放在 api_key.bin。
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

from .paths import api_key_file, settings_file
from . import secrets

log = logging.getLogger(__name__)

# 常见 OpenAI 兼容服务预设（可自行改 api_base）
PROVIDER_PRESETS = {
    "DeepSeek": "https://api.deepseek.com",
    "OpenAI": "https://api.openai.com/v1",
    "自定义 OpenAI 兼容": "",
}

API_KEY_PLAINTEXT_FALLBACK = "_plaintext"

# 旧版聊天正则（要求玩家名带括号），检测到则升级为新默认
LEGACY_CHAT_PATTERN = r"\[[^\]\n]{0,24}\]\s*\([^()\n]{1,48}\)\s*[:：]\s*.+"
DEFAULT_CHAT_PATTERN = (
    r"^\s*(?:\[[^\]\n]{0,24}\]\s*)?(?:\([^()\n]{1,48}\)|[^:：()\n]{1,64})\s*[:：]\s*.+"
)


@dataclass
class Settings:
    # ---- 翻译 API ----
    api_provider: str = "DeepSeek"
    api_base: str = "https://api.deepseek.com"
    model: str = ""
    source_lang: str = "auto"          # 源语言提示: auto/en/ja/ko/zh
    target_lang: str = "zh-CN"         # 目标语言
    spicy_mode: bool = False           # 嘴臭模式：开启=译文用嘴臭提示词；关闭=正常提示词
    # ---- 采样与 OCR ----
    sample_ms: int = 220               # 变化时采样/截图间隔(ms)
    idle_probe_s: float = 0            # (兼容遗留字段，不再使用)
    stable_frames: int = 2             # 需连续几帧一致才提交翻译(吸收 OCR 抖动)
    max_text_chars: int = 800          # 超过则忽略(避免误框整屏导致的超大文本)
    ocr_interval_s: float = 1.5        # 活跃间隔(秒)：最近有文字时两次 OCR 最小间隔
    ocr_idle_s: float = 5.0            # 空闲退避(秒)：连续无文字时两次 OCR 最小间隔
    text_gate: bool = True             # 文本存在预判门：明显无字形的变化不跑 OCR
    idle_sample_s: float = 1.5         # 画面静止时的巡检间隔(秒)：没变化就慢速签名比对省 CPU
    chat_mode: bool = False            # SC聊天模式：只翻译形如 [频道](玩家):正文 的玩家消息
    chat_pattern: str = DEFAULT_CHAT_PATTERN  # 聊天行匹配正则
    # ---- 框选区域 (logical 为 Qt 全局坐标；physical 为 mss 物理像素) ----
    region: Optional[dict] = None      # {logical:{x,y,w,h}, physical:{left,top,width,height}, dpr, label}
    local_enabled: bool = False        # 本地GGUF离线翻译(实验，默认 Qwen2.5-1.5B int4)
    local_model_path: str = ""         # GGUF 路径(留空用 data/models/ 下的默认文件名)
    local_gpu_layers: int = -1         # -1=全部层上GPU；0=纯CPU；N=前N层上GPU（控制显存占用）
    local_cpu_threads: int = 4         # GPU卸载时留给 CPU 的线程数（小即可，省 CPU）
    dict_enabled: bool = False         # SC静态UI词典(聊天场景不需要，默认关闭)
    dict_path: str = ""                # bilingual 词典文件(每行 英文=中文)；留空关闭
    glossary_enabled: bool = True      # SC术语表：专名预替换(Stanton→斯坦顿星系等)
    glossary_path: str = ""            # 术语表文件(每行 英文=中文)；留空仅用内置默认
    # ---- 悬浮框 ----
    always_show: bool = True           # 常态显示翻译框
    click_through: bool = True         # 鼠标穿透
    auto_hide_sec: int = 0             # 0=不自动隐藏；>0 空闲 N 秒后淡出
    show_original: bool = True         # 显示原文
    font_size: int = 14
    opacity: int = 92                  # 0-100 悬浮框背景不透明度
    max_entries: int = 120             # 悬浮框保留最大译文条数(超出滚动)
    # ---- 回话助手 ----
    reply_enabled: bool = False
    reply_target: str = "English"      # English / Japanese / Korean
    auto_copy_reply: bool = True
    # ---- 游戏聊天码（中文 -> 游戏内 @码，需装带社区输入法支持的汉化）----
    gamecode_ini_path: str = ""        # 汉化后的 global.ini；留空自动检测
    gamecode_auto_copy: bool = True    # 编码结果自动进剪贴板（便于游戏内 Ctrl+V）
    # ---- 界面 ----
    theme: str = "dark"
    log_level: str = "INFO"
    overlay_geometry: Optional[dict] = None  # 悬浮框位置 {x,y,w,h}(logical)
    pin_single_core: bool = False            # 纯文字翻译场景无需单核绑定(原屏幕OCR用)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Settings":
        known = {f.name for f in fields(cls)}
        s = cls()
        for k, v in d.items():
            if k in known and v is not None:
                setattr(s, k, v)
        return s

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def load(self) -> "Settings":
        p = settings_file()
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                merged = Settings.from_dict(data)
                # 仅当文件里确实存了这些键才覆盖默认；旧版聊天正则自动升级为新默认
                for f in fields(Settings):
                    if f.name in data and getattr(merged, f.name) is not None:
                        if f.name == "chat_pattern" and getattr(merged, f.name) == LEGACY_CHAT_PATTERN:
                            continue
                        setattr(self, f.name, getattr(merged, f.name))
            except Exception as exc:  # noqa: BLE001
                log.warning("读取设置失败，使用默认值: %s", exc)
        return self

    def save(self) -> None:
        p = settings_file()
        try:
            p.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("保存设置失败: %s", exc)

    # ---------------- API Key（DPAPI） ----------------
    def load_api_key(self) -> str:
        p = api_key_file()
        if not p.exists():
            return ""
        try:
            raw = p.read_bytes()
            if raw.startswith(API_KEY_PLAINTEXT_FALLBACK.encode()):
                return raw[len(API_KEY_PLAINTEXT_FALLBACK):].decode("utf-8")
            return secrets.unprotect(raw).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            log.warning("读取 API Key 失败: %s", exc)
            return ""

    def save_api_key(self, key: str) -> None:
        key = (key or "").strip()
        p = api_key_file()
        try:
            if not key:
                p.unlink(missing_ok=True)
                return
            if secrets.dpapi_available():
                p.write_bytes(secrets.protect(key.encode("utf-8")))
            else:
                # 非 Windows / DPAPI 不可用时的兜底（明文，带标记）
                p.write_bytes(API_KEY_PLAINTEXT_FALLBACK.encode() + key.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            log.warning("保存 API Key 失败: %s", exc)

    # 便于给测试使用
    @staticmethod
    def with_home(tmp_home: Path) -> "Settings":
        import os

        os.environ["SC_TRANSLATOR_HOME"] = str(tmp_home)
        return Settings().load()
