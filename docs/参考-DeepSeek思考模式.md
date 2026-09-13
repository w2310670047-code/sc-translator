# DeepSeek 思考模式（官方文档要点摘要）

来源：<https://api-docs.deepseek.com/zh-cn/guides/thinking_mode>
本文件只记录**与本项目实现直接相关**的要点，便于代码对照；完整说明请看官方文档。

## 要点

1. **思考模式默认打开，且 effort 默认为 `high`** —— DeepSeek 模型普遍适用，
   包括 `deepseek-flash`、`deepseek-v4-pro`。翻译这类短请求会先花掉一部分输出预算，
   预算不足时 `content` 为空（**HTTP 200 但没内容**）——这就是“老是 HTTP 200”的原因。
   实测佐证：不带参数时 `deepseek-flash` 报 `reasoning_tokens=78`、`deepseek-v4-pro` 报 `62`。
2. 关闭思考（Chat Completions / OpenAI 格式）：`{"thinking": {"type": "disabled"}}`；
   也可显式 `{"thinking": {"type": "enabled"}}`。等价写法还有 Anthropic 格式
   `{"reasoning": {"effort": "none"}}`（`none` 表示关闭）与 Responses API 格式。
3. 思考强度：`{"reasoning_effort": "low/high/max"}`；映射：`minimal→low`、`low→low`、
   `medium→high`、`high→high`、`xhigh→high`、`max→max`、`ultra→max`。
4. **思考模式下 `temperature`、`presence_penalty`、`frequency_penalty` 会被忽略**（设置不报错但不生效）；
   `top_p` 在思考模式下下限被抬到 0.95，非思考模式恒为 1.0。
5. 思考模式下思维链通过 **`reasoning_content`** 返回，与 `content` 同级；
   未携带 `tools` 参数时无需回传（传了也会被忽略）。
6. 取值非法会 400：`thinking.type` 只接受 `adaptive` / `enabled` / `disabled`；
   `{"thinking": {}}` 缺 `type` 同样 400。
7. 实测（同一句短翻译）：

   | 请求 | 输出 token | reasoning_tokens | 耗时 |
   | --- | --- | --- | --- |
   | 不带 thinking | 85 | 78 | ~2.0s |
   | `thinking=disabled` | **7** | 无 | ~1.6s |
   | `thinking=enabled` | 157 | 150 | ~2.1s |

## 本项目的处理

- 模型名含 `deepseek`（或含 `thinking`）时，请求自动带 `{"thinking": {"type": "disabled"}}`，
  避免空内容、变慢、双倍计费；
- 若某网关不认识该参数（400 且报错文本含 `thinking`），自动去掉参数重试并记住不再发送；
- 若仍收到空内容，自动**再带 disabled 重试一次**；两次都空时，错误信息给出
  `finish_reason` 与 `reasoning_tokens`（例如“思考吃满预算”），而不是笼统一句空内容；
- 单行翻译的输出预算下限提到 256，避免思考把预算吃光后一个字都输出不了。