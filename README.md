# Star Citizen 翻译器 (SC Translator)

**简体中文** | [繁體中文](README_zh-TW.md) | [English](README_en.md)

面向《星际公民》玩家的 **翻译工具**（Windows 桌面程序）：文字双向翻译 + 按热键的截图翻译。

- **看懂**：把游戏里/群里看到的外文（英文、日文、韩文）粘进来 → 一键译成简体中文
- **回话**：把自己的中文打进去 → 译成 English / Japanese / Korean 并**自动复制到剪贴板**，回游戏直接 Ctrl+V
- **术语表**：`Stanton → 斯坦顿星系`、`Pyro → 派罗星系`，以及从官方 `global.ini` 抽取的 8700+ 条地名/载具/物品/组织译名，在送模型之前先做专名替换
- **嘴臭模式**：一个开关决定用「正常提示词」还是「嘴臭提示词」，无自动检测、无自动生成。**嘴臭提示词明确允许真脏话、人身攻击与歧视性内容**（内容在可编辑的 `prompts\translation_spicy.md` 里；不想要就改它，或不开这个开关）

翻译后端走 **OpenAI 兼容 API**（默认 DeepSeek），提示词与术语表全部外置成可编辑文件。

> 项目形态参考 [ow-translate-lite](https://github.com/reverieach/ow-translate-lite)；
> 早期版本的「实时屏幕翻译」（巡逻截图 + OCR + 悬浮窗）已在 **v0.4.0 换成按需截图翻译**：
> 只在按下热键那一刻抓一帧，不按键完全不占 CPU、也不会持续请求 API（见下文「截图翻译」一节）。

---

## 下载即用（打包版）

在 [Releases](https://github.com/wangcangxing/sc-translator/releases) 下载 `SCTranslator-v*-win64.zip`，解压到任意目录后双击 `SCTranslator.exe`。免安装、免 Python 环境。

```text
SCTranslator\
  SCTranslator.exe        主程序（7 MB，双击即用）
  _internal\              运行库（含 Qt + RapidOCR 模型，约 330 MB），勿删
  prompts\                提示词（可编辑，随包释放）
  data\                   首次运行自动生成：设置 / 加密 Key / 缓存 / 日志
```

- **便携**：整个文件夹拷到别的机器就能用（设置与日志都在 `data\`）
- **自检**：命令行运行 `SCTranslator.exe --doctor` 检查配置/提示词/术语表/游戏码表/**OCR 模型**/**抓屏后端**；
  `SCTranslator.exe --doctor --online` 额外实测一次真实 API 翻译。结果同时写入 `data\logs\doctor.log`
- 首次启动若缺少 `prompts\` 或 `data\sc_glossary.ini`，程序会从内置资源自动释放（不覆盖你改过的文件）

## 使用步骤

1. **申请 API Key**：https://platform.deepseek.com → API Keys（按量计费；文字翻译用量极小）
2. 主窗口选服务商 **DeepSeek**（默认地址 `https://api.deepseek.com`），粘贴 Key
3. **看懂**：把外文粘到左侧 → 点 **翻译到中文**（或 `Ctrl+Enter`）→ 右下结果显示译文
4. **回话**：把中文写到右侧、选目标语言 → 点 **翻译并复制** → 译文自动进剪贴板，回游戏 Ctrl+V
5. 可选：**输出勾选**（回话区「中文码」/「译文」两个复选框）——按需选择中译中、中译英，或两者同时（双行）
6. 可选：勾选/取消 **嘴臭模式**，即刻切换后续译文使用的提示词
7. 可选：顶栏右下角 **界面语言** 下拉框切换 简体中文 / 繁體中文 / English（立即生效，记入 `data\settings.json`）
8. 可选：**截图翻译**——按 **F10** 框选一次游戏里的文字区域，之后按 **Shift+F9** 即可"抓一次 → 识别 → 翻译"，
   结果同时进三处：① 鼠标旁的快看浮窗（8 秒淡出，可固定/复制）② **常驻译文浮窗**（累积历史）③ 主窗口结果区

## 截图翻译（热键按需，不做实时巡逻）

星际公民里遇到看不懂的英文界面、任务简报、聊天，按一下热键就行——**只在按键那一刻抓一帧**，
没有巡逻线程、没有定时采样，不按键完全不占 CPU、不烧 token。

| 热键（可改） | 作用 |
| --- | --- |
| **Shift+F9** | 抓取记住的区域 → 本地 RapidOCR 识别 → 翻译成中文 → 鼠标旁浮窗 + 主窗口结果区 |
| **F10** | 重新框选截图区域（首次使用也走这条） |

- **识别**：本地 RapidOCR（PaddleOCR onnx 模型随包分发，离线可用，不联网、不花钱）
- **翻译**：走你配置的 API，与文字翻译共用术语表/缓存（`Stanton System` → 斯坦顿星系、`Pyro` → 派罗星系）
- **耗时**：首次按键需加载模型（约 1-3 秒，之后常驻内存），此后每次约 **2-6 秒**（OCR 1-3 s + 翻译 1-2 s）
- **设置**（v0.4.9）：右上角「**⚙ 设置**」打开对话框——服务商/API Key/模型、SC 术语表、截图热键、OCR 加速与读图、结果显示位置、译文浮窗、界面语言与日志都在里面；主界面只留翻译与截图触发
- **更快**（v0.4.9）：OCR 检测尺寸按框选大小优化（实测 **−38%**）；同一画面重复按键直接复用上次结果（**0.005 s**）；不再每按一次热键就重新探测 `/models` 并重建连接（省 **2~4.5 s**）；识别一结束**先显示原文**，译文回来原地替换
- **GPU 加速（DirectML）**（设置里可切）：实测 OCR **0.48 s → 0.09 s（约 5 倍）**，固定占用约 200 MB 显存且不随次数增长，关掉即释放；打包版**已内置**运行时，源码运行需 `pip install --force-reinstall --no-deps onnxruntime-directml`
- **模型直接读图**（可选，设置里可切）：把框选的小图**直接交给多模态模型**（如 `deepseek-flash`）一次完成识别+翻译，**不吃本机 CPU/显存**；代价是**截图会上传服务商**、按图片 token 计费（官方上限 1024/张）
- **浮窗**：出现在鼠标旁、避开屏幕边缘，8 秒后自动淡出（可设置/可固定）；鼠标移入暂停倒计时；
  「复制全部」把"原文 → 译文"写进剪贴板，正文也可选中局部复制
- **防误伤**：单次最多翻译 40 行（可设置），避免误框整屏烧 token；纯数字/符号/单字符行自动丢弃
- **结果去哪由你定**：截图卡片里有「结果显示：**常驻悬浮窗** / **鼠标旁浮窗**」两个勾选——可以只留一个，也可以**两个都关**；
  两个都关时结果只写主窗口结果区，手动复制即可（不弹任何浮窗、不打扰游戏画面）
- **常驻译文浮窗**（0.4.0 下线后已重新接线）：截图翻译的结果会**累积**到一个置顶框里，同一句只占一行，
  上限 `max_entries`（默认 120，超出滚动）；未固定时整窗鼠标穿透不挡操作，点边缘「☰ 固定」后可拖动/缩放/右键菜单/「复制全部」；
  点「✕」隐藏后，用主窗口截图卡片里的「显示浮窗」叫回来
- **浮窗回话条**：勾选「浮窗显示回话输入条」即可直接在浮窗里输入中文回话（Enter 翻译，问答记录保留最近 8 条）；
  译文是否自动进剪贴板由「回话译文自动复制」开关决定（默认开）
- **失败退化**：翻译失败（欠费/断网）仍会把识别到的原文显示出来，不会白抓一帧
- **前提**：星际公民请用**窗口化/无边框**运行；独占全屏的 DX 画面可能抓不到（程序会在状态栏说明）

> 体积说明：OCR 需要 `onnxruntime + opencv + rapidocr` 与模型文件，整包因此从 120 MB 涨到约 **330 MB**
> （zip 约 150 MB）。它们是**懒加载**的：不按热键不加载、不常驻。想回到精简包，见 `SCTranslator.spec`
> 顶部注释（把 OCR 相关项重新排除即可，代价是截图翻译不可用）。

## 功能一览

- 双向翻译：外文 → 中文；中文 → English / Japanese / Korean（自动复制）
- **界面三语切换**：顶栏下拉框随时切换 **简体中文 / 繁體中文 / English**，立即生效并记忆
- **输出勾选**：中译中（`[zh] @中文码`）/ 中译英 / 两者同时（双行 `[en] 译文`），回话区与游戏码卡片各一组
- **游戏聊天码**：中文 ↔ 游戏内 `@码`（`你好吗` → `[zh] @IH@E8@AP`），让游戏聊天里也能发中文
- 术语表预替换：8700+ 条官方中英对照（地名 / 载具 / 物品 / 组织），可自行增删
- **常驻译文浮窗**：截图翻译结果累积在置顶框里（同文一行、可固定/穿透、可拖动缩放、一键复制全部），
  并可在浮窗里直接输入中文回话（回话输入条与自动复制各有一个开关）
- 嘴臭模式开关（提示词切换，正常 ⇄ 嘴臭两套，用户可编辑）
- 翻译缓存 + 多行批量请求 + `Ctrl+Enter` 快捷键，重复文本不重复计费
- **完整错误日志**：启动崩溃 / 未捕获异常 / Qt 告警落盘 `data\logs\startup.log`；
  主窗口「日志」按钮直达；`data\logs\exchange.log` 记录每次「输入 → 模型输出」（便于排查空内容与乱码）
- API Key 用 Windows DPAPI 加密，仅当前用户本机可解密
- 深浅两套主题；单实例锁；便携目录结构

## 游戏聊天码（把中文送进游戏聊天）

星际公民聊天框打不了中文，但游戏**本地化语法 `@KEY` 会展开成该键的值**。
社区做法是把 7020 个常用汉字注册成 `global.ini` 里的本地化键（键名 = 汉字序号转 base36），
聊天里只发 `@IH@E8@AP`，客户端就会渲染成「你好吗」。本工具实现了这条路：

- **编码**：左侧输入中文 → 即时得到 `[zh] @IH@E8@AP` → 自动进剪贴板 → 游戏内 `Ctrl+V` 发送
- **解码**：别人发来的 `[zh] @…` 粘到右侧 → **解码为中文**（社区原工具没有反向功能）
- 码表来源：自动检测本机**已装汉化**的 `global.ini`（`…\StarCitizen\LIVE\data\Localization\chinese_(simplified)\global.ini`），
  也可以手动点「浏览…」指定；状态栏会显示码表字数与版本
- 路径会写回 `data\settings.json` 的 `gamecode_ini_path`，之后启动不再扫盘（首次检测约 0.1 秒）

> **前提**：必须安装带「社区输入法支持」的汉化包（SC 汉化盒子安装汉化时勾选，
> 或社区输入法数据已写入你的 `global.ini`）；没装时本功能显示提示但不影响翻译主功能。

实现细节（`sc_translator/gamecode.py`）：

| 规则 | 说明 |
| --- | --- |
| 码表块 | `global.ini` 里 `_…_community_input_method_version=` 与 `_…_localization_version=` 之间的 `码=汉字` 行 |
| 码 | 汉字在码表中的序号转 base36（`0-9A-Z`，最少两位），如 `IH`=665=你、`E8`=512=好、`AP`=385=吗 |
| ASCII/标点 | 原样直通，与码之间补一个空格（`Pyro 见 @Bob` → `[zh] Pyro @31 @Bob`） |
| 未覆盖的字 | 丢成一个空格（与原实现一致） |
| 解码防误伤 | 严格按编码器不变式判定：码后必接空格，所以 `@Bob` 这类玩家名不会被拆成码 |

**输出勾选**（两个复选框，回话区与游戏聊天码卡片各一组，互不影响）：

| 中文码 | 英文/译文 | 输出 | 需要 API |
| :---: | :---: | --- | --- |
| ☑ | ☐ | `[zh] @IH@E8@AP`（中译中：只发中文，中国玩家看得懂） | 否（纯本地） |
| ☐ | ☑ | `How are you`（中译英：只发外语） | 是 |
| ☑ | ☑ | `[zh] @IH@E8@AP` ↲ `[en] How are you`（同时翻译，双方都看得懂） | 是 |

- 两项**至少勾一个**：取消最后一个会自动勾回并提示
- 回话区的"译文"跟随目标语言（English/Japanese/Korean），标记随之变为 `[en]`/`[ja]`/`[ko]`
- 勾选状态写入 `data\settings.json`（`reply_out_code` / `reply_out_foreign`、`gamecode_out_code` / `gamecode_out_en`），下次启动保持
- 本机没有汉化码表时：只勾中文码会提示去装汉化；勾了中文码+译文则**自动退回只输出译文**并提示，不会发出半成品
- 翻译失败/未配 API Key 时也会退化为只发中文码行，保证消息发得出去

## 界面语言（简中 / 繁中 / English）

顶栏右下角的下拉框即可切换，**立即重建界面生效**，无需重启；选择写入 `data\settings.json` 的 `ui_language`。

- 文案表在 `sc_translator/i18n.py`：**一条 key 一行三语**（元组），结构上保证不会漏翻；
  `tests/test_i18n.py` 会检查三语齐全、英文不含中文、繁中确实不同于简中
- 新增文案只需加一行元组；缺失时自动回退简体中文，再回退 key 本身（永不抛异常）
- 翻译进行中会拒绝切换（避免回调写到已销毁的控件），状态栏给出提示
- 服务商下拉的**显示名**随语言变化，**存进设置的值**始终是稳定 key（`DeepSeek`/`OpenAI`/`custom`），
  旧版存过显示名的设置会自动迁移

## 提示词文件（可自行编辑）

提示词不写死在代码里，放在**程序文件夹下的 `prompts\`**（`.md` / `.txt` 纯文本）：

| 文件 | 作用 |
| --- | --- |
| `prompts\translation_normal.md` | 正常翻译提示词。`{src}`→源语言描述，`{target}`→目标语言 |
| `prompts\translation_spicy.md` | 嘴臭模式附加提示（开启时追加到上面之后） |
| `prompts\reply.md` | 回话翻译提示词。`{target}`→English/Japanese/Korean |

- 改完**重启程序**生效；`<!-- … -->` 注释与 `#` 开头行会被剔除，不会发给模型
- 文件缺失/损坏时自动回退内置默认提示词；环境变量 `SC_PROMPTS_DIR` 可指向其它目录

## 术语表（专名预替换）

`data\sc_glossary.ini`，每行 `英文词条=规范中文译名`，可自由增删。例如：

```ini
Stanton=斯坦顿星系
Pyro=派罗星系
Area18=18 区
```

匹配为**大小写不敏感 + 词边界**，多词条目优先；未配置路径时自动使用随包术语表。
（`data\settings.json` 里 `glossary_enabled` 可整体关闭。）

## 源码运行

Windows 10/11 x64 + Python 3.10+。

```powershell
# 方式一：双击 run.bat（首次自动建虚拟环境并装依赖，1-3 分钟）
# 方式二：手动
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m sc_translator
```

## 自行打包 exe

```powershell
# 双击 build.bat，或：
.\.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SCTranslator.spec
# 产物：dist\SCTranslator\SCTranslator.exe（onedir，约 120 MB，含 Qt）
```

打包包含：PySide6(Core/Gui/Widgets) + requests（文字翻译）+ rapidocr/onnxruntime/opencv（按需截图翻译）。
OCR 栈是**懒加载**的，不进启动路径，因此冷启动仍是约 1 秒、常驻内存也不含模型；
tests/test_packaging.py 会守住这条底线：启动导入图里一旦出现重型依赖，测试直接失败。

发布到 GitHub：双击 `publish.bat`（配置 origin → 推送 `main` → 复制发行说明到剪贴板并打开 Release 页面），
再把 `dist\SCTranslator-v0.4.5-win64.zip` 拖进 Release 附件区即可。

## 配置与数据

| 路径 | 说明 |
| --- | --- |
| `data\settings.json` | 全部设置（服务商 / 模型 / 嘴臭开关 / 术语表开关…） |
| `data\api_key.bin` | DPAPI 加密的 API Key |
| `data\cache.json` | 翻译缓存 |
| `data\sc_glossary.ini` | 术语表（便携版首次运行自动释放） |
| `data\logs\startup.log` | 启动/崩溃日志（`run.bat` 失败时自动显示尾部） |
| `data\logs\sc_translator.log` | 运行期日志 |
| `data\logs\exchange.log` | 输入/输出交换日志（时间/类型/模型/风格/输入/输出或错误） |
| `data\logs\doctor.log` | `--doctor` 自检报告 |

- 数据目录默认是**程序所在文件夹的 `data\`**（便携）；`SC_TRANSLATOR_HOME` 可强制重定向
- 旧版 `%APPDATA%\SCTranslator` 数据会在首次运行时自动迁移
- 单实例运行；异常退出后 15 秒内重启若提示“已在运行”，删除 `data\instance.lock` 即可

## 常见问题

- **点“翻译”没反应 / 提示缺少 Key**：先填 API Key；`SCTranslator.exe --doctor` 可快速定位
- **提示“模型返回了空内容（HTTP 200）”**：这是**思考模式**造成的——DeepSeek 模型**默认开启思考**（effort 默认 `high`），
  短翻译请求的输出预算会被思维链吃掉，于是 HTTP 200 但 `content` 为空。程序现在会自动：
  ① 对 `deepseek*` 模型加 `{"thinking":{"type":"disabled"}}`；
  ② 若仍为空，自动改“关闭思考”重试一次；
  ③ 单行输出预算下限提到 256；
  ④ 两次都空时在错误里给出 `finish_reason` 与 `reasoning_tokens`（说明是“思考吃满预算”）。
  实测同一句：不带参数输出 85 token、带 `disabled` 只要 7。详见 `docs\参考-DeepSeek思考模式.md`
- **双击无窗口 / 启动失败**：看 `data\logs\startup.log` 与 `sc_translator.log`；
  源码运行可直接命令行执行 `python -m sc_translator` 看报错
- **译文不理想**：改 `prompts\` 下的提示词，或把术语补进 `data\sc_glossary.ini`，再重启
- **嘴臭模式**：只是提示词开关，切换后对后续译文即时生效
- **费用**：相同文本走缓存不重复请求；文字翻译与截图翻译（按次）一天通常几分钱级别

## 开发者

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m pytest tests -q        # 198 passed, 1 skipped
```

```text
main.py / build.bat / SCTranslator.spec   打包入口与 PyInstaller 配置
sc_translator/
  __main__.py         启动入口（崩溃日志 / 单实例锁 / --doctor 自检）
  app.py              应用装配（主窗口 + 客户端 + 术语表 + 缓存）
  bootstrap.py        首次运行释放 prompts\ 与术语表
  prompts.py          提示词文件加载与回退
  glossary.py         术语表（专名预替换）
  gamecode.py         游戏聊天码（码表解析 / 编码 / 解码）
  i18n.py             界面三语文案表（简中/繁中/English）
  snapshot.py         按需截图翻译（热键 -> 抓屏 -> OCR -> 翻译）
  ocr.py screen.py    本地 OCR 与多屏/DPI 抓屏（截图翻译用）
  ui/snap_popup.py    截图翻译结果浮窗
  textutil.py         轻量文本工具（汉字占比）
  paths.py settings.py secrets.py logger_setup.py exchange_log.py
  translate/          缓存 + OpenAI 兼容客户端（批量/重试/思考模式关闭）
  ui/                 主窗口 / 结果浮窗 / 框选 / 主题
assets/               应用图标 + 术语表源文件（打包用）
prompts/              随包提示词默认内容
tests/                单元 + 集成 + 打包回归
```

## 免责声明

第三方社区项目，与 Cloud Imperium Games 无关；本工具只做翻译（文本输入，或按热键截取屏幕文字后本地识别），不修改游戏文件、不注入进程。
请遵守游戏与翻译 API 服务商的使用条款，自行承担使用风险。以 MIT 协议发布。
