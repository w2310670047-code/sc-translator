"""UI 主题：深色(默认) / 浅色。"""

from __future__ import annotations

DARK = {
    "bg": "#10141b",
    "panel": "#171c26",
    "panel2": "#1e2530",
    "line": "#2a3342",
    "text": "#e3e9f2",
    "muted": "#93a0b0",
    "accent": "#46a6ff",
    "accent_hover": "#2f8fe0",
    "ok": "#37d399",
    "warn": "#f5b83d",
    "danger": "#ff6b6b",
    "input_bg": "#0d1116",
    "row_bg": "#1a2029",
}

LIGHT = {
    "bg": "#f2f4f7",
    "panel": "#ffffff",
    "panel2": "#eef1f5",
    "line": "#d5dbe3",
    "text": "#1d2430",
    "muted": "#66707d",
    "accent": "#1578d4",
    "accent_hover": "#0f63b4",
    "ok": "#17945f",
    "warn": "#c07f12",
    "danger": "#d33a3a",
    "input_bg": "#ffffff",
    "row_bg": "#f7f9fb",
}


def palette(name: str = "dark") -> dict:
    return DARK if name == "dark" else LIGHT


def build_stylesheet(name: str = "dark") -> str:
    c = palette(name)
    return f"""
QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {c['bg']}; }}
QFrame#card {{
    background-color: {c['panel']};
    border: 1px solid {c['line']};
    border-radius: 8px;
}}
QLabel#cardTitle {{ font-weight: 600; font-size: 13px; color: {c['text']}; }}
QLabel#hint {{ color: {c['muted']}; font-size: 12px; }}
QLabel#statusGood {{ color: {c['ok']}; font-weight: 600; }}
QLabel#statusBad {{ color: {c['warn']}; }}
QPushButton {{
    background-color: {c['panel2']};
    border: 1px solid {c['line']};
    border-radius: 6px;
    padding: 5px 12px;
    color: {c['text']};
}}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:pressed {{ background-color: {c['panel2']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary {{
    background-color: {c['accent']};
    color: #ffffff;
    border: none;
    font-weight: 600;
    padding: 7px 18px;
}}
QPushButton#primary:hover {{ background-color: {c['accent_hover']}; }}
QPushButton#danger {{ color: {c['danger']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    border: 1px solid {c['line']};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {c['accent']};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
QComboBox QAbstractItemView {{
    background-color: {c['panel']};
    border: 1px solid {c['line']};
    selection-background-color: {c['accent']};
    selection-color: white;
}}
QCheckBox, QRadioButton {{ spacing: 6px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; }}
QPlainTextEdit#log {{
    background-color: {c['input_bg']};
    border: 1px solid {c['line']};
    border-radius: 6px;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    color: {c['muted']};
}}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['line']}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QToolTip {{ background-color: {c['panel2']}; color: {c['text']}; border: 1px solid {c['line']}; }}
"""


def overlay_style(theme: str, opacity_pct: int, font_size: int) -> str:
    """悬浮框样式。opacity_pct: 0-100 容器背景不透明度。"""
    c = palette(theme)
    alpha = max(20, min(100, opacity_pct))
    bg_hex = _with_alpha(c["bg"], alpha)
    row_hex = _with_alpha(c["row_bg"], max(35, alpha - 12))
    return f"""
#ovWrap {{
    background-color: {bg_hex};
    border: 1px solid {_with_alpha(c['line'], min(100, alpha + 10))};
    border-radius: 10px;
}}
#ovTitle {{ color: {c['accent']}; font-size: 11px; font-weight: 600; }}
#ovCount {{ color: {c['muted']}; font-size: 11px; }}
QLabel#ovRowTrans {{ color: {c['text']}; font-size: {font_size}px; }}
QLabel#ovRowOrig {{ color: {c['muted']}; font-size: {max(9, font_size - 3)}px; }}
QLabel#ovPending {{ color: {c['warn']}; font-size: {font_size}px; font-style: italic; }}
QFrame#ovRow {{ background-color: {row_hex}; border-radius: 6px; }}
QFrame#ovHeader {{ background-color: transparent; }}
QPushButton#ovBtn {{
    background: transparent; border: none; color: {c['muted']};
    padding: 1px 6px; font-size: 12px;
}}
QPushButton#ovBtn:hover {{ color: {c['text']}; }}
QLineEdit#ovInput {{
    background-color: {_with_alpha(c['input_bg'], min(100, alpha + 20))};
    color: {c['text']}; border: 1px solid {c['line']}; border-radius: 6px; padding: 3px 8px;
}}
QComboBox#ovInput {{ background-color: {_with_alpha(c['input_bg'], min(100, alpha + 20))}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
"""


def _with_alpha(hex_color: str, alpha_pct: int) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    a = max(0, min(255, round(alpha_pct * 255 / 100)))
    return f"#{r}{g}{b}{a:02x}"
