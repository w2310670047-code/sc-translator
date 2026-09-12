# v0.1.0 — 首个公开版本：星际公民双向文字翻译器

Windows 免安装打包版（onedir + 便携 data 目录），解压双击即用。

## 下载

| 文件 | 说明 |
| --- | --- |
| `SCTranslator-v0.1.0-win64.zip` (49 MB) | 解压到任意目录 → 双击 `SCTranslator.exe` |

SHA256：`B2A9A2A1B06FB2E00310330D1EAD3CF8FDD4A22C6CE81BB937CAEC8EBB1A6AA8`

## 主要功能

- **双向翻译**：外文（英/日/韩）→ 简体中文；中文 → English / Japanese / Korean（译文自动进剪贴板，回游戏 Ctrl+V）
- **术语表预替换**：随包 1239 条官方中英对照（地名 / 载具 / 物品 / 组织 / 服务），
  `Stanton → 斯坦顿星系`、`Pyro → 派罗星系`；`data\sc_glossary.ini` 可自由增删
- **嘴臭模式**：一个开关决定使用「正常提示词」还是「嘴臭提示词」（嘲讽垃圾话风格，不含真脏话），无自动检测 / 自动生成
- **提示词全部外置**：`prompts\translation_normal.md` / `translation_spicy.md` / `reply.md`，改完重启生效
- **DeepSeek / OpenAI 兼容接口**：自动为 `deepseek-v4-*` 关闭 Thinking 模式（否则返回空内容）
- **排障友好**：`data\logs\startup.log`（启动崩溃）、`sc_translator.log`（运行）、
  `exchange.log`（每次「输入 → 模型输出」，含模型/风格/是否命中缓存）
- API Key 用 Windows DPAPI 加密，仅当前用户本机可解密
- 便携：整个文件夹拷走即带全部设置与日志

## 打包版自检

```powershell
SCTranslator.exe --doctor            # 配置 / 提示词 / 术语表 自检，报告写入 data\logs\doctor.log
SCTranslator.exe --doctor --online   # 额外实测一次真实 API 翻译
```

本版本发布前实测（真实 DeepSeek API）：

```text
[PASS] 数据目录: ...\SCTranslator\data  (0ms)
[PASS] 设置: provider=DeepSeek model=deepseek-flash base=https://api.deepseek.com key=已配置 嘴臭=False  (5ms)
[PASS] 提示词: normal=168字 spicy=120字 reply=65字  (1ms)
[PASS] 术语表: sc_glossary.ini 载入 1239 词条，生效 1239 条  (191ms)
[PASS] 在线翻译（API）: 模型 2 个；回话翻译 -> Hello, just testing.  (1474ms)
结论：全部通过
```

## 工程说明

- 体积：exe 4.3 MB，整包 120 MB（含 Qt），冷启动约 1 秒
- 打包仅含 PySide6(Core/Gui/Widgets) + requests；OCR / 本地模型 / 图像处理（numpy、opencv、
  onnxruntime、llama-cpp 等）全部排除，`tests/test_packaging.py` 用测试守住这条底线
- 单元 + 集成 + 打包回归共 69 项测试全绿

## 已知限制

- 仅 Windows（星际公民本身也只有 Windows）
- 术语表里官方整句条目按整句匹配，长句无法拆成词条；`Area18` 这类无空格写法需自行补充
- 不含屏幕 OCR / 悬浮窗（早期形态已移除，避免 CPU 与 token 浪费）
