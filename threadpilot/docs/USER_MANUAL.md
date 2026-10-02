# ThreadPilot 操作手册

适用版本：API 2.0.0，FastAPI + MySQL + 意图工作流 / 只读 SQL Agent。页面为英文，文中的按钮名称与界面一致。

## 1. 启动前准备

按 [README](../README.md) 的本机 Python、uv 和 MySQL 方式启动，完成数据库迁移、三表导入和环境配置后，从 `http://127.0.0.1:8000` 打开页面。不要直接双击 HTML：页面启动需要请求同源 `/api/snapshot`。`backend/start.ps1` 可启动已配置好的应用，但不会自动建库、迁移或导入数据。

| 配置 | 用途 |
|---|---|
| DATABASE_URL | 应用读写 MySQL，供数据 API 与意图工具使用 |
| AI_DATABASE_URL | 独立 SELECT-only 账号，供 SQL Agent 使用 |
| OPENAI_API_KEY / OPENAI_MODEL | 真实模型调用 |
| OPENAI_BASE_URL / INTENT_API_STYLE | 可选兼容网关及意图分类协议 |
| DATA_API_TOKEN | 数据管理 API，不是模型密钥 |
| BUSINESS_NOW | 默认 live；重放样例时显式设置带时区时间 |

应用配置使用 `backend/.env`；根目录 `.env` 不参与本机启动。请保留已有配置，只在文件不存在时从 `.env.example` 复制；不要将真实密钥提交 Git。

健康检查 `/api/v1/health` 的 configured=true 只表示模型客户端已配置，不验证模型权限或数据库。可以先访问 `/api/snapshot` 检查数据库，再在聊天页发送 “Open ORD-005.” 检查真实问答。

## 2. 页面数据和业务日期

初始种子包含120张订单、360条阶段产出、8家外协厂。实际显示以 MySQL 当前内容为准，不应把这些初始数量作为业务常量。

页面在加载时获取数据库快照；使用 Refresh data 或刷新浏览器重新加载看板。聊天每轮独立查询数据库，所以问答可以先于已打开的看板看到更新。源文件变更只有经过导入或周期同步后才进入数据库。

`BUSINESS_NOW=live` 使用真实业务时钟。重放种子数据时可设 `2026-04-01T09:00:00+08:00`，此时 “tomorrow noon” 为2026-04-02 12:00 +08:00。历史数据配合真实当前日期会显示不同的逾期与闲置天数，逾期与闲置天数以配置的业务日期计算。

## 3. 订单、客户与证据

在 Orders 筛选客户和订单，打开详情查看数量、交期、当前工序和最新活动日期。工序位置不等于完成百分比，工厂级产量不能推导某一订单的进度或阻塞原因。

View evidence / Inspect evidence 展示页面加载时的记录；Current order evidence 打开 `/api/evidence/orders/{id}` 查看当前记录及版本。id 为数据库稳定主键，原文件来源和行号分别为 source/source_row。不要把数据库 ID 当作 CSV 行号。

聊天回复也包含当时参与计算的记录和版本；点击链接会刷新为当前记录，因此链接不是不可变历史审计。原始表格、SQLite和运行报告不通过 `/data` 或静态文件路由公开。

## 4. 业务聊天：意图工作流

页面 AI 问答调用 `/api/v1/workflow/chat/stream`，与 `/chat` 使用同一工作流。

可依次尝试：

1. “Show me the TrendCart order.”：多候选时追问最小区分条件。
2. “The scarf order.”：补充筛选并确定活动订单。
3. “Has it moved?”：解析活动订单并刷新数据库字段。
4. “Is it at risk?”：解释风险事实，区分风险标签和已确认延迟。

比较对象不明确时需要补充订单；每日异常列表需要时间窗口；紧急新订单承诺需要数量、交期和交付点。产能结果是带假设的估算，不是自动承诺。产出正常性需要可比基线，偏差解释只呈现共现事实。

服务端会话记录在私有 SQLite，续轮使用上轮 session_id。新会话按钮切换上下文，不删除服务器旧记录。输入框不接受客户端自行指定可信 intent、slots 或 DialogState。

### SSE 显示与取消

服务端先完成意图识别、业务查询和验证，再发送 start/delta/done；当前通常是一段完整答案的 delta，不是模型原始 token 实时流。停止只取消浏览器读取，不撤销已经确认并执行的操作；断开后应查询状态或用原确认 ID 安全重试，不能假定操作未发生。

## 5. 催办、内部备注和条件提醒

