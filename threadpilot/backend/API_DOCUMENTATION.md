# ThreadPilot API 文档

本文描述 `backend/app/` 提供的接口，契约见 [OpenAPI 定义](../docs/openapi.json) 为准。应用元数据版本为 `2.0.0`；`/chat` 系列使用意图工作流；`/api/ai/ask` 使用独立的只读 SQL Agent 会话。Web 客户端使用 `POST /api/v1/workflow/chat/stream`。

## 1. 启动与接口总览

先按 [项目 README](../README.md) 配置 MySQL、执行 Alembic 迁移并导入数据，再在 `backend` 目录执行：

```powershell
uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Base URL：`http://127.0.0.1:8000`。配置详情见 [后端 README](README.md)。

[Swagger](http://127.0.0.1:8000/docs) · [ReDoc](http://127.0.0.1:8000/redoc) · [在线 OpenAPI](http://127.0.0.1:8000/openapi.json) · [AI 页面](http://127.0.0.1:8000/#/ai)

| 方法 | 路径 | 功能 / 成功类型 |
|---|---|---|
| GET | `/api/v1/health` | 配置状态；JSON |
| POST | `/chat` | 意图工作流 JSON，等价于下一行 |
| POST | `/api/v1/workflow/chat` | 意图工作流 JSON |
| POST | `/api/v1/workflow/chat/stream` | 验证完成后的工作流 SSE |
| GET | `/api/v1/evidence/{source}/{row}` | 按结果序号读取数据库证据；推荐使用稳定 ID 入口 |
| GET | `/api/v1/workflow/notifications/{session_id}` | 已生成的站内通知数组；JSON |
| POST | `/api/v1/workflow/replies` | 受认证的回复事件接入；JSON |

数据管理与 SQL 问答接口见第 11 节。除表格上传使用 `multipart/form-data` 外，POST/PUT 请求使用 `Content-Type: application/json`；SSE 可增加 `Accept: text/event-stream`。浏览器不传 OpenAI Key、model、intent、slots、state 或 stream 参数。应用没有登录系统；工作流会话 ID 应作为本地访问凭证保管。数据管理写操作和同步日志使用 DATA_API_TOKEN；回复事件使用独立的 REPLY_INGEST_TOKEN。

CORS 允许 localhost / 127.0.0.1 的 8000、8765 端口，允许 GET/POST/PUT/DELETE，以及 Content-Type、Authorization、X-Confirm-Write 请求头。

## 2. 健康检查

```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
```

HTTP 200 示例：

```json
{"status":"ok","configured":true,"model":"gpt-4.1","streaming":true}
```

不调用模型。`configured` 仅表示已创建客户端，不验证凭证、余额、模型权限、数据完整性、发送网关或提醒是否可触发。

## 3. 意图工作流：请求与会话

`POST /chat`、`POST /api/v1/workflow/chat`、`POST /api/v1/workflow/chat/stream` 共用请求体。

首轮示例（[可下载 JSON](../docs/examples/workflow-chat-request.json)）：

```json
{
  "message": "Show me the TrendCart order."
}
```

续轮示例；必须替换成**目标服务器上一轮返回的** ID：

```json
{
  "message": "The scarf order.",
  "session_id": "00000000-0000-4000-8000-000000000001"
}
```

| 字段 | 必填 | 约束和语义 |
|---|---|---|
| message | 是 | 字符串，1–1500 字符；全空白返回 EMPTY_MESSAGE |
| session_id | 否 | 默认 null，省略则创建新会话；传服务器返回的 UUID。当前校验格式为 36 位小写十六进制/连字符，之后还会查询会话是否存在 |
| confirmation_id | 否 | 默认 null；确认已预览业务操作时回传响应中的确认 ID |
| selected_order_id | 否 | 默认 null；格式 ORD-三位数字。只在没有 active_order 且不处于比较上下文时用于初始化选择；更换已活动订单请在 message 中明确指定新 ID |

额外字段返回 422。请求不接受 `history` 或 `context`；上下文由服务端管理。

服务端持久化 `DialogState`，客户端不上传历史或可信状态。首轮追问也会创建会话；继续澄清时须保留 `session_id`。未知 ID 返回 404 UNKNOWN_SESSION。开启新会话时省略 ID；前端“新会话”不会删除旧数据库记录。

同一会话应按顺序等待响应后再发送下一轮，避免客户端并发导致业务顺序不确定。当前部署使用单进程锁，应保持单个 Uvicorn worker。

## 4. 工作流响应

JSON 接口 HTTP 200 的 body 与新 SSE 的 `done.data` 使用同一个 `ChatResponse` 契约。HTTP 200 可以表示正常回答、澄清、待确认，或“未发送/结果未知”，并不表示业务写操作成功。

| 字段 | 类型 | 含义 |
|---|---|---|
| answer | string | 用户可读英文回复，含业务时间、约束和证据引用；按纯文本/安全转义显示，勿当可信 HTML |
| intent | string enum | 识别或延续的业务意图，见下表 |
| slots | object | 本轮合并后的服务器槽位；不适用字段为空 |
| confidence | number | 分类置信度；低于 0.65 追问；确认处理轮为 1，不代表业务预测概率 |
| needs_clarification | boolean | 是否需要补充信息 |
| clarification_question | string / null | 最小澄清问题 |
| confirmation_required | boolean | 是否存在待确认业务操作 |
| confirmation_id | string / null | 当前预览的操作 ID；修改预览后必须更新 |
| state | DialogState | 会话快照；取 state.session_id 续聊，不把整个对象传回 |
| tool_calls | ToolCall[] | 实际执行、尝试或被配置阻止的工具轨迹 |
| evidence | Evidence[] | 参与回答/计算的原始记录及对应链接 |
| order_ids | string[] | 当前结果列表，最多 10 个；可为空，不能假定第一条就是用户选择 |
| selected_order_id | string / null | 当前 active_order；双订单比较时可能为 null |
| sources | string[] | 从 evidence 派生的数据库表名；original_source 记录文件来源或 api |
| request_id | string | 请求标识，对应 X-Request-ID |
| model | string | 当前配置的模型名，不保证为上游版本快照名 |
| business_date | string | 工作流时钟对应 YYYY-MM-DD；由 BUSINESS_NOW 决定 |
| usage | object / null | 当前意图工作流未汇总 token 用量，返回 null |

### 意图枚举与槽位

| 场景 | intent | 主要槽位 |
|---|---|---|
| 1.1 | order.lookup | order_ids/customer/product/quantity/due_date |
| 1.2 | order.refresh | 唯一订单或 active_order、reference |
| 1.3 | order.risk | 唯一订单、action |
| 1.4 | order.compare | 两订单、comparison_fields、criterion |
| 1.5 | order.commitment | product/quantity/due_date/delivery_point、delivery_buffer_days、packing_loss_days |
| 1.6 | order.prioritize | window_days、customer、order_ids |
| 2.1 | operations.normality | stage/target_date/baseline、observed_output |
| 2.2 | operations.deviation | stage/target_date、action |
| 3.1 | execution.chase | recipient/tone/text/deadline/action |
| 3.2 | execution.note | text/action、唯一订单 |
| 3.3 | execution.reminder | condition/deadline/action、唯一订单 |
| 通用 | unknown | 不支持或不确定的请求，需要澄清 |

槽位由模型提取、服务器验证，客户端不能直接提交。完整类型、必填规则和缺槽行为见 [意图与槽位设计](../docs/INTENT_WORKFLOW.md) 及 OpenAPI 中的 `Slots`。例如 `window_days=0` 明确表示今天；未给出窗口不自动视为 0。`condition` 只支持 `no_reply` / `no_activity`。

### DialogState

| 字段 | 用途 |
|---|---|
| session_id | 服务端会话标识 |
| active_order / active_customer | 唯一解析的活动订单及客户 |
| pending_clarification | intent、question、已知 slots、候选订单列表 |
| last_intent / slots | 后续短语和澄清的业务上下文 |
| comparison_orders | 两个比较对象；此时歧义代词需要明确 |
| last_order_ids | 最近结果的完整内部顺序 |
| draft | 未发送草稿的订单、收件人、语气和文本 |
| pending_action | id、kind、order_id、payload、preview、created_at、source_snapshot |
| history / revision | 有界历史和轮次版本 |

### ToolCall 与 Evidence

`ToolCall` 包含 `name`、`arguments`、`result`、`idempotent`、`requires_confirmation`、`executed`。其中 `executed=true` 表示工具已运行/尝试，**不代表外发成功**；发送须检查 `send_chase.result.status` 和回执。

`Evidence` 包含：

```json
{
  "source": "orders",
  "row": 104,
  "record_id": 104,
  "version": 1,
  "updated_at": "2026-09-18T12:00:00Z",
  "original_source": "orders.csv",
  "url": "/api/evidence/orders/104",
  "record": {
    "order_id": "ORD-005",
    "customer": "TrendCart",
    "product": "Scarf",
    "category": "ACCESSORIES",
    "pieces": "500",
    "order_date": "2026-03-21",
    "due_date": "2026-04-20",
    "status": "IN_PROGRESS",
    "current_stage": "KNITTING",
    "last_activity_date": "2026-03-24",
    "completed_date": "",
    "days_late": ""
  }
}
```

这是响应结构示例，ID、时间与版本必须以实际响应为准。record 为数据库业务字段的字符串表示；row 在数据库适配器中等于稳定 record_id，不是 Excel 行号。原文件行号可在证据端点的 source_row 中查看。回答保存当时的字段和版本，链接读取当前记录。

## 5. 确认与业务操作结果

写操作顺序是“提出请求 → 展示完整预览 → 明确确认 → 执行并记录结果”。模型分类本身不产生执行权限。

| 操作 | 预览阶段 | 确认方式 |
|---|---|---|
| 催办发送 | 先起草/修订；“Send it”展示订单、收件人和最终正文 | “Send now”并回传 confirmation_id |
| 内部备注 | 先确认活动订单目标，再预览内部备注正文 | “Save it”并回传 confirmation_id |
| 创建/修改提醒 | 显示订单、条件及带时区的明确时间；修改仍需确认 | “Confirm”并回传新 confirmation_id |

确认请求示例，两个 ID 都必须取自自己的会话：

```json
{
  "message": "Send now.",
  "session_id": "00000000-0000-4000-8000-000000000001",
  "confirmation_id": "00000000-0000-4000-8000-000000000002"
}
```

[确认 JSON 模板](../docs/examples/workflow-confirm-request.json) 不能直接使用占位 ID 执行。服务端也接受不带确认 ID、但明确确认当前唯一预览的文本；客户端应始终携带 ID，防止旧界面确认新内容。

- 新的非确认提问或修订撤销旧预览；每次新预览生成不同 ID。
- 预览有效期为业务时钟的 15 分钟。显式配置回放时钟时，业务时间不会自然推进。
- 确认前再次读取订单；订单记录改变、提醒时间已过或预览过期时，要求重新预览。
- 目标确认“yes, ORD-005”不等于保存备注。内部备注不会自动发送给外部联系人。
- 已成功操作再次使用同一确认 ID，返回已有记录，不重复操作。普通聊天请求没有请求级幂等键；不要对所有 POST 无条件自动重试。

### 发送状态

| send_chase.result.status | 含义 | 客户端处理 |
|---|---|---|
| sent | 已获得发送网关的成功 receipt，审计已记录 | 可以展示已发送 |
| not_sent | 未配置发送连接器，草稿仍未发送；该 ToolCall.executed=false | 展示配置缺口，不当作成功 |
| unknown | 请求已尝试，但送达没有确认 | 保留同一 confirmation_id 重试，不伪造成功回执 |

`save_internal_note` 和 `upsert_reminder` 成功时 result.status 为 `saved`。提醒以 session/order/condition 唯一定位并原位更新，不因更改时间创建重复记录。

### 发送网关契约

网关 URL 与凭证只从服务端环境配置读取。确认发送后，后端向该 URL POST：

```json
{
  "order_id": "ORD-005",
  "recipient": "Maya",
  "text": "Please provide an updated status for ORD-005.",
  "tone": "firm but polite"
}
```

Header：`Authorization: Bearer <CHASE_WEBHOOK_TOKEN>`、`Idempotency-Key: <action UUID>`。网关必须支持同键去重，并负责将收件人名称映射成实际地址。只有成功 HTTP 响应且正文为 `{"status":"sent","receipt":"provider-message-id"}` 才视为发送成功；没有配置时不会用模拟回执代替真实发送。

## 6. 意图工作流 SSE

`POST /api/v1/workflow/chat/stream` 会先完成意图识别、规则检查及本轮必要操作，再返回 HTTP 200 SSE。它使用流式传输协议，但**当前不是边调用模型边显示 token**。在规则完成前可能没有任何流数据。

响应头包括 `Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no` 和 `X-Request-ID`。

| event | data | 当前行为 |
|---|---|---|
| start | request_id、model | 标识本轮响应 |
| delta | text | 当前发送一次完整、已验证的 answer |
| done | 完整 ChatResponse | 保存正式回答、更新 session_id/confirmation_id、显示证据 |

正常顺序：**start → delta → done**。以 `done` 判断响应是否接收完整；以响应业务字段判断是否需要澄清、确认或是否已经发送。

接口的已处理模型/数据错误在进入 SSE 前返回非 200 JSON，当前不会生成 `error` 事件。传输中断仍可能导致没有 done。客户端用 POST fetch + ReadableStream + TextDecoder，按空行分隔事件；网络 chunk 不等于一个 SSE 事件。实现见 [ai-stream.js](../frontend/ai-stream.js)。

浏览器 90 秒没有数据会中止读取；此时服务器操作可能已经完成。**AbortController 只取消客户端读取，不保证撤销已确认的写操作。** 对确认操作重试时保留同一会话和 confirmation_id；没有拿到 done 不等于没有发送。接口没有心跳、Last-Event-ID 或断点续传。

## 7. 证据、通知与回复事件

### 原始证据

`GET /api/v1/evidence/{source}/{row}` 返回第 4 节的完整 Evidence。

- source 白名单：`orders.csv`、`production_log.csv`、`workshops.csv`。
- row 为整数，首条记录是 2；越界、不支持的来源或无法读取的来源返回 404 UNKNOWN_SOURCE_ROW。
- 此入口按当前数据库结果顺序定位，不读取 CSV；删除或插入可能改变位置。客户端应使用 `/api/evidence/{dataset}/{record_id}` 的稳定 ID 链接。回答的 evidence.record 保留当次计算值，链接不提供不可变历史版本。
- 不需要 OpenAI Key，不调用模型。

### 条件提醒通知

`GET /api/v1/workflow/notifications/{session_id}` 返回已有通知数组。没有通知时为 `[]`，不是错误。未知会话返回 404 UNKNOWN_SESSION。

每条对象包含 `id`、`session_id`、`order_id`、`message`、`created_at`。此接口只是读取，不触发即时检查，也不清除通知；客户端按 id 去重，当前没有已读/删除接口。

后端按约 30 秒间隔检查已确认提醒（繁忙时可延后）。`no_reply` 检查创建以来到截止时间之间的记录回复；`no_activity` 使用日期粒度的 last_activity_date，不能证明同日精确到小时的更新。条件满足则静默，未满足时生成一次站内通知。同一提醒截止时间重复评估不会重复生成通知。

默认 `BUSINESS_NOW=live`；只有显式指定回放时间时业务时钟才冻结。实际监控需保持服务和数据接入运行。更改时钟不等于已接工厂实时数据。服务停止期间不检查，重启后补检到期提醒。

### 回复事件接入

`POST /api/v1/workflow/replies` 供可信上游接入真实回复；不是聊天“确认保存”接口。必须设置服务端 `REPLY_INGEST_TOKEN`，并发送：

```text
Authorization: Bearer <REPLY_INGEST_TOKEN>
Content-Type: application/json
```

[请求示例](../docs/examples/reply-event-request.json)：

```json
{
  "event_id": "provider-reply-001",
  "order_id": "ORD-005",
  "received_at": "2026-04-01T08:30:00+08:00"
}
```

| 字段 | 约束 |
|---|---|
| event_id | 1–100 字符；上游稳定事件 ID，同 ID 重试不重复写入 |
| order_id | ORD-三位数字且存在于正式订单数据 |
| received_at | 带时区的日期时间，不得晚于业务时钟 |

成功返回 `{"status":"recorded"}`。未配置或错误 token 返回 401 UNAUTHORIZED；未知订单/未来事件返回 422 INVALID_REPLY；字段不合法由 Pydantic 返回 422。当前 ReplyEvent 使用 BaseModel 默认行为，额外字段忽略，不同于拒绝额外字段的聊天模型。

缺少上游接入时，“无回复”只表示本地未记录回复，不能推断现实中没有回复。

## 8. 错误处理

应用主动处理的 HTTP 错误使用：

```json
{
  "error": {
    "code": "UNKNOWN_SESSION",
    "message": "Start a new conversation.",
    "request_id": "request-identifier"
  }
}
```

FastAPI 字段校验错误使用 `{"detail":[...]}`，客户端需兼容两种结构。下表列出已实现的主要错误映射，不是对所有运行时故障的穷举。

| HTTP | code | 适用场景 |
|---|---|---|
| 503 | API_KEY_NOT_CONFIGURED | 聊天未配置模型客户端 |
| 503 | DATA_UNAVAILABLE | 聊天来源读取失败 |
| 404 | UNKNOWN_SESSION | 意图工作流/通知使用不存在的会话 |
| 404 | UNKNOWN_SOURCE_ROW | 证据来源或行不可用 |
| 422 | EMPTY_MESSAGE | 意图工作流全空白消息 |
| 422 | INVALID_WORKFLOW_INPUT | 意图工作流未知记录、非法日期或无效结构化输出 |
| 429 | MODEL_RATE_LIMITED | 聊天上游限流或额度问题 |
| 504 | MODEL_TIMEOUT | 聊天模型超时 |
| 502 | MODEL_API_ERROR | 意图工作流连接或上游请求错误 |
| 401 | UNAUTHORIZED | 回复接入认证未通过 |
| 422 | INVALID_REPLY | 回复订单不存在或时间在业务时钟之后 |
| 422 | detail 数组 | 请求字段类型、长度、格式或额外字段不符合对应模型 |

意图工作流的业务澄清、无效/过期确认、未配置外发、送达未知通常为 **HTTP 200 的 ChatResponse**，按 needs_clarification、confirmation_required、tool_calls.result 判断，不按 HTTP 状态推断成功。

## 9. curl / PowerShell / Apipost

在项目根目录执行，先启动后端。聊天调用真实模型并消耗额度：

```powershell
# 意图工作流 JSON
curl.exe -X POST "http://127.0.0.1:8000/chat" -H "Content-Type: application/json" --data-binary "@docs/examples/workflow-chat-request.json"

# 意图工作流 SSE：验证完成后返回事件
curl.exe -N -X POST "http://127.0.0.1:8000/api/v1/workflow/chat/stream" -H "Content-Type: application/json" -H "Accept: text/event-stream" --data-binary "@docs/examples/workflow-chat-request.json"

```

可直接续聊的 PowerShell 示例：

```powershell
$apiBase = 'http://127.0.0.1:8000'
$first = Invoke-RestMethod -Method Post -Uri "$apiBase/chat" -ContentType 'application/json' -Body (@{ message = 'Show me the TrendCart order.' } | ConvertTo-Json)
$first.answer
$followup = @{ message = 'The scarf order.'; session_id = $first.state.session_id } | ConvertTo-Json
$second = Invoke-RestMethod -Method Post -Uri "$apiBase/chat" -ContentType 'application/json' -Body $followup
$second.answer
```

Apipost 导入 [OpenAPI 文件](../docs/openapi.json) 或在线 /openapi.json，核对 Base URL 和具体请求体。SSE 路由在 OpenAPI 中声明 text/event-stream；事件顺序以本文为准，done 的完整负载对应 JSON 路由的 ChatResponse 模型。

404 时检查主机、端口、方法和路径；`#/ai` 是网页路由，不是 API 地址。响应为 HTML 通常表示命中了静态资源路径或其他服务。接口工具缓冲整个响应时，用网页或 curl -N 检查事件；接口在业务验证完成后返回事件。

## 10. 数据、部署与维护

初始三表由仓库种子数据导入；在线业务工具读取 MySQL。API 提交后下一次查询可见，文件变动需经过上传或定时同步，最新数据库值仍取决于上游更新。生产日志为工厂级，不能推导单个订单的进度百分比或活动详情。异常优先级采用公开字段顺序；产能是带假设的情景估算。算法、完整工具清单及场景差异见 [Intent Workflow](../docs/INTENT_WORKFLOW.md)。

工作流会话、备注、操作审计、提醒、回复和通知保存在私有 SQLite；不向客户端暴露数据库文件。尚无会话用户归属鉴权、删除会话 API、多 worker 锁或外部通知推送。发送网关负责实际地址解析与幂等送达。原驾驶舱浏览器内的模拟动作不自动同步为这些服务端操作。

FastAPI 托管前端 /，不公开 /data、backend、runtime 或 docs；仓库里的文档/示例链接不代表同名在线 API。

在 backend 执行：

```powershell
uv run --locked pytest -q
uv run --locked python -m scripts.export_openapi
# 可选：先配置 LIVE_DATABASE_URL/LIVE_AI_DATABASE_URL 指向专用 threadpilot_test；会产生真实模型用量
uv run --locked python -m scripts.verify_live_llm
```

接口改动同步更新实现、回归、本文、docs/openapi.json 及调用方。离线 pytest 不消耗模型额度；真实评测会消耗额度。浏览器测试见 [tests/e2e](../tests/e2e/README.md)。



## 11. MySQL、同步和 SQL Agent 接口

| 方法 | 路径 | 认证/语义 |
|---|---|---|
| GET | `/api/data` | dataset 默认 orders；offset≥0，limit 默认100、最大1000 |
| GET | `/api/data/{record_id}` | dataset 参数选择表，返回当前版本 |
| POST | `/api/data` | 管理 Bearer + X-Confirm-Write: true；成功201 |
| PUT | `/api/data/{record_id}` | 同上，完整业务字段 + expected_version |
| DELETE | `/api/data/{record_id}` | 同上，dataset + expected_version；成功204 |
| GET | `/api/evidence/{dataset}/{record_id}` | 当前记录、来源、版本和时间 |
| POST | `/api/sync/import` | 管理 Bearer + 确认头；multipart file，可选 dataset |
| GET | `/api/sync/logs` | 仅管理 Bearer，最近100条审计，无需确认头 |
| GET | `/api/snapshot` | 当前三表快照，Cache-Control: no-store |
| POST | `/api/ai/ask` | 只读 SQL 问答，独立 session_id |

`dataset` 仅允许 `orders`、`production_log`、`workshops`。创建/更新 body 为 `{"dataset":"orders","data":{...},"expected_version":1}`，POST 可省略版本。字段定义见 [schema.yaml](../data/dictionary/schema.yaml)。业务唯一键不可通过 PUT 改写；DELETE 留下墓碑，旧文件不会重新插入，显式 POST 可以重建。

`RecordRead` 返回 id、dataset、data、version、source、source_row、created_at、updated_at。证据端点还返回同内容的 record，供工作流客户端使用。数据库时间列按 UTC 保存。

表格多 sheet 名称必须对应三张业务表；单 sheet 可用 dataset 指定。一个文件整体事务提交，重复业务键且内容相同则去重，冲突重复行或非法字段拒绝。输入未变时保留 API 修改；文件与 API 同时改动同一行返回409，不全量覆盖。上传不会覆盖服务器原文件。

SQL 问答请求：

```json
{"message":"Show order_id and pieces for ORD-005.","session_id":null}
```

message 为1–3000字符，续轮携带此接口返回的 UUID。响应包含 `session_id`、`answer`、`business_time` 和 `queries[]`；每条查询包含 `sql`、`columns`、`rows`、`possibly_truncated`、`queried_at`。SQL 是实际执行的限行版本；无当前查询证据时返回无法验证/澄清提示。响应为普通 JSON，不提供此入口的 SSE。

SQL Agent 使用独立 SELECT-only MySQL 账号，并检查 SQL AST、表/函数白名单、LIMIT 和执行超时。它不能发送、保存备注或创建提醒；这些操作继续走 `/chat`。SQL 会话与工作流会话不可互换。

| 状态 | 接口错误 | 处理 |
|---|---|---|
| 401 | UNAUTHORIZED | 配置并携带 DATA_API_TOKEN |
| 409 | CONFIRMATION_REQUIRED | 核对写入后添加 X-Confirm-Write: true |
| 409 | VERSION_CONFLICT / DATA_CONFLICT / IMPORT_CONFLICT | 刷新版本，或人工协调文件与数据库 |
| 413 | FILE_TOO_LARGE | 缩小上传文件或调整 MAX_UPLOAD_BYTES |
| 422 | INVALID_DATA / IMMUTABLE_KEY / 参数校验错误 | 按数据字典更正请求 |
| 503 | DATABASE_UNAVAILABLE | 检查连接与迁移 |
| 503 | SQL_AGENT_UNAVAILABLE | 检查模型和独立只读连接/权限 |
| 502 | SQL_AGENT_FAILED | 上游模型或查询处理失败；包括此入口内部的限流错误 |

工作流接口的模型限流返回429 MODEL_RATE_LIMITED；SQL Agent 当前统一映射为502，不应把两者错误码混同。参数校验错误使用 FastAPI 的 detail 格式；业务错误通常使用 error.code/message。客户端应同时处理这两种结构。

可复制的 PowerShell 请求见 [调用示例](../docs/request_examples.md)。真实模型测试结果、失败分类及验证范围见 [验证报告](../docs/live_model_verification.md)。
