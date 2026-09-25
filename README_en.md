# Star Citizen Translator (SC Translator)

[简体中文](README.md) | [繁體中文](README_zh-TW.md) | **English**

A **translation toolkit for Star Citizen players** (Windows desktop app): two-way text translation plus on-demand screenshot translation.

- **Understand**: paste foreign text you see in game or in chat (English / Japanese / Korean) → one click to Simplified Chinese
- **Reply**: type your Chinese → translated to English / Japanese / Korean and **auto-copied to the clipboard**, ready to `Ctrl+V` in game
- **Glossary**: `Stanton → 斯坦顿星系`, `Pyro → 派罗星系`, plus 8700+ term pairs mined from the official `global.ini` (locations / vehicles / items / organizations), applied as proper-noun pre-replacement before the model call
- **Spicy mode**: a single toggle that picks the "normal" or the "spicy" prompt set. No auto-detection, no auto-generation. **The spicy prompt explicitly permits real profanity, personal insults and discriminatory content** (it lives in the editable `prompts\translation_spicy.md`; edit it or leave the toggle off if you don't want that)

Translation runs against any **OpenAI-compatible API** (DeepSeek by default). Prompts and glossary are external editable files.

> The UI ships in **Simplified Chinese / Traditional Chinese / English** — switch it from the dropdown in the top-right corner, effective immediately.
> Project shape inspired by [ow-translate-lite](https://github.com/reverieach/ow-translate-lite);
> The earlier "real-time screen translation" (polling capture + OCR + overlay) was replaced in **v0.4.0 by
> on-demand screenshot translation**: exactly one frame is captured when you press the hotkey, so the idle
> cost is zero in CPU and nothing is sent to the API unless you ask for it (see the section below).

---

## Download & run (packaged build)

Get `SCTranslator-v*-win64.zip` from [Releases](https://github.com/w2310670047-code/sc-translator/releases), extract anywhere, double-click `SCTranslator.exe`. No installer, no Python required.

```text
SCTranslator\
  SCTranslator.exe        main program (7 MB)
  _internal\              runtime (includes Qt + RapidOCR models, ~330 MB) — do not delete
  prompts\                prompts (editable, extracted on first run)
  data\                   created on first run: settings / encrypted key / cache / logs
```

- **Portable**: copy the whole folder to another machine and it keeps your settings and logs (all under `data\`)
- **Self-check**: run `SCTranslator.exe --doctor` to verify settings / prompts / glossary / game code table / OCR models / **capture backends**;
  `SCTranslator.exe --doctor --online` additionally performs one real API translation. The report is also written to `data\logs\doctor.log`
- On first launch the app extracts `prompts\` and `data\sc_glossary.ini` from bundled resources if missing (it never overwrites files you edited)

## Getting started

1. **Get an API key**: https://platform.deepseek.com → API Keys (pay-as-you-go; text translation costs very little)
2. In the main window pick provider **DeepSeek** (default base `https://api.deepseek.com`) and paste the key
3. **Understand**: paste foreign text on the left → click **翻译到中文** (or press `Ctrl+Enter`) → the translation appears bottom-right
4. **Reply**: type your Chinese on the right, pick a target language → click **翻译并复制** → the translation is copied to the clipboard, ready to `Ctrl+V` in game
5. Optional: **output checkboxes** (「中文码」/「译文」 in the reply pane) to choose Chinese-to-Chinese, Chinese-to-foreign, or both at once (two lines)
6. Optional: toggle **spicy mode** to switch which prompt set is used for subsequent translations
7. Optional: use the **Language** dropdown in the top-right corner to switch Simplified Chinese / Traditional Chinese / English (instant, stored in `data\settings.json`)
8. Optional: **screenshot translation** — press **F10** once to select the text area in game, then press **Shift+F9** any time to "capture once → OCR → translate"; the result goes to three places: ① a quick popup next to the cursor (auto-fades, pinnable/copyable) ② a **persistent overlay** that accumulates the history ③ the main window panes

## Features

- Two-way translation: foreign → Chinese; Chinese → English / Japanese / Korean (auto-copied)
- **On-demand screenshot translation**: press **Shift+F9** to capture a remembered region → local RapidOCR → translate, shown in a floating popup next to the cursor; **F10** re-selects the region. Idle cost is zero (no polling loop, no timed sampling)
- **Trilingual UI**: switch between **Simplified Chinese / Traditional Chinese / English** from the top-bar dropdown — applied instantly and remembered
- **Output checkboxes**: zh→zh (`[zh] @code`), zh→foreign, or both (two lines: `[zh] @…` + `[en] …`) — one set in the reply pane, one in the game-chat-code card
- **Game chat code**: Chinese ↔ in-game `@code` (`你好吗` → `[zh] @IH@E8@AP`), so you can actually send Chinese in game chat
- Glossary pre-replacement: 1200+ official EN/ZH pairs (locations / vehicles / items / organizations), fully editable
- **You decide where results go**: the screenshot card has 「Show results in: **Persistent overlay** / **Popup by cursor**」 checkboxes —
  keep either one, or **turn both off**; with both off the result only goes to the main window result panes and you copy it manually
  (no floating window at all, nothing covering the game)
- **Persistent translation overlay** (removed in 0.4.0, wired back in): screenshot results **accumulate** in an always-on-top frame —
  one row per unique line, capped by `max_entries` (default 120, scrolls beyond that). Click-through until you press 「☰ Pin」,
  then drag/resize/right-click menu/「Copy all」; press 「✕」 to hide it and use 「Show overlay」 in the main window to bring it back
- **Reply bar in the overlay**: tick 「Show reply bar in overlay」 to type a Chinese reply right there (Enter to translate, last 8 exchanges kept);
  whether the translation is auto-copied is controlled by the 「Auto-copy reply translations」 toggle (on by default)
- Spicy mode toggle (normal ⇄ spicy prompt sets, user-editable)
- Translation cache + multi-line batched requests + `Ctrl+Enter`, repeated text is never billed twice
- **Full error logging**: startup crashes / uncaught exceptions / Qt warnings go to `data\logs\startup.log`;
  the 「日志」 button opens the log folder; `data\logs\exchange.log` records every "input → model output" pair (handy when debugging empty content or mojibake)
- API key encrypted with Windows DPAPI — only your Windows user on this machine can decrypt it
- Dark & light themes, single-instance lock, portable layout

## Game chat code (getting Chinese into in-game chat)

Star Citizen's chat box cannot type Chinese, but the game's **localization syntax `@KEY` expands to that key's value**.
The community's trick is to register 7020 common Chinese characters as localization keys in `global.ini`
(key name = character index in base36); typing `@IH@E8@AP` in chat renders as 「你好吗」. This tool implements that path:

- **Encode**: type Chinese on the left → instantly get `[zh] @IH@E8@AP` → auto-copied → `Ctrl+V` in game
- **Decode**: paste someone's `[zh] @…` on the right → **decode back to Chinese** (the original community tool has no reverse direction)
- Code table source: auto-detected from the **localized `global.ini` already installed on your machine**
  (`…\StarCitizen\LIVE\data\Localization\chinese_(simplified)\global.ini`), or pick it manually via 「浏览…」;
  the status line shows table size and version
- The resolved path is stored in `data\settings.json` (`gamecode_ini_path`), so later launches skip the disk scan (first detection ≈ 0.1 s)

> **Requirement**: a Chinese localization pack that includes "community input method support" must be installed
> (e.g. checked when installing the localization in SC 汉化盒子, or the block is already present in your `global.ini`).
> Without it the feature shows a hint and the rest of the app keeps working.

Implementation notes (`sc_translator/gamecode.py`):

| Rule | Detail |
| --- | --- |
| Code table block | the `code=character` lines in `global.ini` between `_…_community_input_method_version=` and `_…_localization_version=` |
| Code | the character's index in the table, base36 (`0-9A-Z`, min 2 chars): `IH`=665=你, `E8`=512=好, `AP`=385=吗 |
| ASCII / punctuation | passed through verbatim, separated from codes by a space (`Pyro 见 @Bob` → `[zh] Pyro @31 @Bob`) |
| Uncovered characters | dropped to a single space (same as the original implementation) |
| Decode safety | encoding invariants are enforced, so player handles like `@Bob` are never split into bogus codes |

**Output checkboxes** (one pair in the reply pane, one in the game-code card; independent):

| Chinese code | Foreign / translation | Output | Needs API |
| :---: | :---: | --- | --- |
| ☑ | ☐ | `[zh] @IH@E8@AP` (zh→zh: Chinese only) | no (fully local) |
| ☐ | ☑ | `How are you` (zh→foreign) | yes |
| ☑ | ☑ | `[zh] @IH@E8@AP` ↲ `[en] How are you` (both audiences) | yes |

- **At least one** box must stay checked; unchecking the last one re-checks it and tells you
- In the reply pane the "translation" follows the target language (English/Japanese/Korean) and the marker becomes `[en]` / `[ja]` / `[ko]`
- Choices persist in `data\settings.json` (`reply_out_code` / `reply_out_foreign`, `gamecode_out_code` / `gamecode_out_en`)
- Without a code table: "Chinese code only" points you at installing the localization; "code + translation" silently falls back to translation only — never a half-finished message
- On API failure or a missing key it degrades to the Chinese code line, so the message still gets out

## UI language (Simplified / Traditional Chinese / English)

Use the dropdown in the top-right corner: the window is rebuilt immediately, no restart needed, and the
choice is stored as `ui_language` in `data\settings.json`.

- The string table lives in `sc_translator/i18n.py`: **one key per row, three languages as a tuple**, so a
  missing translation is structurally impossible; `tests/test_i18n.py` asserts all three locales are
  complete, that the English strings contain no Chinese, and that Traditional differs from Simplified
- Adding a string is one tuple; a missing/empty entry falls back to Simplified Chinese and then to the key itself
- Switching is refused while a translation is in flight (so callbacks cannot hit destroyed widgets) and the status line says so
- Provider **display names** follow the language, while the **stored value** stays a stable key
  (`DeepSeek`/`OpenAI`/`custom`); settings that stored a legacy display name are migrated automatically

## Screenshot translation (on-demand hotkey, no continuous scanning)

When you hit English UI text, a mission briefing or chat you cannot read, just press a hotkey — the app
captures **exactly one frame** at that moment. There is no polling thread and no timed sampling, so the
idle cost is zero in CPU and in tokens.

| Hotkey (configurable) | Action |
| --- | --- |
| **Shift+F9** | Capture the remembered region → local RapidOCR → translate to Chinese → floating popup + main-window result pane |
| **F10** | Re-select the capture region (also used on first run) |

- **Recognition**: local RapidOCR (PaddleOCR onnx models ship with the app; fully offline, no cost)
- **Translation**: your configured API, sharing the glossary and cache with text translation
  (`Stanton System` → 斯坦顿星系, `Pyro` → 派罗星系)
- **Timing**: the first press loads the model (~1-3 s, then it stays in memory); afterwards each press takes
  roughly **2-6 s** (OCR 1-3 s + translation 1-2 s)
- **Settings** (v0.4.9): the **⚙ Settings** button (top right) opens a dialog holding provider/API key/model,
  the SC glossary, screenshot hotkeys, OCR acceleration and image-reading, where results go, the overlay,
  UI language and log access — the main window keeps only translation and capture controls
- **Faster** (v0.4.9): the OCR detection size is tuned to your framed region (measured **-38%**); pressing the
  hotkey twice on an unchanged frame reuses the previous result (**0.005 s**); `/models` is no longer probed and
  the connection no longer rebuilt on every press (saves **2-4.5 s**); the recognized text appears first and is
  replaced in place when the translation arrives
- **GPU acceleration (DirectML)** (toggle in Settings): OCR measured **0.48 s -> 0.09 s (~5x)** with a flat
  ~200 MB of VRAM that is released when switched off. The packaged build already bundles the runtime; for source
  runs install `pip install --force-reinstall --no-deps onnxruntime-directml`
- **Let the model read the image** (optional, toggle in Settings): sends the framed crop straight to the
  multimodal model (e.g. `deepseek-flash`), which recognizes and translates in one call and uses **no local
  CPU/VRAM**; the trade-off is that **the screenshot is uploaded** and image tokens are billed (official cap:
  1024 per image)
- **Popup**: appears next to the cursor, auto-avoids screen edges, fades after 8 s (configurable/pinnable);
  hovering pauses the countdown; "Copy all" puts "source → translation" on the clipboard
- **Guard rail**: at most 40 lines per capture (configurable) so a mis-dragged full-screen region cannot burn tokens;
  numeric-only, punctuation-only and single-character lines are dropped
- **Graceful failure**: if translation fails (no credit/offline) the recognized source text is still shown
- **Requirement**: run Star Citizen **windowed / borderless**; exclusive fullscreen DX frames may not be capturable

> Size note: OCR needs `onnxruntime + opencv + rapidocr` plus model files, which grows the bundle from
> 120 MB to about **330 MB** (zip ~150 MB). They are **lazy-loaded**: nothing is loaded or kept resident until
> you press the hotkey. See the comments at the top of `SCTranslator.spec` to build a slim variant instead.

## Prompt files (editable)

Prompts are not hard-coded; they live under `prompts\` next to the program (`.md` / `.txt` plain text):

| File | Purpose |
| --- | --- |
| `prompts\translation_normal.md` | normal translation prompt. `{src}`→source language, `{target}`→target language |
| `prompts\translation_spicy.md` | extra prompt appended when spicy mode is on |
| `prompts\reply.md` | reply translation prompt. `{target}`→English/Japanese/Korean |

- **Restart the app** after editing; HTML comments `<!-- … -->` and lines starting with `#` are stripped and never sent
- Missing/broken files fall back to built-in defaults; the `SC_PROMPTS_DIR` environment variable can point elsewhere

## Glossary (proper-noun pre-replacement)

`data\sc_glossary.ini`, one `English=Chinese` pair per line; add or remove freely:

```ini
Stanton=斯坦顿星系
Pyro=派罗星系
Area18=18 区
```

Matching is **case-insensitive with word boundaries**, multi-word entries win; if no path is configured the bundled table is used.
(Set `glossary_enabled` to false in `data\settings.json` to disable it entirely.)

## Run from source

Windows 10/11 x64 + Python 3.10+.

```powershell
# Option A: double-click run.bat (creates the venv and installs deps on first run, 1-3 min)
# Option B: manually
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m sc_translator
```

## Build your own exe

```powershell
# double-click build.bat, or:
.\.venv\Scripts\python.exe -m pip install --upgrade pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean SCTranslator.spec
# output: dist\SCTranslator\SCTranslator.exe (onedir, ~120 MB including Qt)
```

The bundle only contains what text translation needs: PySide6 (Core/Gui/Widgets) + requests.
OCR / local models / imaging (numpy, opencv, onnxruntime, llama-cpp …) are all excluded, which keeps both size and startup time small (cold start ≈ 1 s).
`tests/test_packaging.py` guards that boundary: if a heavy dependency ever enters the import graph, the test fails.

Publishing to GitHub: double-click `publish.bat` (sets origin → pushes `main` → copies the release notes to the clipboard and opens the release page),
then drop `dist\SCTranslator-v0.4.5-win64.zip` into the release attachments.

## Configuration & data

| Path | Purpose |
| --- | --- |
| `data\settings.json` | all settings (provider / model / spicy mode / glossary toggles …) |
| `data\api_key.bin` | DPAPI-encrypted API key |
| `data\cache.json` | translation cache |
| `data\sc_glossary.ini` | glossary (extracted on first run of the portable build) |
| `data\logs\startup.log` | startup/crash log (`run.bat` shows its tail on failure) |
| `data\logs\sc_translator.log` | runtime log |
| `data\logs\exchange.log` | input/output exchange log (time / kind / model / style / input / output or error) |
| `data\logs\doctor.log` | `--doctor` self-check report |

- The data directory defaults to **`data\` next to the program** (portable); `SC_TRANSLATOR_HOME` overrides it
- Legacy `%APPDATA%\SCTranslator` data is migrated automatically on first run
- Single instance only; if a restart within 15 s says "already running", delete `data\instance.lock`

## FAQ

- **Clicking translate does nothing / missing key**: fill in the API key first; `SCTranslator.exe --doctor` pinpoints the problem
- **"model returned empty content (HTTP 200)"**: this is **thinking mode** — DeepSeek models enable thinking **by default**
  (effort defaults to `high`), so the reasoning chain eats the output budget of a short translation request and `content`
  comes back empty at HTTP 200. The app now automatically: ① sends `{"thinking":{"type":"disabled"}}` for `deepseek*`
  models; ② retries once with thinking disabled if content is still empty; ③ raises the per-line output budget floor to
  256; ④ reports `finish_reason` and `reasoning_tokens` in the error when both attempts are empty. Measured on the same
  sentence: 85 output tokens without the flag vs **7** with `disabled`. See `docs\参考-DeepSeek思考模式.md`
- **Nothing appears / it fails to start**: check `data\logs\startup.log` and `sc_translator.log`; from source, run `python -m sc_translator` in a terminal to see the error
- **Translations not good enough**: edit the prompts under `prompts\`, or add terms to `data\sc_glossary.ini`, then restart
- **Spicy mode**: purely a prompt switch; it affects subsequent translations immediately
- **Cost**: identical text hits the cache and is never re-sent; typical text-chat usage costs a few cents per day

## For developers

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pytest
.\.venv\Scripts\python.exe -m pytest tests -q        # 198 passed, 1 skipped
```

```text
main.py / build.bat / SCTranslator.spec   packaging entry point & PyInstaller config
sc_translator/
  __main__.py         entry point (crash logging / single-instance lock / --doctor)
  app.py              app wiring (main window + client + glossary + cache)
  bootstrap.py        extracts prompts\ and glossary on first run
  prompts.py          prompt file loading and fallback
  glossary.py         glossary (proper-noun pre-replacement)
  gamecode.py         game chat code (table parsing / encode / decode)
  textutil.py         small text helpers (CJK ratio)
  paths.py settings.py secrets.py logger_setup.py exchange_log.py
  translate/          cache + OpenAI-compatible client (batching / retry / thinking off)
  ui/                 main window / theme
assets/               app icon + glossary source (for packaging)
prompts/              bundled default prompts
tests/                unit + integration + packaging regression
```

## Disclaimer

A third-party community project, not affiliated with Cloud Imperium Games. It only translates: either text you paste
in, or screen text captured on demand (hotkey) and recognized locally. It does not modify game files and does not
inject into any process. Please comply with the terms of service of the game and of your
translation API provider; use at your own risk. Released under the MIT license.