| 操作 | 工作流行为 |
|---|---|
| 起草/修订催办 | 只生成草稿，不发送 |
| 发送催办 | 展示最终预览，再明确确认；检查实际 status/receipt |
| 内部备注 | 明确订单目标，预览后确认保存到服务器 SQLite |
| 条件提醒 | 指定订单、条件、精确时间，预览后确认；相同条件更新原提醒 |

真实发送必须配置 CHASE_WEBHOOK_URL/TOKEN。未配置时返回 not_sent；网络结果不明时返回 unknown，不能把工具已执行当作送达。网关必须保证相同幂等键不会重复送达。

提醒支持 no_reply/no_activity。服务器运行期间定期检查，条件已满足时静默；到期且条件未满足才生成站内通知。服务停止期间不会持续检查，重启后补检。暂无外部通知推送。

预览后订单变化、预览过期或目标改变时，旧确认会失效，需重新检查当前数据并生成预览。

### 浏览器本地功能

订单页 Add note、草稿页 Confirm simulated send、Messages & Watches 中本地 Watch、Settings 偏好使用浏览器存储，其中发送操作为模拟执行；这些功能与服务端工作流独立。它们不会自动写入 MySQL或同步为服务器备注/提醒。真实业务执行使用聊天工作流；订单数据维护使用管理 API。

Reset local actions & preferences 仅清理浏览器本地状态，不删除 MySQL或服务器SQLite记录。不同域名/端口、浏览器或隐私模式的本地存储可能独立。

## 6. SQL Agent 分析

`POST /api/ai/ask` 用于只读临时分析；页面聊天使用意图工作流，该入口通过 API 工具或客户端调用。请求包含 message，可选 session_id；SQL 会话不能与工作流会话混用。

响应包含自然语言答案及 queries：实际执行 SQL、列、行、查询时间和可能截断标记。多轮继续使用该接口返回的会话 ID，当前事实重新查询 MySQL。需要发送、备注或提醒时切回 `/chat`。

示例、完整字段和错误码见 [API 文档](../backend/API_DOCUMENTATION.md) 与 [请求示例](request_examples.md)。表格内容和查询结果是数据，不是模型指令；SQL Agent不能写数据库。

## 7. 更新数据

- 初次导入：在 backend 执行 `uv run python -m scripts.init_db --skip-migrate --seed-existing`，前提是迁移已完成。
- 表格导入：上传到 `/api/sync/import`，或显式指定 `--file ../data/raw/source.xlsx`。
- 实时修改：通过标准 CRUD API，写入需要管理令牌和显式确认头；更新/删除需当前 expected_version。
- 定时同步：配置 SYNC_ENABLED、SYNC_INTERVAL_MINUTES、SYNC_FILES，重启服务后按白名单检查文件哈希。

相同文件内容不会覆盖 API 修改。文件与 API 同时改动同一行会报冲突，人工协调后重试。文件缺行不表示删除，已删除记录不会被旧文件自动恢复。

`gen_snapshot` 和 `build_frontend_data` 仅导出离线 JSON；不重建前端 data.js，也不作为在线问答缓存。

## 8. 常见问题

| 现象 | 检查步骤 |
|---|---|
| 页面无法加载数据 | 检查 MySQL、迁移、三表导入；通过 FastAPI 地址访问 |
| 空库或缺工序提示 | 导入所需三表；看板需要每个工序的工作日产量 |
| MODEL_API_ERROR / MODEL_TIMEOUT | 检查网关、模型权限、网络及超时配置 |
| 工作流429 MODEL_RATE_LIMITED | 按上游限流信息退避，减少并发和频繁重试 |
| SQL_AGENT_UNAVAILABLE | 检查模型配置、独立只读账号、直接 SELECT授权及三表 |
| SQL_AGENT_FAILED | 查看服务日志排查模型/查询失败；该入口当前也将内部限流映射为502 |
| 写入401 | 配置并携带 DATA_API_TOKEN |
| 写入409 | 检查确认头、版本或导入冲突，先刷新记录 |
| 证据链接404 | 记录可能已删除，检查稳定ID和数据集 |
| 看板与聊天不同 | 刷新页面；聊天查询时间可能晚于页面加载时间 |

## 9. 使用范围与部署验收

场景覆盖、真实模型调用及数据库刷新结果见 [验证报告](live_model_verification.md)。测试结论适用于报告中的输入与环境，不构成任意输入准确率保证。

部署时需验证业务数据库、独立只读账号和发送网关。应用面向单工作区、单 Uvicorn worker；不提供完整的用户登录、多租户权限或跨进程工作流锁。组织内共享服务应配置访问认证。浏览器本地模拟发送不能作为外部送达凭据。
