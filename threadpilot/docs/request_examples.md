# API 调用示例

完整字段和响应见 [OpenAPI](openapi.json) 及 [API 文档](../backend/API_DOCUMENTATION.md)，运行时访问 `/docs` 或 `/redoc`。适用 API 版本：2.0.0。

## 接口清单

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /api/data?dataset=orders&offset=0&limit=100 | 分页查询；dataset 支持三表 |
| GET | /api/data/{id}?dataset=orders | 当前记录、版本和来源 |
| POST | /api/data | 创建业务记录 |
| PUT | /api/data/{id} | 完整替换业务字段，要求 expected_version |
| DELETE | /api/data/{id}?dataset=orders&expected_version=1 | 删除并保留墓碑 |
| GET | /api/evidence/{dataset}/{id} | 稳定记录证据链接 |
| POST | /api/sync/import?dataset=orders | multipart 表格上传；多 sheet 不传 dataset |
| GET | /api/sync/logs | 最近一百条同步审计，需管理认证 |
| GET | /api/snapshot | 为前端生成当前数据库快照，Cache-Control: no-store |
| POST | /api/ai/ask | SQL Agent，多轮只读分析，返回实际 SQL/结果证据 |
| POST | /chat | 意图工作流 |
| POST | /api/v1/workflow/chat | /chat 的 JSON 别名 |
| POST | /api/v1/workflow/chat/stream | 同一工作流的 SSE 传输 |
| GET | /api/v1/workflow/notifications/{session_id} | 已确认提醒的通知 |
| POST | /api/v1/workflow/replies | 上游回复接入，原 REPLY_INGEST_TOKEN 认证 |

## 上传

以下 PowerShell 命令中的令牌由调用者设置，不能使用 OpenAI API Key：

```powershell
$base = 'http://127.0.0.1:8000'
$env:DATA_API_TOKEN = '与你的后端配置一致的管理令牌'
curl.exe -X POST "$base/api/sync/import" -H "Authorization: Bearer $env:DATA_API_TOKEN" -H 'X-Confirm-Write: true' -F 'file=@data/raw/source.xlsx'
```

响应包含 `id/source/file_hash/status/inserted/updated/skipped/message/created_at`。内容校验失败 422，API/文件冲突 409，文件超过配置大小 413。XLSX 解压后的总成员大小限制为 100 MB。

## CRUD

GET 不写入。管理写入先检查将提交的 JSON，再显式添加 `X-Confirm-Write: true`；缺少令牌为 401，缺少确认或版本冲突为 409。

```powershell
$headers = @{Authorization="Bearer $env:DATA_API_TOKEN"; 'X-Confirm-Write'='true'}
$rows = Invoke-RestMethod "$base/api/data?dataset=orders&limit=1000"
$record = $rows | Where-Object { $_.data.order_id -eq 'ORD-005' }
$record.data.current_stage = 'ASSEMBLY'
# 检查 $record.data 后再提交；保留其他全部业务字段。
$body = @{dataset='orders'; data=$record.data; expected_version=$record.version} | ConvertTo-Json -Depth 8
$updated = Invoke-RestMethod "$base/api/data/$($record.id)" -Method Put -Headers $headers -ContentType 'application/json' -Body $body
```

创建订单的 body 示例（POST 不需要 expected_version）：

```json
{
  "dataset": "orders",
  "data": {
    "order_id": "ORD-999", "customer": "Example Customer", "product": "Scarf",
    "category": "ACCESSORIES", "pieces": 500, "order_date": "2026-09-18",
    "due_date": "2026-10-01", "status": "IN_PROGRESS", "current_stage": "KNITTING",
    "last_activity_date": "2026-09-18", "completed_date": null, "days_late": null
  }
}
```

PUT 为完整替换，不能更改业务唯一键。DELETE 示例路径：`/api/data/121?dataset=orders&expected_version=1`，使用相同管理头；成功为 204。`id` 是实际 GET/POST 返回的数据库整数，不是 ORD 编号。

## SQL 问答

```powershell
$first = Invoke-RestMethod "$base/api/ai/ask" -Method Post -ContentType 'application/json' -Body '{"message":"How many active orders does TrendCart have?"}'
$first.answer
$first.queries | ConvertTo-Json -Depth 10
$followup = @{session_id=$first.session_id; message='Refresh the count and show their order IDs.'} | ConvertTo-Json
Invoke-RestMethod "$base/api/ai/ask" -Method Post -ContentType 'application/json' -Body $followup
```

响应：`session_id`、`answer`、`business_time`、`queries[]`。每个 query 包含 `sql`、`columns`、`rows`、`possibly_truncated`、`queried_at`。返回的是执行后的限行 SQL。没有可用的只读账号/模型配置返回 503；模型或处理失败 502；未知会话 404。SQL 会话与工作流会话不能互换。

## 意图工作流

```powershell
$chat = Invoke-RestMethod "$base/chat" -Method Post -ContentType 'application/json' -Body '{"message":"Open ORD-005"}'
$body = @{session_id=$chat.state.session_id; message='Has it moved?'} | ConvertTo-Json
Invoke-RestMethod "$base/chat" -Method Post -ContentType 'application/json' -Body $body
```

催办、内部备注和提醒经过预览与显式确认。确认时回传预览返回的 `confirmation_id`；数据在预览后变动会要求重新预览。完整行为与提示词见 [意图工作流](INTENT_WORKFLOW.md)。

## 限流与验证记录

工作流接口将模型限流映射为429 MODEL_RATE_LIMITED，SQL Agent当前统一返回502 SQL_AGENT_FAILED。批量调用应降低频率，按上游信息退避，不连续立即重试。健康检查不验证数据库可用性或模型额度。

测试范围、结果与限流重跑口径见 [验证报告](live_model_verification.md)。
