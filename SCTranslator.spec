# -*- mode: python ; coding: utf-8 -*-
"""SC Translator 打包配置（PyInstaller >= 6）。

用法：
    .venv\\Scripts\\pyinstaller.exe --noconfirm --clean SCTranslator.spec
产物：
    dist\\SCTranslator\\SCTranslator.exe   （onedir，便携，双击即用）

包含内容：
- PySide6(Core/Gui/Widgets) + requests：文字翻译主功能；
- rapidocr-onnxruntime + onnxruntime + opencv：**按需**截图翻译（热键触发的本地 OCR）。
  这几个包约 60-70 MB，整包因此从 ~120 MB 涨到 ~330 MB；运行期是**懒加载**的
  （不按热键不初始化、不占内存），所以启动速度不受影响。
  想要精简包：把 EXCLUDES 里注释掉的 OCR 相关项恢复、并删掉 collect_data_files
  那一行即可（代价是截图翻译不可用）。
- 仍然排除：llama-cpp（本地大模型）、matplotlib/scipy/pandas 等无关重型库。

数据文件：
- prompts/                 提示词（用户可编辑，首启释放到 exe 同级）
- assets/sc_glossary.ini   官方术语表
- rapidocr 的 onnx 模型与 config.yaml（随包，离线可用）
"""

import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.getcwd())

# 与翻译功能无关的重型依赖
# 若要出"纯文字精简版"：把下面注释的两行恢复为生效项，
# 并删除 DATAS 里的 collect_data_files("rapidocr_onnxruntime")。
EXCLUDES = [
    # "onnxruntime",
    # "rapidocr_onnxruntime",
    # "cv2",
    # "numpy",
    # "mss",
    # "PIL",
    # "shapely",
    # "pyclipper",
    # "wordninja",
    "llama_cpp",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "tests",
    "tkinter",
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

# RapidOCR 的 onnx 模型/config 不是标准包数据，必须显式收集（否则运行期报缺模型）
try:
    DATAS += collect_data_files("rapidocr_onnxruntime")
except Exception:  # noqa: BLE001
    pass

HIDDEN = [
    "sc_translator",
    "sc_translator.snapshot",
    "sc_translator.ocr",
    "sc_translator.screen",
    "sc_translator.wordseg",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "rapidocr_onnxruntime",
    "pyclipper",
    "shapely",
    "yaml",
    "wordninja",
    "dxcam",
    "comtypes",
]

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
