# Star Citizen 翻譯器 (SC Translator)

[简体中文](README.md) | **繁體中文** | [English](README_en.md)

面向《星際公民》玩家的 **翻譯工具**（Windows 桌面程式）：文字雙向翻譯 + 按熱鍵的截圖翻譯。

- **看懂**：把遊戲裡／群組裡看到的外文（英文、日文、韓文）貼進來 → 一鍵譯成簡體中文
- **回話**：把自己的中文打進去 → 譯成 English / Japanese / Korean 並**自動複製到剪貼簿**，回遊戲直接 Ctrl+V
- **詞彙表**：`Stanton → 斯坦頓星系`、`Pyro → 派羅星系`，以及從官方 `global.ini` 抽取的 8700+ 條地名／載具／物品／組織譯名，在送模型之前先做專名替換
- **嘴砲模式**：一個開關決定用「正常提示詞」還是「嘴砲提示詞」，無自動偵測、無自動生成。**嘴砲提示詞明確允許真正的髒話、人身攻擊與歧視性內容**（內容在可編輯的 `prompts\translation_spicy.md` 裡；不想要就改它，或別開這個開關）

翻譯後端走 **OpenAI 相容 API**（預設 DeepSeek），提示詞與詞彙表全部外置成可編輯檔案。

> 程式介面支援**簡體中文 / 繁體中文 / English** 三語切換（頂欄右下角下拉框，立即生效）。
> 專案形態參考 [ow-translate-lite](https://github.com/reverieach/ow-translate-lite)；
> 早期版本的「即時螢幕翻譯」（巡邏截圖 + OCR + 懸浮窗）已在 **v0.4.0 換成按需截圖翻譯**：
> 只在按下熱鍵那一刻抓一幀，不按鍵完全不佔 CPU、也不會持續請求 API（見下文「截圖翻譯」一節）。

---

## 下載即用（打包版）

在 [Releases](https://github.com/wangcangxing/sc-translator/releases) 下載 `SCTranslator-v*-win64.zip`，解壓到任意資料夾後雙擊 `SCTranslator.exe`。免安裝、免 Python 環境。

```text
SCTranslator\
  SCTranslator.exe        主程式（7 MB，雙擊即用）
  _internal\              執行庫（含 Qt + RapidOCR 模型，約 330 MB），請勿刪除
  prompts\                提示詞（可編輯，隨包釋出）
  data\                   首次執行自動產生：設定 / 加密 Key / 快取 / 記錄
```

- **可攜**：整個資料夾複製到別台電腦就能用（設定與記錄都在 `data\`）
- **自我檢查**：命令列執行 `SCTranslator.exe --doctor` 檢查設定／提示詞／詞彙表／遊戲碼表／OCR 模型／**抓屏後端**；
  `SCTranslator.exe --doctor --online` 額外實測一次真實 API 翻譯。結果同時寫入 `data\logs\doctor.log`
- 首次啟動若缺少 `prompts\` 或 `data\sc_glossary.ini`，程式會從內建資源自動釋出（不會覆蓋你改過的檔案）

## 使用步驟

1. **申請 API Key**：https://platform.deepseek.com → API Keys（按量計費；文字翻譯用量極小）
2. 主視窗選服務商 **DeepSeek**（預設位址 `https://api.deepseek.com`），貼上 Key
3. **看懂**：把外文貼到左側 → 點 **翻譯到中文**（或 `Ctrl+Enter`）→ 右下結果顯示譯文
4. **回話**：把中文寫到右側、選目標語言 → 點 **翻譯並複製** → 譯文自動進剪貼簿，回遊戲 Ctrl+V
5. 選用：**輸出勾選**（回話區「中文碼」／「譯文」兩個核取方塊）——依需求選擇中譯中、中譯英，或兩者同時（雙行）
6. 選用：勾選／取消 **嘴砲模式**，即刻切換後續譯文使用的提示詞
7. 選用：頂欄右下角 **介面語言** 下拉框切換 簡體中文 / 繁體中文 / English（立即生效，記入 `data\settings.json`）
8. 選用：**截圖翻譯**——按 **F10** 框選一次遊戲裡的文字區域，之後按 **Shift+F9** 即可「抓一次 → 辨識 → 翻譯」，
   結果同時進三處：① 滑鼠旁的快看浮窗（8 秒淡出，可固定／複製）② **常駐譯文浮窗**（累積歷史）③ 主視窗結果區

## 功能一覽

- 雙向翻譯：外文 → 中文；中文 → English / Japanese / Korean（自動複製）
- **按需截圖翻譯**：全域熱鍵 **Shift+F9** 抓一次記住的區域 → 本機 RapidOCR → 翻譯，滑鼠旁浮窗顯示；**F10** 重新框選。不按鍵完全不耗資源（無巡邏、無定時取樣）
- **介面三語切換**：頂欄下拉框隨時切換 **簡體中文 / 繁體中文 / English**，立即生效並記憶
- **輸出勾選**：中譯中（`[zh] @中文碼`）／中譯英／兩者同時（雙行 `[en] 譯文`），回話區與遊戲碼卡片各一組
- **遊戲聊天碼**：中文 ↔ 遊戲內 `@碼`（`你好嗎` → `[zh] @IH@E8@AP`），讓遊戲聊天裡也能發中文
- 詞彙表預替換：8700+ 條官方中英對照（地名／載具／物品／組織），可自行增刪
- **結果去哪由你決定**：截圖卡片裡有「結果顯示：**常駐懸浮框**／**滑鼠旁浮窗**」兩個勾選——可以只留一個，也可以**兩個都關**；
  兩個都關時結果只寫主視窗結果區，手動複製即可（不彈任何浮窗、不打擾遊戲畫面）
- **常駐譯文浮窗**（0.4.0 下線後已重新接線）：截圖翻譯結果**累積**在置頂框裡，同一句只佔一行，
  上限 `max_entries`（預設 120，超出捲動）；未固定時整窗滑鼠穿透不擋操作，點邊緣「☰ 固定」後可拖動／縮放／右鍵選單／「複製全部」；
  點「✕」隱藏後，用主視窗截圖卡片裡的「顯示浮窗」叫回來
- **浮窗回話列**：勾選「浮窗顯示回話輸入條」即可直接在浮窗裡輸入中文回話（Enter 翻譯，問答記錄保留最近 8 條）；
  譯文是否自動進剪貼簿由「回話譯文自動複製」開關決定（預設開）
- 嘴砲模式開關（提示詞切換，正常 ⇄ 嘴砲兩套，使用者可編輯）
- 翻譯快取 + 多行批次請求 + `Ctrl+Enter` 快速鍵，重複文字不重複計費
- **完整錯誤記錄**：啟動崩潰／未捕捉例外／Qt 警告寫入 `data\logs\startup.log`；
  主視窗「日誌」按鈕直達；`data\logs\exchange.log` 記錄每次「輸入 → 模型輸出」（便於排查空內容與亂碼）
- API Key 以 Windows DPAPI 加密，僅目前使用者本機可解密
- 深淺兩套主題；單一實例鎖；可攜目錄結構

## 遊戲聊天碼（把中文送進遊戲聊天）

星際公民聊天框打不了中文，但遊戲**在地化語法 `@KEY` 會展開成該鍵的值**。
社群做法是把 7020 個常用漢字註冊成 `global.ini` 裡的在地化鍵（鍵名＝漢字序號轉 base36），
聊天裡只發 `@IH@E8@AP`，客戶端就會顯示「你好嗎」。本工具實作了這條路：

- **編碼**：左側輸入中文 → 即時得到 `[zh] @IH@E8@AP` → 自動進剪貼簿 → 遊戲內 `Ctrl+V` 傳送
- **解碼**：別人傳來的 `[zh] @…` 貼到右側 → **解碼為中文**（社群原工具沒有反向功能）
- 碼表來源：自動偵測本機**已安裝漢化**的 `global.ini`（`…\StarCitizen\LIVE\data\Localization\chinese_(simplified)\global.ini`），
  也可以手動點「瀏覽…」指定；狀態列會顯示碼表字數與版本
- 路徑會寫回 `data\settings.json` 的 `gamecode_ini_path`，之後啟動不再掃描磁碟（首次偵測約 0.1 秒）

> **前提**：必須安裝帶「社群輸入法支援」的漢化包（SC 漢化盒子安裝漢化時勾選，
> 或社群輸入法資料已寫入你的 `global.ini`）；沒安裝時本功能顯示提示，但不影響翻譯主功能。

實作細節（`sc_translator/gamecode.py`）：

| 規則 | 說明 |
| --- | --- |
| 碼表區塊 | `global.ini` 裡 `_…_community_input_method_version=` 與 `_…_localization_version=` 之間的 `碼=漢字` 行 |
| 碼 | 漢字在碼表中的序號轉 base36（`0-9A-Z`，最少兩位），如 `IH`=665=你、`E8`=512=好、`AP`=385=嗎 |
| ASCII／標點 | 原樣直通，與碼之間補一個空格（`Pyro 见 @Bob` → `[zh] Pyro @31 @Bob`） |
| 未涵蓋的字 | 丟成一個空格（與原實作一致） |
| 解碼防誤傷 | 嚴格依編碼器不變式判定：碼後必接空格，所以 `@Bob` 這類玩家名稱不會被拆成碼 |

**輸出勾選**（兩個核取方塊，回話區與遊戲聊天碼卡片各一組，互不影響）：

| 中文碼 | 英文／譯文 | 輸出 | 需要 API |
| :---: | :---: | --- | --- |
| ☑ | ☐ | `[zh] @IH@E8@AP`（中譯中：只發中文，中國玩家看得懂） | 否（純本機） |
| ☐ | ☑ | `How are you`（中譯英：只發外語） | 是 |
| ☑ | ☑ | `[zh] @IH@E8@AP` ↲ `[en] How are you`（同時翻譯，雙方都看得懂） | 是 |

- 兩項**至少勾一個**：取消最後一個會自動勾回並提示
- 回話區的「譯文」跟隨目標語言（English/Japanese/Korean），標記隨之變為 `[en]`／`[ja]`／`[ko]`
- 勾選狀態寫入 `data\settings.json`（`reply_out_code` / `reply_out_foreign`、`gamecode_out_code` / `gamecode_out_en`），下次啟動保持
- 本機沒有漢化碼表時：只勾中文碼會提示去安裝漢化；勾了中文碼+譯文則**自動退回只輸出譯文**並提示，不會發出半成品
- 翻譯失敗／未設定 API Key 時也會退化為只發中文碼行，確保訊息送得出去

## 介面語言（簡中 / 繁中 / English）

頂欄右下角的下拉框即可切換，**立即重建介面生效**，無需重新啟動；選擇寫入 `data\settings.json` 的 `ui_language`。

- 文案表在 `sc_translator/i18n.py`：**一條 key 一行三語**（元組），結構上保證不漏翻；
  `tests/test_i18n.py` 會檢查三語齊全、英文不含中文、繁中確實不同於簡中
- 新增文案只需加一行元組；缺失時自動回退簡體中文，再回退 key 本身
- 翻譯進行中會拒絕切換（避免回呼寫到已銷毀的控件），狀態列會提示
- 服務商下拉的**顯示名**隨語言改變，**存進設定的值**始終是穩定 key，舊版存過顯示名的設定會自動移轉

## 截圖翻譯（熱鍵按需，不做即時巡邏）

遊戲裡遇到看不懂的英文介面、任務簡報、聊天，按一下熱鍵就好——**只在按鍵那一刻抓一幀**，
沒有巡邏執行緒、沒有定時取樣，不按鍵完全不佔 CPU、不浪費 token。

| 熱鍵（可改） | 作用 |
| --- | --- |
| **Shift+F9** | 抓取記住的區域 → 本機 RapidOCR 辨識 → 翻譯成中文 → 滑鼠旁浮窗 + 主視窗結果區 |
| **F10** | 重新框選截圖區域（首次使用也走這條） |

- **辨識**：本機 RapidOCR（PaddleOCR onnx 模型隨包，離線可用、不連網、不花錢）
- **翻譯**：走你設定的 API，與文字翻譯共用詞彙表/快取（`Stanton System` → 斯坦頓星系、`Pyro` → 派羅星系）
- **耗時**：首次按鍵需載入模型（約 1-3 秒，之後常駐記憶體），之後每次約 **2-6 秒**
- **設定**（v0.4.9）：右上角「**⚙ 設定**」開啟對話框——服務商/API Key/模型、SC 術語表、截圖熱鍵、OCR 加速與讀圖、結果顯示位置、譯文懸浮框、介面語言與日誌都在裡面；主介面只留翻譯與截圖觸發
- **更快**（v0.4.9）：OCR 偵測尺寸依框選大小最佳化（實測 **−38%**）；同一畫面重複按鍵直接重用上次結果（**0.005 s**）；不再每按一次熱鍵就重新探測 `/models` 並重建連線（省 **2~4.5 s**）；辨識一結束**先顯示原文**，譯文回來原地替換
- **GPU 加速（DirectML）**（設定裡可切）：實測 OCR **0.48 s → 0.09 s（約 5 倍）**，固定佔用約 200 MB 顯存且不隨次數成長，關掉即釋放；打包版**已內建**執行階段，原始碼執行需 `pip install --force-reinstall --no-deps onnxruntime-directml`
- **模型直接讀圖**（可選，設定裡可切）：把框選的小圖**直接交給多模態模型**（如 `deepseek-flash`）一次完成辨識+翻譯，**不吃本機 CPU/顯存**；代價是**截圖會上傳服務商**、依圖片 token 計費（官方上限 1024/張）
- **浮窗**：出現在滑鼠旁、自動避開螢幕邊緣，8 秒後淡出（可設定/可固定）；滑鼠移入暫停倒數；
  「複製全部」把「原文 → 譯文」寫進剪貼簿
- **防誤傷**：單次最多翻譯 40 行（可設定）；純數字/符號/單字元行自動丟棄
- **失敗退化**：翻譯失敗（欠費/斷網）仍會顯示辨識到的原文
- **前提**：星際公民請用**視窗化/無邊框**執行；獨占全螢幕的 DX 畫面可能抓不到

> 體積說明：OCR 需要 `onnxruntime + opencv + rapidocr` 與模型檔，整包因此從 120 MB 漲到約 **330 MB**
> （zip 約 150 MB）。它們是**懶載入**的：不按熱鍵不載入、不常駐。想回到精簡包見 `SCTranslator.spec` 頂部註解。

## 提示詞檔案（可自行編輯）

提示詞不寫死在程式裡，放在**程式資料夾下的 `prompts\`**（`.md` / `.txt` 純文字）：

| 檔案 | 作用 |
| --- | --- |
| `prompts\translation_normal.md` | 正常翻譯提示詞。`{src}`→來源語言描述，`{target}`→目標語言 |
| `prompts\translation_spicy.md` | 嘴砲模式附加提示（開啟時追加到上面之後） |
| `prompts\reply.md` | 回話翻譯提示詞。`{target}`→English/Japanese/Korean |

- 改完**重新啟動程式**生效；`<!-- … -->` 註解與 `#` 開頭行會被剔除，不會送給模型
- 檔案缺失／損毀時自動回退內建預設提示詞；環境變數 `SC_PROMPTS_DIR` 可指向其它目錄

## 詞彙表（專名預替換）

`data\sc_glossary.ini`，每行 `英文詞條=規範中文譯名`，可自由增刪。例如：

```ini
Stanton=斯坦顿星系
Pyro=派罗星系
Area18=18 区
```

比對為**大小寫不敏感 + 詞邊界**，多詞詞條優先；未設定路徑時自動使用隨包詞彙表。
（`data\settings.json` 裡 `glossary_enabled` 可整體關閉。）

## 以原始碼執行

Windows 10/11 x64 + Python 3.10+。

```powershell
# 方式一：雙擊 run.bat（首次自動建立虛擬環境並安裝相依套件，1-3 分鐘）
# 方式二：手動
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m sc_translator
```

## 自行打包 exe

```powershell
# 雙擊 build.bat，或：
.\.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SCTranslator.spec
# 產物：dist\SCTranslator\SCTranslator.exe（onedir，約 120 MB，含 Qt）
```

打包只包含文字翻譯所需的 PySide6(Core/Gui/Widgets) + requests；
OCR／本機模型／影像處理（numpy、opencv、onnxruntime、llama-cpp…）全部排除，因此體積與啟動時間都很小（冷啟動約 1 秒）。
`tests/test_packaging.py` 會守住這條底線：一旦匯入圖出現重量級相依，測試直接失敗。

發佈到 GitHub：雙擊 `publish.bat`（設定 origin → 推送 `main` → 複製發行說明到剪貼簿並開啟 Release 頁面），
再把 `dist\SCTranslator-v0.4.5-win64.zip` 拖進 Release 附件區即可。

## 設定與資料

| 路徑 | 說明 |
| --- | --- |
| `data\settings.json` | 全部設定（服務商／模型／嘴砲開關／詞彙表開關…） |
| `data\api_key.bin` | DPAPI 加密的 API Key |
| `data\cache.json` | 翻譯快取 |
| `data\sc_glossary.ini` | 詞彙表（可攜版首次執行自動釋出） |
| `data\logs\startup.log` | 啟動／崩潰記錄（`run.bat` 失敗時自動顯示尾段） |
| `data\logs\sc_translator.log` | 執行期記錄 |
| `data\logs\exchange.log` | 輸入／輸出交換記錄（時間／類型／模型／風格／輸入／輸出或錯誤） |
| `data\logs\doctor.log` | `--doctor` 自我檢查報告 |

- 資料目錄預設是**程式所在資料夾的 `data\`**（可攜）；`SC_TRANSLATOR_HOME` 可強制重導
- 舊版 `%APPDATA%\SCTranslator` 資料會在首次執行時自動移轉
- 單一實例執行；異常結束後 15 秒內重啟若提示「已在執行」，刪除 `data\instance.lock` 即可

## 常見問題

- **點「翻譯」沒反應／提示缺少 Key**：先填 API Key；`SCTranslator.exe --doctor` 可快速定位
- **提示「模型返回了空內容（HTTP 200）」**：這是**思考模式**造成的——DeepSeek 模型**預設開啟思考**（effort 預設 `high`），
  短翻譯請求的輸出預算會被思維鏈吃掉，於是 HTTP 200 但 `content` 為空。程式現在會自動：
  ① 對 `deepseek*` 模型加 `{"thinking":{"type":"disabled"}}`；
  ② 若仍為空，自動改「關閉思考」重試一次；
  ③ 單行輸出預算下限提高到 256；
  ④ 兩次都空時在錯誤裡給出 `finish_reason` 與 `reasoning_tokens`。
  實測同一句：不帶參數輸出 85 token、帶 `disabled` 只要 7。詳見 `docs\参考-DeepSeek思考模式.md`
- **雙擊沒視窗／啟動失敗**：看 `data\logs\startup.log` 與 `sc_translator.log`；
  以原始碼執行可直接在命令列執行 `python -m sc_translator` 看錯誤
- **譯文不理想**：改 `prompts\` 下的提示詞，或把術語補進 `data\sc_glossary.ini`，再重新啟動
- **嘴砲模式**：只是提示詞開關，切換後對後續譯文即時生效
- **費用**：相同文字走快取不重複請求；純文字聊天情境一天通常幾分錢等級

## 開發者

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m pytest tests -q        # 198 passed, 1 skipped
```

```text
main.py / build.bat / SCTranslator.spec   打包進入點與 PyInstaller 設定
sc_translator/
  __main__.py         啟動進入點（崩潰記錄 / 單一實例鎖 / --doctor 自我檢查）
  app.py              應用組裝（主視窗 + 客戶端 + 詞彙表 + 快取）
  bootstrap.py        首次執行釋出 prompts\ 與詞彙表
  prompts.py          提示詞檔案載入與回退
  glossary.py         詞彙表（專名預替換）
  gamecode.py         遊戲聊天碼（碼表解析 / 編碼 / 解碼）
  textutil.py         輕量文字工具（漢字佔比）
  paths.py settings.py secrets.py logger_setup.py exchange_log.py
  translate/          快取 + OpenAI 相容客戶端（批次／重試／關閉思考模式）
  ui/                 主視窗 / 主題
assets/               應用圖示 + 詞彙表來源檔（打包用）
prompts/              隨包提示詞預設內容
tests/                單元 + 整合 + 打包回歸
```

## 免責聲明

第三方社群專案，與 Cloud Imperium Games 無關；本工具只做翻譯（文字輸入，或按熱鍵截取螢幕文字後本機辨識），不修改遊戲檔案、不注入行程。
請遵守遊戲與翻譯 API 服務商的使用條款，自行承擔使用風險。以 MIT 授權條款發佈。
