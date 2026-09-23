"""设置存取（JSON，默认位于程序目录下的 data\\settings.json，见 paths.py）。

便携：数据跟着程序目录走；只有当程序被当作已安装包运行（程序目录里找不到随包分发的
run.bat 标记）时才退回 %APPDATA%\\SCTranslator。SC_TRANSLATOR_HOME 可强制重定向。

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
# 注意：key 是**稳定标识**，不要本地化——界面显示名走 i18n（provider.custom）
PROVIDER_PRESETS = {
    "DeepSeek": "https://api.deepseek.com",
    "OpenAI": "https://api.openai.com/v1",
    "custom": "",
}

# 旧版把显示名直接存进了设置，读取时升级为稳定 key
LEGACY_PROVIDER_NAMES = {"自定义 OpenAI 兼容": "custom"}

API_KEY_PLAINTEXT_FALLBACK = "_plaintext"


@dataclass
class Settings:
    # ---- 翻译 API ----
    api_provider: str = "DeepSeek"
    api_base: str = "https://api.deepseek.com"
    model: str = ""
    source_lang: str = "auto"          # 源语言提示: auto/en/ja/ko/zh
    target_lang: str = "zh-CN"         # 目标语言
    spicy_mode: bool = False           # 嘴臭模式：开启=译文用嘴臭提示词；关闭=正常提示词
    # ---- 词典 / 术语表 ----
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
    reply_out_code: bool = False       # 回话：输出中文码行（中译中）
    reply_out_foreign: bool = True     # 回话：输出外文译文行（中译外）
    # ---- 游戏聊天码（中文 -> 游戏内 @码，需装带社区输入法支持的汉化）----
    gamecode_ini_path: str = ""        # 汉化后的 global.ini；留空自动检测
    gamecode_auto_copy: bool = True    # 结果自动进剪贴板（便于游戏内 Ctrl+V）
    gamecode_out_code: bool = True     # 游戏码卡片：输出中文码行
    gamecode_out_en: bool = False      # 游戏码卡片：输出英文译文行
    # ---- 按需截图翻译（全局热键触发，不做实时巡逻）----
    snap_enabled: bool = True          # 启用全局热键
    snap_hotkey: str = "Shift+F9"      # 截图识别 + 翻译（默认 Shift+F9，避免和别的软件抢 F9）
    snap_hotkey_select: str = "F10"    # 重新框选截图区域
    snap_region: Optional[dict] = None # {logical:{x,y,w,h}, physical:{left,top,width,height}, dpr, label}
    snap_popup_sec: int = 8            # 结果浮窗自动淡出秒数（0 = 一直显示）
    snap_show_popup: bool = True       # 显示结果浮窗（鼠标旁）
    snap_show_overlay: bool = True     # 结果进常驻译文悬浮框（与上一项都关=只写主窗口，手动复制）
    snap_write_main: bool = True       # 结果同时写进主窗口
    snap_max_lines: int = 40           # 单次最多翻译行数（误框整屏时防止烧 token）
    # ---- 界面 ----
    theme: str = "dark"
    ui_language: str = "zh_CN"         # 界面语言: zh_CN / zh_TW / en
    log_level: str = "INFO"
    overlay_geometry: Optional[dict] = None  # 悬浮框位置 {x,y,w,h}(logical)
    pin_single_core: bool = False            # 把本进程限制到单个小核(避免与游戏抢大核；代价:截图OCR变慢)

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
                # 仅当文件里确实存了这些键才覆盖默认值
                for f in fields(Settings):
                    if f.name in data and getattr(merged, f.name) is not None:
                        setattr(self, f.name, getattr(merged, f.name))
                # 旧版单一"双行"开关（v0.2.1）升级为"中文码 + 外文"两个勾选
                if data.get("reply_dual_line") is True:
                    self.reply_out_code = True
                    self.reply_out_foreign = True
                # 旧版把服务商显示名存进设置，升级为稳定 key
                self.api_provider = LEGACY_PROVIDER_NAMES.get(self.api_provider, self.api_provider)
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
