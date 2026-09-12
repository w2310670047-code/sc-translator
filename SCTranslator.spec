# -*- mode: python ; coding: utf-8 -*-
"""SC Translator 打包配置（PyInstaller >= 6）。

用法：
    .venv\\Scripts\\pyinstaller.exe --noconfirm --clean SCTranslator.spec
产物：
    dist\\SCTranslator\\SCTranslator.exe   （onedir，便携，双击即用）

设计要点：
- 只打包文字翻译真正需要的东西：PySide6(Core/Gui/Widgets) + requests；
  屏幕 OCR / 本地模型 / 词典相关的重型依赖全部排除，体积与启动时间最小。
- prompts/ 与 data/sc_glossary.ini 作为数据文件随包：
  首次运行由 sc_translator.bootstrap 释放到 exe 同级目录，用户可编辑。
"""

import os

ROOT = os.path.abspath(os.getcwd())

# 重型依赖：文字翻译用不到（屏幕 OCR / 本地推理 / 图像处理）
EXCLUDES = [
    "onnxruntime",
    "rapidocr_onnxruntime",
    "cv2",
    "mss",
    "llama_cpp",
    "numpy",
    "PIL",
    "Pillow",
    "shapely",
    "pyclipper",
    "wordninja",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "tests",
    # PySide6 里没用到的大模块（减少 ~200MB）
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtUiTools",
    "PySide6.QtSpatialAudio",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtSensors",
    "PySide6.QtLocation",
    "PySide6.QtSerialBus",
]

DATAS = [
    (os.path.join(ROOT, "prompts"), "prompts"),
    (os.path.join(ROOT, "assets", "sc_glossary.ini"), "assets"),
]

HIDDEN = ["sc_translator"]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SCTranslator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX 会被杀毒软件误报，关闭
    console=False,          # GUI 程序：不弹黑窗（日志仍在 data\logs）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(ROOT, "assets", "icon.ico") if os.path.exists(os.path.join(ROOT, "assets", "icon.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SCTranslator",
)
