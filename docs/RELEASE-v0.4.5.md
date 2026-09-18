# v0.4.5 — 术语表按 4.10.1 汉化重制（1239 → 8721 条）

用新版汉化 `4.10.1(PU)_CNRSUI_V1.ini` 与官方英文 `global.ini` 重新配对生成术语表，
并修掉两个让术语表"看起来有、实际没生效"的缺陷。

## 下载

| 文件 | 说明 |
| --- | --- |
| `SCTranslator-v0.4.5-win64.zip` | 解压到任意目录 → 双击 `SCTranslator.exe` |

## 术语表变化

| | 之前 | 现在 |
| --- | --- | --- |
| 条目数 | 1239 | **8721**（新增 7482，译名更新 150，人工译名保护 24） |
| 地名/地点 | — | 1071 |
| 物品/装备 | — | 6217 |
| 载具/飞船 | — | 214 |
| 组织/势力 | — | 114 |

新增 `tools/构建术语表.py`（可复用于以后的汉化更新）：

1. **只从专名命名空间取词**：`item_name*` / `vehicle_*` / `mission_location_*` / `manufacturer_*` /
   `mineabletype_*`（矿物）/ `items_commodities_*` / `stanton*` / `pyro*` / `ui_pregame_port_*` 等；
   `pu_ / dlg_ / ph_ / dxsm_ / ui_` 这些整句对话与按键提示一律排除。
2. **译名清洗**：汉化里大量条目是 `中文（English）` 或 `中文\nEnglish` 形式
   （如 `斯坦顿（Stanton）`、`克莱舍尔劳教设施\nKlescher Rehabilitation Facility`）——
   以前这类"最有用的专名"因为含英文被整条丢弃，现在取出中文部分再用。
3. **专名形状判定**：每个词要么首字母大写，要么是 of/the/on 之类连接词，要么是 F7A/5a/EMP 型编号。
4. **通用词过滤**：单词条目要求整词频 ≤50 或在该专名白名单内，
   并排除 `item_displaytype_*` 这类类型名 —— 挡掉了 `shoes→鞋类`、`helmet→头盔`、`station→站点` 等
   会在聊天里乱替换的通用词（共挡掉 429 条）。
5. **编号丢失保护**：英文带编号而中文里没数字的条目丢弃（如站台号 `L5-B` 被翻没了）。
6. **人工译名保护**：`stanton=斯坦顿星系`、`pyro=派罗星系` 是本项目明确选定的写法，
   新汉化给的是短写法（`斯坦顿`/`派罗`）也不会覆盖；凡"新译名是旧译名前缀"的截短情况一律保留旧值。

## 顺带修掉的两个真 bug

| # | 缺陷 | 影响 | 修复 |
| --- | --- | --- | --- |
| 1 | `glossary.load` 上限 **4000** 且**按文件顺序截断** | 8721 条的术语表只装前 4000 条；新的表按长度排序，于是 **Stanton / Pyro / Port Tressler 这些短专名全被丢掉**，实测一个都替换不上 | 上限提到 20000（并在超限时记日志，不再静默截断） |
| 2 | 8000+ 词条的正则**在加载时同步编译** | 启动多花约 0.9 秒（窗口晚出现） | 改为**首次翻译时惰性编译**：启动 87ms，首次 apply 0.9s，之后每次 2ms |

新增 2 项回归测试守住这两点（大表不被截断、编译惰性）。

## 实测

```text
Heading to Stanton system then jump to Pyro
  -> Heading to 斯坦顿星系 then jump to 派罗星系
selling Laranite and Bexalite at ArcCorp
  -> selling 砬兰石 and 贝沙电气石 at 弧光星
meet me at Port Tressler with a Cutlass Black
  -> meet me at 特雷斯勒空间站 with a 黑弯刀
```

测试总数：**197 passed, 1 skipped**。

## 说明

- 术语表随包分发，首启会释放到 `data\sc_glossary.ini`（已存在则不覆盖）；
  想立刻用上新表，可直接把 `assets\sc_glossary.ini` 覆盖到 `data\sc_glossary.ini`。
- 术语表是纯文本，可自行增删；语法 `英文 = 中文`，`#` 开头为注释。
