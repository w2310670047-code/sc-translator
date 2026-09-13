# v0.4.0 — 按需截图翻译（F9 抓一次 → 本地 OCR → 翻译）

新增**热键按需**的截图翻译：只在按键那一刻抓一帧，**不做实时巡逻**，不按键完全不耗资源。

## 下载

| 文件 | 说明 |
| --- | --- |
| `SCTranslator-v0.4.0-win64.zip` | 解压到任意目录 → 双击 `SCTranslator.exe`（免安装、免 Python） |

> 体积变化：整包 120 MB → **约 330 MB**（zip 约 150 MB），因为 OCR 需要
> `onnxruntime + opencv + rapidocr` 与 onnx 模型。它们是**懒加载**的，不进启动路径，
> 冷启动依然约 1 秒；想回精简包见 `SCTranslator.spec` 顶部注释。

## 新增：截图翻译

| 热键（可改） | 作用 |
| --- | --- |
| **F9** | 抓取记住的区域 → 本地 RapidOCR 识别 → 翻译成中文 → 鼠标旁浮窗 + 主窗口结果区 |
| **F10** | 重新框选截图区域（首次使用也用它） |

- **不按键 = 零开销**：没有巡逻线程、没有定时采样、不加载模型、不占内存（这是与早期"实时翻译"版本的关键区别）
- **识别**：本地 RapidOCR（PaddleOCR onnx 模型随包，离线、免费、不联网）
- **翻译**：走你配置的 API，与文字翻译共用术语表与缓存
- **浮窗**：鼠标旁半透明小窗、自动避边，8 秒淡出（可设置/可固定）；鼠标移入暂停倒计时；
  「复制全部」写剪贴板；正文可选中局部复制
- **防误伤**：单次最多 40 行（可设置）；纯数字/符号/单字符行丢弃
- **失败退化**：翻译失败也会把识别到的原文显示出来
- **界面**：三语（简中/繁中/English）全部覆盖新功能

## 实测证据

**源码级端到端**（真抓屏 + 真 RapidOCR + 真 DeepSeek API）：

```text
原文: QUANTUMTRAVEL                          -> 译文: 量子旅行
原文: Destination:Area 18,Stanton System      -> 译文: 目的地：18区，斯坦顿星系
原文: Bounty hunting is available nearby.     -> 译文: 附近有赏金猎人活动可参加。
原文: Press F to pay respects, then jump to Pyro. -> 译文: 按F键致敬，然后跃迁至派罗星系。
（术语表预替换生效：Stanton System→斯坦顿星系、Pyro→派罗星系）
```

**打包版端到端**（注入真实 F9 按键，验证 exe 内 OCR 模型可用）：

```text
sc_translator.log: 全局热键注册：截图 F9 / 重框 F10 → 成功
sc_translator.log: 截图翻译：5 行，OCR 3524ms，翻译 2074ms，合计 5663ms
exchange.log     : Destination:Area 18,斯坦顿星系 -> 目的地：18区，斯坦顿星系
exchange.log     : Press F to pay respects, then jump to 派罗星系. -> 按F致敬，然后跃迁至派罗星系。
```

**`--doctor` 自检**新增一项：

```text
[PASS] 截图翻译（OCR）: 热键 F9 截图翻译 / F10 重框；区域 未设置（首次按热键会引导框选）；RapidOCR 模型加载 1314ms（已启用）
```

## 实现与测试

| 文件 | 内容 |
| --- | --- |
| `sc_translator/snapshot.py` | 一次性流水线（抓屏→OCR→翻译）、行过滤、热键解析（`F9` / `Ctrl+Shift+S`） |
| `sc_translator/ui/snap_popup.py` | 结果浮窗（拖动/固定/复制/自动淡出/避边） |
| `sc_translator/ui/main_window.py` | 新卡片：热键编辑、立即截图、框选、原文/译文对照 |
| `sc_translator/app.py` `hotkeys.py` | 全局热键注册（窗口重建后自动重注册）、服务生命周期 |
| `tests/test_snapshot.py` | 26 项：热键解析、行过滤、流水线（替身）、失败退化、max_lines、回调投递 |
| `tests/test_packaging.py` | 守住"启动导入图必须保持轻量"（OCR 栈懒加载） |

测试：**144 passed, 1 skipped**。

## 其它

- 版本号 0.3.0 → 0.4.0；三语 README 与 `--doctor` 均已同步更新
- 截图区域、热键、浮窗时长等写入 `data\settings.json`（`snap_region` / `snap_hotkey` / `snap_popup_sec`…）
