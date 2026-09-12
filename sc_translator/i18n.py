"""界面多语言（简中 / 繁中 / English）。

设计：**一条 key 一行三语**，用元组保证三种语言永远成套（漏翻会被测试直接抓出来）：

    "app.name": ("Star Citizen 翻译器", "Star Citizen 翻譯器", "Star Citizen Translator"),

用法::

    from ..i18n import t
    self.setWindowTitle(t("app.title", version=__version__))

- 当前语言来自设置 ``ui_language``（默认 ``zh_CN``），`set_language()` 切换；
- 缺失/为空的译文回退到简体中文，再回退到 key 本身（永不抛异常）；
- 占位符用 ``str.format`` 风格：``t("gc.state_ready", size=7020)``。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# 语言顺序即元组下标，勿随意调整（调整时同步 _T 里所有元组）
LANGS: tuple[str, ...] = ("zh_CN", "zh_TW", "en")

_current: str = "zh_CN"

# ---------------------------------------------------------------------------
# key -> (简体中文, 繁體中文, English)
# ---------------------------------------------------------------------------
_T: dict[str, tuple[str, str, str]] = {
    # ---- 应用/窗口 ----
    "app.name": ("Star Citizen 翻译器", "Star Citizen 翻譯器", "Star Citizen Translator"),
    "app.title": (
        "Star Citizen 翻译器 v{version}（文字翻译）",
        "Star Citizen 翻譯器 v{version}（文字翻譯）",
        "Star Citizen Translator v{version} (Text)",
    ),
    "lang.label": ("界面语言", "介面語言", "Language"),
    "lang.zh_CN": ("简体中文", "簡體中文", "Simplified Chinese"),
    "lang.zh_TW": ("繁體中文", "繁體中文", "Traditional Chinese"),
    "lang.en": ("English", "English", "English"),
    "status.ready": ("就绪", "就緒", "Ready"),

    # ---- API 配置行 ----
    "provider.label": ("服务商", "服務商", "Provider"),
    "provider.custom": ("自定义 OpenAI 兼容", "自訂 OpenAI 相容", "Custom OpenAI-compatible"),
    "btn.models": ("获取模型", "取得模型", "Get models"),
    "btn.test": ("测试", "測試", "Test"),
    "btn.logs": ("日志", "日誌", "Logs"),

    # ---- 术语表 ----
    "glossary.label": (
        "SC术语表（Stanton→斯坦顿星系、Pyro→派罗星系…）",
        "SC術語表（Stanton→斯坦頓星系、Pyro→派羅星系…）",
        "SC glossary (Stanton→斯坦顿星系, Pyro→派罗星系…)",
    ),
    "glossary.path_ph": (
        "术语表文件(可选，留空用默认词条)",
        "術語表檔案(可選，留空用預設詞條)",
        "Glossary file (optional; empty = built-in terms)",
    ),
    "btn.make_glossary": ("生成术语表", "產生術語表", "Create glossary"),

    # ---- 嘴臭模式 ----
    "spicy.label": (
        "嘴臭模式：开启用嘴臭提示词(嘲讽垃圾话)，关闭用正常提示词",
        "嘴砲模式：開啟用嘴砲提示詞(嘲諷垃圾話)，關閉用正常提示詞",
        "Spicy mode: trash-talk prompt when on, normal prompt when off",
    ),
    "spicy.tip": (
        "开启后“看懂”译文与“回话”输出都用嘴臭风格；关闭恢复正常。",
        "開啟後「看懂」譯文與「回話」輸出都用嘴砲風格；關閉恢復正常。",
        'When on, both "Understand" and "Reply" outputs use the spicy style; off restores normal.',
    ),
    "status.spicy_on": ("嘴臭模式已开启", "嘴砲模式已開啟", "Spicy mode on"),
    "status.spicy_off": ("嘴臭模式已关闭", "嘴砲模式已關閉", "Spicy mode off"),

    # ---- 看懂（外文 -> 中文）----
    "pane.in.title": (
        "看懂：粘贴/输入外文 → 中文",
        "看懂：貼上/輸入外文 → 中文",
        "Understand: paste foreign text → Chinese",
    ),
    "pane.in.ph": (
        "把聊天里看到的外文粘贴/输入到这里…",
        "把聊天裡看到的外文貼上/輸入到這裡…",
        "Paste the foreign text you saw in chat here…",
    ),
    "btn.translate_zh": ("翻译到中文", "翻譯成中文", "Translate to Chinese"),
    "btn.paste": ("粘贴剪贴板", "貼上剪貼簿", "Paste clipboard"),
    "btn.clear": ("清空", "清空", "Clear"),

    # ---- 回话（中文 -> 外文）----
    "pane.out.title": (
        "回话：输入中文 → 外文",
        "回話：輸入中文 → 外文",
        "Reply: type Chinese → foreign",
    ),
    "pane.out.ph": (
        "要发给外国玩家的中文回话…",
        "要發給外國玩家的中文回話…",
        "Chinese message you want to send to foreign players…",
    ),
    "lbl.target": ("目标", "目標", "Target"),
    "btn.translate_copy": ("翻译并复制", "翻譯並複製", "Translate & copy"),
    "lbl.output": ("输出", "輸出", "Output"),
    "chk.code": ("中文码", "中文碼", "Chinese code"),
    "chk.code.tip": (
        "中译中：把中文编成游戏内可显示的中文码行（[zh] @…）",
        "中譯中：把中文編成遊戲內可顯示的中文碼行（[zh] @…）",
        "zh→zh: encode Chinese into an in-game code line ([zh] @…)",
    ),
    "chk.foreign": ("译文", "譯文", "Translation"),
    "chk.foreign.tip": (
        "中译外：翻译成目标语言（English/Japanese/Korean）",
        "中譯外：翻譯成目標語言（English/Japanese/Korean）",
        "zh→foreign: translate into the target language (English/Japanese/Korean)",
    ),
    "lbl.result": (
        "译文（只读，可选中复制）",
        "譯文（唯讀，可選取複製）",
        "Result (read-only, selectable)",
    ),
    "btn.copy_result": ("复制译文", "複製譯文", "Copy result"),
    "status.reply_out_both": (
        "回话输出：中文码 + 译文",
        "回話輸出：中文碼 + 譯文",
        "Reply output: code + translation",
    ),
    "status.reply_out_code": ("回话输出：只中文码", "回話輸出：只中文碼", "Reply output: code only"),
    "status.reply_out_foreign": ("回话输出：只译文", "回話輸出：只譯文", "Reply output: translation only"),
    "status.min_one_reply": (
        "至少保留一项输出：中文码 或 译文",
        "至少保留一項輸出：中文碼 或 譯文",
        "Keep at least one output: code or translation",
    ),

    # ---- 游戏聊天码 ----
    "gc.title": (
        "游戏聊天码：把中文送进游戏聊天（需已装带社区输入法支持的汉化）",
        "遊戲聊天碼：把中文送進遊戲聊天（需已裝帶社群輸入法支援的漢化）",
        "Game chat code: get Chinese into in-game chat (needs a localization with community input-method support)",
    ),
    "gc.path_label": ("汉化 global.ini", "漢化 global.ini", "Localized global.ini"),
    "gc.path_ph": (
        "留空 = 自动检测已安装的汉化",
        "留空 = 自動偵測已安裝的漢化",
        "Empty = auto-detect an installed localization",
    ),
    "gc.detect": ("自动检测", "自動偵測", "Auto-detect"),
    "gc.browse": ("浏览…", "瀏覽…", "Browse…"),
    "gc.in_label": (
        "中文（双行模式下输入即时出中文码）",
        "中文（雙行模式下輸入即時出中文碼）",
        "Chinese (in dual-line mode the code appears as you type)",
    ),
    "gc.in_ph": ("你好吗", "你好嗎", "你好吗"),
    "gc.autocopy": ("自动复制", "自動複製", "Auto copy"),
    "gc.chk.code.tip": (
        "中译中：输出游戏内可显示的中文码行（[zh] @…）",
        "中譯中：輸出遊戲內可顯示的中文碼行（[zh] @…）",
        "zh→zh: output an in-game code line ([zh] @…)",
    ),
    "gc.chk.en": ("英文", "英文", "English"),
    "gc.chk.en.tip": (
        "中译英：调用翻译 API 输出英文译文行（[en] …）",
        "中譯英：呼叫翻譯 API 輸出英文譯文行（[en] …）",
        "zh→en: call the translation API and output an English line ([en] …)",
    ),
    "gc.out_label": (
        "游戏码 / 结果（可粘贴别人的 [zh] 消息后解码）",
        "遊戲碼 / 結果（可貼上別人的 [zh] 訊息後解碼）",
        "Code / result (paste someone's [zh] message here to decode)",
    ),
    "gc.out_ph_dual": ("[zh] @IH@E8@AP\n[en] How are you", "[zh] @IH@E8@AP\n[en] How are you", "[zh] @IH@E8@AP\n[en] How are you"),
    "gc.out_ph_en": ("How are you", "How are you", "How are you"),
    "gc.out_ph_code": ("[zh] @IH@E8@AP", "[zh] @IH@E8@AP", "[zh] @IH@E8@AP"),
    "btn.decode": ("解码为中文", "解碼為中文", "Decode to Chinese"),
    "btn.copy_gc": ("复制结果", "複製結果", "Copy result"),
    "gc.state_ready": ("码表就绪：{size} 字", "碼表就緒：{size} 字", "Code table ready: {size} chars"),
    "gc.state_version": (" · 版本 {version}", " · 版本 {version}", " · v{version}"),
    "gc.state_source": (" · 来源 {source}", " · 來源 {source}", " · from {source}"),
    "gc.state_missing": (
        "未找到码表：请先安装带“社区输入法支持”的汉化，或点“浏览…”选择游戏目录下的 "
        "…\\Localization\\chinese_(simplified)\\global.ini",
        "找不到碼表：請先安裝帶「社群輸入法支援」的漢化，或點「瀏覽…」選擇遊戲目錄下的 "
        "…\\Localization\\chinese_(simplified)\\global.ini",
        "No code table found: install a localization with community input-method support, or use "
        "\"Browse…\" to pick …\\Localization\\chinese_(simplified)\\global.ini",
    ),
    "status.table_loaded": ("游戏码表已加载：{n} 字", "遊戲碼表已載入：{n} 字", "Code table loaded: {n} chars"),
    "status.preview_note": ("", "", ""),

    # ---- 游戏聊天码按钮/状态 ----
    "btn.gen_dual": ("生成双行并复制", "產生雙行並複製", "Generate 2 lines & copy"),
    "btn.translate_en_copy": ("翻译为英文并复制", "翻譯成英文並複製", "Translate to English & copy"),
    "btn.encode_copy": ("编码并复制", "編碼並複製", "Encode & copy"),
    "status.need_zh": ("请先在左侧输入中文", "請先在左側輸入中文", "Type Chinese on the left first"),
    "status.copied_send": ("已复制，进游戏 Ctrl+V 发送", "已複製，進遊戲 Ctrl+V 傳送", "Copied — press Ctrl+V in game"),
    "status.copied_code": (
        "已复制中文码，进游戏 Ctrl+V 发送",
        "已複製中文碼，進遊戲 Ctrl+V 傳送",
        "Chinese code copied — press Ctrl+V in game",
    ),
    "status.copied_dual": (
        "已复制双行（中文码+英文），进游戏 Ctrl+V 发送",
        "已複製雙行（中文碼+英文），進遊戲 Ctrl+V 傳送",
        "Two lines copied (code + English) — press Ctrl+V in game",
    ),
    "status.copied_en": (
        "已复制英文，进游戏 Ctrl+V 发送",
        "已複製英文，進遊戲 Ctrl+V 傳送",
        "English copied — press Ctrl+V in game",
    ),
    "status.no_key_code_only": (
        "未配置 API Key，仅复制中文码行",
        "未設定 API Key，僅複製中文碼行",
        "No API key configured — copied the code line only",
    ),
    "status.need_key_en": (
        "需要 API Key 才能生成英文",
        "需要 API Key 才能產生英文",
        "An API key is required to produce English",
    ),
    "status.translate_failed_code": (
        "翻译失败（{err}），仅复制中文码行",
        "翻譯失敗（{err}），僅複製中文碼行",
        "Translation failed ({err}) — copied the code line only",
    ),
    "status.need_paste_code": (
        "请先在右侧粘贴 [zh] 开头的游戏码消息",
        "請先在右側貼上 [zh] 開頭的遊戲碼訊息",
        "Paste a [zh] game-code message on the right first",
    ),
    "status.decoded": ("已解码并复制中文", "已解碼並複製中文", "Decoded and copied the Chinese text"),
    "status.decoded_unsure": (
        "已解码并复制中文（未检测到 [zh] 前缀，结果可能不准）",
        "已解碼並複製中文（未偵測到 [zh] 前置字串，結果可能不準）",
        "Decoded and copied (no [zh] prefix found — result may be inaccurate)",
    ),
    "status.min_one_gc": (
        "至少保留一项输出：中文码 或 英文",
        "至少保留一項輸出：中文碼 或 英文",
        "Keep at least one output: code or English",
    ),
    "warn.no_table_code": (
        "⚠ 未找到汉化码表，无法生成中文码",
        "⚠ 找不到漢化碼表，無法產生中文碼",
        "⚠ No localization code table — cannot build a Chinese code line",
    ),
    "warn.no_table_translation_only": (
        "⚠ 未找到汉化码表，本次只输出译文",
        "⚠ 找不到漢化碼表，本次只輸出譯文",
        "⚠ No code table — outputting the translation only",
    ),
    "warn.no_encodable": (
        "⚠ 没有可编码的中文，本次只输出译文",
        "⚠ 沒有可編碼的中文，本次只輸出譯文",
        "⚠ Nothing encodable — outputting the translation only",
    ),

    # ---- 通用状态 ----
    "btn.loading": ("获取中…", "取得中…", "Loading…"),
    "dlg.fetch_fail.title": ("获取失败", "取得失敗", "Failed to fetch"),
    "btn.testing": ("测试中…", "測試中…", "Testing…"),
    "dlg.test_ok.title": ("测试成功", "測試成功", "Test passed"),
    "dlg.test_ok.body": ("测试译文：{val}", "測試譯文：{val}", "Test translation: {val}"),
    "dlg.test_fail.title": ("测试失败", "測試失敗", "Test failed"),
    "dlg.no_key.title": ("缺少 API Key", "缺少 API Key", "Missing API key"),
    "dlg.no_key.body": ("请先填写 API Key。", "請先填寫 API Key。", "Please fill in the API key first."),

    # ---- 术语表状态 ----
    "gl.state_off": ("已关闭", "已關閉", "Off"),
    "gl.state_active": (
        "已生效 {n} 词条",
        "已生效 {n} 詞條",
        "{n} terms active",
    ),
    "gl.state_inactive": ("未生效", "未生效", "Inactive"),
    "gl.made": ("术语表已生成", "術語表已產生", "Glossary template created"),
    "gl.make_fail": ("生成失败", "產生失敗", "Failed to create"),

    # ---- 通用状态 ----
    "status.translating": ("翻译中…", "翻譯中…", "Translating…"),
    "status.done": ("完成", "完成", "Done"),
    "status.copied_result": ("已复制译文", "已複製譯文", "Result copied"),
    "status.fail": ("失败：{msg}", "失敗：{msg}", "Failed: {msg}"),
    "status.lang_busy": (
        "翻译进行中，请稍后再切换界面语言",
        "翻譯進行中，請稍後再切換介面語言",
        "Translation in progress — switch the language afterwards",
    ),

    # ---- 对话框 ----
    "dlg.notice": ("提示", "提示", "Notice"),
    "dlg.fail.title": ("翻译失败", "翻譯失敗", "Translation failed"),
    "dlg.need_foreign": (
        "请先粘贴或输入外文。",
        "請先貼上或輸入外文。",
        "Paste or type some foreign text first.",
    ),
    "dlg.need_reply": ("请先输入中文回话。", "請先輸入中文回話。", "Type a Chinese reply first."),
    "dlg.no_table.title": ("未找到码表", "找不到碼表", "Code table not found"),
    "dlg.no_table.body": (
        "没有在本机找到带社区输入法码表的 global.ini。\n"
        "请先在 SC 汉化盒子里安装带“社区输入法支持”的汉化，或手动选择文件。",
        "沒有在本機找到帶社群輸入法碼表的 global.ini。\n"
        "請先在 SC 漢化盒子裡安裝帶「社群輸入法支援」的漢化，或手動選擇檔案。",
        "No global.ini with a community input-method code table was found on this machine.\n"
        "Install a localization with that support (e.g. via SC 汉化盒子), or pick the file manually.",
    ),
    "dlg.pick_ini": (
        "选择汉化后的 global.ini",
        "選擇漢化後的 global.ini",
        "Select the localized global.ini",
    ),
    "filter.ini": (
        "INI 文件 (*.ini);;所有文件 (*)",
        "INI 檔案 (*.ini);;所有檔案 (*)",
        "INI files (*.ini);;All files (*)",
    ),
    "dlg.load_fail.title": ("码表加载失败", "碼表載入失敗", "Failed to load the code table"),
    "dlg.empty_table.title": ("码表为空", "碼表為空", "Empty code table"),
    "dlg.empty_table.body": (
        "该文件里没有社区输入法码表块。",
        "該檔案裡沒有社群輸入法碼表區塊。",
        "That file contains no community input-method block.",
    ),
    "dlg.need_table.code_body": (
        "中文码需要汉化码表。\n请先安装带“社区输入法支持”的汉化，\n"
        "或点“自动检测 / 浏览…”指定 global.ini；\n也可以只勾“英文”用翻译输出。",
        "中文碼需要漢化碼表。\n請先安裝帶「社群輸入法支援」的漢化，\n"
        "或點「自動偵測 / 瀏覽…」指定 global.ini；\n也可以只勾「英文」用翻譯輸出。",
        "The Chinese code line needs a localization code table.\n"
        "Install a localization with community input-method support, or use\n"
        "\"Auto-detect / Browse…\" to pick global.ini. You can also check just \"English\".",
    ),
    "dlg.need_table.reply_body": (
        "中文码需要汉化码表。\n请先安装带“社区输入法支持”的汉化，"
        "或到下方“游戏聊天码”卡片点“自动检测 / 浏览…”指定 global.ini。",
        "中文碼需要漢化碼表。\n請先安裝帶「社群輸入法支援」的漢化，"
        "或到下方「遊戲聊天碼」卡片點「自動偵測 / 瀏覽…」指定 global.ini。",
        "The Chinese code line needs a localization code table.\n"
        "Install one, or use \"Auto-detect / Browse…\" in the \"Game chat code\" card below.",
    ),

    # ---- 启动入口（__main__）----
    "boot.already_running.title": ("提示", "提示", "Notice"),
    "boot.already_running.body": (
        "SC 翻译器已在运行（或上次异常退出）。\n若确认没有运行，请删除下面的文件后重试：\n",
        "SC 翻譯器已在執行（或上次異常結束）。\n若確認沒有在執行，請刪除下面的檔案後重試：\n",
        "SC Translator is already running (or exited abnormally last time).\n"
        "If you are sure it is not running, delete this file and retry:\n",
    ),
    "boot.start_fail.title": ("SC 翻译器启动失败", "SC 翻譯器啟動失敗", "SC Translator failed to start"),
    "boot.start_fail.body": (
        "启动时发生错误，详见日志：\n",
        "啟動時發生錯誤，詳見日誌：\n",
        "An error occurred during startup — see the log:\n",
    ),
}


def languages() -> list[tuple[str, str]]:
    """可用语言 [(code, 显示名)]。"""
    return [(code, t(f"lang.{code}")) for code in LANGS]


def set_language(code: str) -> str:
    """切换当前语言；未知代码回退 zh_CN。返回最终生效的代码。"""
    global _current
    code = (code or "").strip()
    if code not in LANGS:
        if code:
            log.warning("未知界面语言 %r，回退 zh_CN", code)
        code = "zh_CN"
    _current = code
    return _current


def current() -> str:
    return _current


def t(key: str, **kwargs) -> str:
    """取文案并按需格式化占位符；任何缺失都优雅回退，不抛异常。"""
    row = _T.get(key)
    text = ""
    if row is not None:
        try:
            idx = LANGS.index(_current)
        except ValueError:
            idx = 0
        text = row[idx] if idx < len(row) else ""
        if not text:
            text = row[0]
    if not text:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:  # noqa: BLE001
            return text
    return text


def keys() -> list[str]:
    """所有文案 key（测试用）。"""
    return list(_T)
