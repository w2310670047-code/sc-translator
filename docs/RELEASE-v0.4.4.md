# v0.4.4 — 修复"老是 HTTP 200（空内容）"：思考模式

用户问"老是 HTTP 200 是什么原因"，用官方文档 + 真实 API 实测定位并修掉。

## 下载

| 文件 | 说明 |
| --- | --- |
| `SCTranslator-v0.4.4-win64.zip` | 解压到任意目录 → 双击 `SCTranslator.exe` |

## 原因：HTTP 200 = 请求成功，但 `content` 是空的

HTTP 200 说明网络与鉴权都没问题，**故障在响应内容里**：DeepSeek 模型的**思考模式默认打开**
（官方文档：「思考模式默认打开，且 effort 默认为 `high`」），模型先把一段思维链写进
`reasoning_content`，普通 chat 请求只读 `content`，于是：

- 短句翻译的输出预算（原实现按 `len(text)*2.5`、下限仅 64）被思维链吃光 →
  `content` 为空、`finish_reason=length` → 我们的客户端判定"空内容"并报错；
- 这也是**偶发**的原因：模型每次思考多长不一样，偶尔还能挤出一句译文。

实测佐证（同一句短翻译，用户自己的 Key）：

| 请求 | 输出 token | reasoning_tokens | 耗时 |
| --- | --- | --- | --- |
| 不带 thinking | 85 | 78 | ~2.0s |
| `thinking=disabled` | **7** | 无 | ~1.6s |
| `thinking=enabled` | 157 | 150 | ~2.1s |

## 修复

| # | 修复 | 说明 |
| --- | --- | --- |
| 1 | **扩大关闭思考的模型范围** | 原实现只对 `deepseek-v4*` 关思考；官方文档说明思考模式对 DeepSeek 模型**默认打开**，因此改为：模型名含 `deepseek`（或含 `thinking`）即自动加 `{"thinking":{"type":"disabled"}}`。用户用的 `deepseek-flash` 正好落在原来的漏网区 |
| 2 | **空内容自动重试** | 若没关思考仍收到空内容（没见过的模型名），自动**改关思考重试一次**；两次都空才报错 |
| 3 | **网关兼容** | 若某个 OpenAI 兼容网关不认识 `thinking` 参数（400 且报错含 thinking），自动去掉参数重试并**记住不再发送**，不误伤第三方服务 |
| 4 | **提高输出预算下限** | 单行 64→**256**，回话 128→256，批量 +256，避免思考把预算吃光后一个字都没有 |
| 5 | **错误信息说人话** | 两次都空时给出 `finish_reason` 与 `reasoning_tokens`，直接说明"模型把输出预算花在思考上了"，而不是笼统一句空内容 |

官方文档要点已整理成 `docs\参考-DeepSeek思考模式.md`（含关闭写法、effort 映射、
思考模式下 `temperature` 被忽略等），便于以后对照。三语 README 的 FAQ 同步更新。

## 实测

```text
客户端判断 needs_thinking_off('deepseek-flash') = True
'Bounty hunting is available nearby.'  -> '附近有悬赏任务可接。'      (1379ms)
'Press F to pay respects, then jump to Pyro.' -> '按F表示敬意，然后跳转到Pyro。' (482ms)
```

（对比修复前：同一句偶发返回空内容并报「HTTP 200 空内容」。）

## 测试

`tests/test_translate.py` 新增/加强 5 项：`deepseek-flash` 与 `deepseek-chat` 都要关思考、
网关前缀模型名（`openrouter/deepseek-*`）也要关、非 DeepSeek 模型不带该参数、
空内容自动关思考重试成功、两次都空时错误信息包含 `reasoning_tokens`、网关 400 后自动去掉参数并记住。
测试总数：**195 passed, 1 skipped**。
