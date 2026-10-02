# ThreadPilot 前端说明

适用版本：API 2.0.0。前端使用原生 HTML、CSS 和 JavaScript，由 FastAPI 同源托管。启动步骤见 [项目说明](../README.md)，操作说明见 [用户手册](../docs/USER_MANUAL.md)。

## 数据加载与模块职责

`data.js` 请求 `/api/snapshot`，取得 MySQL 数据后依次加载 `app.js`、`data-views.js`、`ai-api.js` 和 `ai-stream.js`。数据库为空或请求失败时显示错误，页面不能通过双击 HTML 独立运行。

| 模块 | 职责 |
|---|---|
| data.js | 加载数据库快照并启动页面 |
| app.js | 页面导航、状态和本地交互 |
| data-views.js | 订单、产出及外协厂数据视图 |
| ai-api.js | 聊天渲染和共用状态交互 |
| ai-stream.js | SSE 请求、停止、重试和会话切换 |

看板使用页面加载时的快照，刷新页面可获取更新。数据维护通过管理 API 或表格导入完成；AI 每轮独立读取数据库。`scripts.gen_snapshot` 和 `scripts.build_frontend_data` 仅导出离线 JSON，不生成或覆盖 `frontend/data.js`。

## 聊天与证据

聊天入口为 `POST /api/v1/workflow/chat/stream`。客户端使用服务端返回的 `session_id` 延续对话，使用 `confirmation_id` 确认操作预览。服务端完成规则验证后发送 SSE，答案不是模型 token 的实时增量。前端显示记录证据链接，并约每 30 秒读取会话的条件提醒通知。

会话 ID 存放于 sessionStorage。“新会话”切换客户端上下文，不删除服务端记录。停止读取不撤销已确认的业务操作；确认重试须使用同一会话及确认 ID。完整契约见 [API 文档](../backend/API_DOCUMENTATION.md)。

## 本地功能与服务端操作

订单页本地备注、Watch、模拟发送和设置偏好使用浏览器存储，不同步为 MySQL 业务数据或 SQLite 工作流记录。模拟发送不产生外部消息。服务端备注、催办和提醒通过聊天工作流执行，且需要预览和显式确认。

开发默认通过 FastAPI 的 8000 端口访问，无需独立静态服务。浏览器测试及覆盖范围见 [端到端测试说明](../tests/e2e/README.md)。
