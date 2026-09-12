# Star Citizen 翻译器 (SC Translator)

面向《星际公民》玩家的 **双向文字翻译器**（Windows 桌面程序，纯文本输入输出）：

- **看懂**：把游戏里/群里看到的外文（英文、日文、韩文）粘进来 → 一键译成简体中文
- **回话**：把自己的中文打进去 → 译成 English / Japanese / Korean 并**自动复制到剪贴板**，回游戏直接 Ctrl+V
- **术语表**：`Stanton → 斯坦顿星系`、`Pyro → 派罗星系`，以及从官方 `global.ini` 抽取的 1200+ 条地名/载具/物品/组织译名，在送模型之前先做专名替换
- **嘴臭模式**：一个开关决定用「正常提示词」还是「嘴臭提示词」（嘲讽垃圾话风格，不涉真脏话），无自动检测、无自动生成

翻译后端走 **OpenAI 兼容 API**（默认 DeepSeek），提示词与术语表全部外置成可编辑文件。

> 项目形态参考 [ow-translate-lite](https://github.com/reverieach/ow-translate-lite)；
> 早期版本做过「框选屏幕 + OCR + 悬浮窗」的实时屏幕翻译，现已**移除屏幕翻译**，只保留更省 CPU、更省 token 的纯文字翻译。

---

## 下载即用（打包版）

在 [Releases](https://github.com/rtgi6/sc-translator/releases) 下载 `SCTranslator-v*-win64.zip`，解压到任意目录后双击 `SCTranslator.exe`。免安装、免 Python 环境。

```text
SCTranslator\
  SCTranslator.exe        主程序（4 MB，双击即用）
  _internal\              运行库（含 Qt），勿删
  prompts\                提示词（可编辑，随包释放）
  data\                   首次运行自动生成：设置 / 加密 Key / 缓存 / 日志
```

- **便携**：整个文件夹拷到别的机器就能用（设置与日志都在 `data\`）
- **自检**：命令行运行 `SCTranslator.exe --doctor` 检查配置/提示词/术语表；
  `SCTranslator.exe --doctor --online` 额外实测一次真实 API 翻译。结果同时写入 `data\logs\doctor.log`
- 首次启动若缺少 `prompts\` 或 `data\sc_glossary.ini`，程序会从内置资源自动释放（不覆盖你改过的文件）

## 使用步骤

1. **申请 API Key**：https://platform.deepseek.com → API Keys（按量计费；文字翻译用量极小）
2. 主窗口选服务商 **DeepSeek**（默认地址 `https://api.deepseek.com`），粘贴 Key
3. **看懂**：把外文粘到左侧 → 点 **翻译到中文**（或 `Ctrl+Enter`）→ 右下结果显示译文
4. **回话**：把中文写到右侧、选目标语言 → 点 **翻译并复制** → 译文自动进剪贴板，回游戏 Ctrl+V
5. 可选：勾选/取消 **嘴臭模式**，即刻切换后续译文使用的提示词

## 功能一览

- 双向翻译：外文 → 中文；中文 → English / Japanese / Korean（自动复制）
- 术语表预替换：1200+ 条官方中英对照（地名 / 载具 / 物品 / 组织），可自行增删
- 嘴臭模式开关（提示词切换，正常 ⇄ 嘴臭两套，用户可编辑）
- 翻译缓存 + 多行批量请求 + `Ctrl+Enter` 快捷键，重复文本不重复计费
- **完整错误日志**：启动崩溃 / 未捕获异常 / Qt 告警落盘 `data\logs\startup.log`；
  主窗口「日志」按钮直达；`data\logs\exchange.log` 记录每次「输入 → 模型输出」（便于排查空内容与乱码）
- API Key 用 Windows DPAPI 加密，仅当前用户本机可解密
- 深浅两套主题；单实例锁；便携目录结构

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

打包只包含文字翻译所需的 PySide6(Core/Gui/Widgets) + requests；
OCR / 本地模型 / 图像处理（numpy、opencv、onnxruntime、llama-cpp…）全部排除，因此体积与启动时间都很小（冷启动约 1 秒）。
`tests/test_packaging.py` 会守住这条底线：一旦导入图里出现重型依赖，测试直接失败。

发布到 GitHub：双击 `publish.bat`（配置 origin → 推送 `main` → 复制发行说明到剪贴板并打开 Release 页面），
再把 `dist\SCTranslator-v0.1.0-win64.zip` 拖进 Release 附件区即可。

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
- **提示“模型返回了空内容”**：`deepseek-v4-*` 系列默认开启 Thinking，普通 chat 请求会返回空 `content`；
  程序已自动为该系列附加 `"thinking":{"type":"disabled"}`，重启后重试即可
- **双击无窗口 / 启动失败**：看 `data\logs\startup.log` 与 `sc_translator.log`；
  源码运行可直接命令行执行 `python -m sc_translator` 看报错
- **译文不理想**：改 `prompts\` 下的提示词，或把术语补进 `data\sc_glossary.ini`，再重启
- **嘴臭模式**：只是提示词开关，切换后对后续译文即时生效
- **费用**：相同文本走缓存不重复请求；纯文字聊天场景一天通常几分钱级别

## 开发者

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m pytest tests -q        # 68 passed
```

```text
main.py / build.bat / SCTranslator.spec   打包入口与 PyInstaller 配置
sc_translator/
  __main__.py         启动入口（崩溃日志 / 单实例锁 / --doctor 自检）
  app.py              应用装配（主窗口 + 客户端 + 术语表 + 缓存）
  bootstrap.py        首次运行释放 prompts\ 与术语表
  prompts.py          提示词文件加载与回退
  glossary.py         术语表（专名预替换）
  textutil.py         轻量文本工具（汉字占比）
  paths.py settings.py secrets.py logger_setup.py exchange_log.py
  translate/          缓存 + OpenAI 兼容客户端（批量/重试/思考模式关闭）
  ui/                 主窗口 / 主题
assets/               应用图标 + 术语表源文件（打包用）
prompts/              随包提示词默认内容
tests/                单元 + 集成 + 打包回归
```

## 免责声明

第三方社区项目，与 Cloud Imperium Games 无关；本工具只做文本翻译，不修改游戏文件、不注入进程。
请遵守游戏与翻译 API 服务商的使用条款，自行承担使用风险。以 MIT 协议发布。
