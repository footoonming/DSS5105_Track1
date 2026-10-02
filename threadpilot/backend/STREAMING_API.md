# SSE 接口说明

Web 客户端使用 **`POST /api/v1/workflow/chat/stream`**。完整字段和联调示例以 [API_DOCUMENTATION.md](API_DOCUMENTATION.md) 为准。

| 项目 | 工作流 SSE |
|---|---|
| 路径 | `/api/v1/workflow/chat/stream` |
| 请求 | message、session_id、confirmation_id、selected_order_id |
| 上下文 | 服务端 SQLite 会话 |
| 返回节奏 | 完成分类、规则与必要操作后，start → 一次完整 answer delta → done |
| 错误 | 已处理的业务前置/模型错误在流开始前返回非 200 JSON |
| done | 完整 ChatResponse，含 intent、state、确认状态、工具轨迹、记录证据 |
| 写操作 | 必须预览、明确确认；取消读取不保证撤销已执行操作 |

该接口在完整答案通过验证后发送事件，不提供模型 token 的实时增量输出；等待分类与规则执行期间可能没有数据，也没有心跳。前端 90 秒无数据会中止读取。

客户端使用 POST fetch 读取 SSE，缓冲到空行后解析事件，不把网络 chunk 当作事件边界。只有 done 才表示完整接收；发送是否成功仍须检查 `tool_calls` 中的业务结果。确认重试应保留同一 session_id 和 confirmation_id，避免重新创建操作。不支持 Last-Event-ID 续传。

[前端实现](../frontend/ai-stream.js) · [请求示例](../docs/examples/workflow-chat-request.json)

[Swagger](http://127.0.0.1:8000/docs) · [在线 OpenAPI](http://127.0.0.1:8000/openapi.json) · [版本化定义](../docs/openapi.json)
