"""打包相关回归：轻量导入图 + 冻结环境下的资源自举 + 便携数据目录。

这些用例保证 "打包成 exe" 不会悄悄退回重型依赖（numpy/cv2/onnxruntime），
也保证 exe 首次运行能把提示词与术语表释放到程序目录。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HEAVY = ("numpy", "cv2", "onnxruntime", "rapidocr_onnxruntime", "mss", "llama_cpp", "PIL")


def test_runtime_import_graph_is_light():
    """主程序启动路径不允许导入重型依赖。

    OCR 栈（numpy/cv2/onnxruntime）现在**随包分发**（截图翻译需要），
    但必须保持懒加载：只有按热键时才导入，这样启动依然快、常驻内存也小。
    """
    code = (
        "import sys, sc_translator.app;"
        "heavy=[m for m in %r if m in sys.modules];"
        "print('HEAVY=' + ','.join(heavy));"
        "print('LAZY=' + str('sc_translator.ocr' in sys.modules or 'sc_translator.snapshot' in sys.modules))"
        % (HEAVY,)
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert out.returncode == 0, out.stderr
    assert "HEAVY=" in out.stdout, out.stdout
    heavy = out.stdout.split("HEAVY=", 1)[1].splitlines()[0].strip()
    assert heavy == "", f"启动路径不应导入重型依赖，实际导入了：{heavy}"
    assert "LAZY=False" in out.stdout, "OCR/截图模块不应在启动时被导入"


def test_ocr_stack_imports_on_demand():
    """真正用到时的导入链路是通的（模型能否加载由 --doctor 负责验证）。"""
    code = (
        "from sc_translator import snapshot, screen;"
        "import numpy, cv2, rapidocr_onnxruntime;"
        "print('OK', bool(snapshot.parse_hotkey('F9')), screen.ScreenCapture is not None)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("OK True"), out.stdout


def test_frozen_paths_point_into_exe_folder(monkeypatch, tmp_path):
    """冻结（打包）后：数据在 exe 同级 data\\，提示词在 exe 同级 prompts\\。"""
    exe_dir = tmp_path / "SCTranslator"
    exe_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "SCTranslator.exe"))
    monkeypatch.delenv("SC_TRANSLATOR_HOME", raising=False)
    monkeypatch.delenv("SC_PROMPTS_DIR", raising=False)

    from sc_translator import paths
    from sc_translator.prompts import prompts_dir

    assert paths.home_dir() == exe_dir / "data"
    assert paths.default_glossary_file() == exe_dir / "data" / "sc_glossary.ini"
    assert prompts_dir() == exe_dir / "prompts"


def test_bootstrap_seeds_prompts_and_glossary(monkeypatch, tmp_path):
    """首次运行自举：随包提示词/术语表复制到程序目录，且不覆盖已有文件。"""
    exe_dir = tmp_path / "SCTranslator"
    exe_dir.mkdir()
    bundle = tmp_path / "_internal"
    (bundle / "prompts").mkdir(parents=True)
    (bundle / "assets").mkdir(parents=True)
    for name in ("translation_normal.md", "translation_spicy.md", "reply.md"):
        (bundle / "prompts" / name).write_text(f"# {name}\n内容-{name}\n", encoding="utf-8")
    (bundle / "assets" / "sc_glossary.ini").write_text("Stanton=斯坦顿星系\n", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "SCTranslator.exe"))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("SC_TRANSLATOR_HOME", str(exe_dir / "data"))
    monkeypatch.delenv("SC_PROMPTS_DIR", raising=False)

    from sc_translator import bootstrap
    from sc_translator.prompts import prompts_dir

    bootstrap.run()
    assert (exe_dir / "prompts" / "translation_normal.md").is_file()
    assert (exe_dir / "prompts" / "reply.md").is_file()
    assert (exe_dir / "data" / "sc_glossary.ini").read_text(encoding="utf-8").startswith("Stanton=")
    assert prompts_dir() == exe_dir / "prompts"

    # 用户改过的提示词不能被覆盖
    (exe_dir / "prompts" / "reply.md").write_text("我的自定义提示词", encoding="utf-8")
    bootstrap.run()
    assert (exe_dir / "prompts" / "reply.md").read_text(encoding="utf-8") == "我的自定义提示词"


def test_doctor_selftest_passes(tmp_path):
    """--doctor 自检必须整体通过（打包版排障的第一道工具）。"""
    home = tmp_path / "home"
    out = subprocess.run(
        [sys.executable, "-m", "sc_translator", "--doctor", f"--home={home}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    report = home / "logs" / "doctor.log"
    assert report.is_file(), "自检报告未生成"
    text = report.read_text(encoding="utf-8")
    assert "[FAIL]" not in text, text
    assert "结论：全部通过" in text, text
    assert out.returncode == 0, out.stdout + out.stderr
    for step in ("数据目录", "设置", "提示词", "术语表"):
        assert f"[PASS] {step}" in text, text


def test_packaged_glossary_is_used_when_no_path_configured(qapp, tmp_home):
    """未配置术语表路径时，自动使用 data\\sc_glossary.ini（便携版开箱即有官方术语）。"""
    from sc_translator import glossary, paths
    from sc_translator.app import AppController

    paths.default_glossary_file().write_text(
        "Stanton=斯坦顿星系\nArea18=18 区\n", encoding="utf-8"
    )
    glossary.clear()
    from sc_translator.settings import Settings

    s = Settings().load()
    assert s.glossary_path == "", "默认不应写死路径"
    s.glossary_enabled = True
    ctrl = AppController(qapp, settings=s)
    assert glossary.apply("go to Stanton now") == "go to 斯坦顿星系 now"
    assert glossary.apply("visit Area18") == "visit 18 区"
    ctrl.shutdown()
