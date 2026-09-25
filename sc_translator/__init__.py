"""Star Citizen 翻译器 (SC Translator).

双向文字翻译（外文 → 中文 / 中文 → 外文）+ 按热键的按需截图翻译，
面向《星际公民》的英文界面与玩家聊天。
"""

__version__ = "0.4.9"
APP_NAME = "SCTranslator"
APP_DISPLAY_NAME = "Star Citizen 翻译器"

# 模型留空时的兜底模型：全项目唯一的默认值来源
# （此前 "deepseek-chat" 字面量散落在 app / __main__ / client / 主窗口共 13 处）
DEFAULT_MODEL = "deepseek-chat"
