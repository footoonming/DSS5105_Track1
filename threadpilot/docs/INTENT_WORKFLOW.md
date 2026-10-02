# 意图工作流设计

系统由 FastAPI、OpenAI SDK、Pydantic v2 和 Web 客户端组成。JSON 聊天入口为 `/chat` 和 `/api/v1/workflow/chat`，Web 客户端使用 `/api/v1/workflow/chat/stream`。意图提取默认使用 Responses API 严格 JSON Schema（`responses.parse` + Pydantic v2）；兼容网关可通过 `INTENT_API_STYLE=chat_completions` 使用 JSON mode，并由 Pydantic 验证结果。模型通过环境变量配置。

`dialogs.xlsx` 是场景和验收输入，G 列是示例而非事实来源。正式三表初始导入 MySQL：120 个订单、360 条工厂级日产量、8 家外协厂。在线工具读取数据库最新提交记录；CSV 用于种子导入与回归测试。默认业务时钟为 `live`，回归时显式设 **2026-04-01 09:00 +08:00**。数据库最新值仍取决于 API/文件同步。详见 [数据链路](data_pipeline.md)。

## 1. Intent Taxonomy

命名为 `<domain>.<verb_or_noun>`，小写 snake_case；一级域是 `order`、`operations`、`execution`。子场景是稳定枚举，细分动作通过 `slots.action` 表达，避免把“确认”和“执行权限”交给模型。

| 场景 | 一级意图 | 子意图 | 支持动作 |
|---|---|---|---|
| 1.1 | order | `order.lookup` | 模糊检索、补充筛选、选定、打开 |
| 1.2 | order | `order.refresh` | 当前阶段、最后记录、今天是否更新 |
| 1.3 | order | `order.risk` | 风险判断、解释、是否已逾期、证据 |
| 1.4 | order | `order.compare` | 并排比较、选择排序维度、推荐优先检查 |
| 1.5 | order | `order.commitment` | 交付点澄清、产能估算、假设、损失日情景、建议 |
| 1.6 | order | `order.prioritize` | 窗口澄清、异常列表、解释实际排名 |
| 2.1 | operations | `operations.normality` | 同 weekday 比较、判断局限、证据 |
| 2.2 | operations | `operations.deviation` | 共现数据、对照、原始记录、下一步检查 |
| 3.1 | execution | `execution.chase` | draft / revise / send；确认单独由服务端处理 |
| 3.2 | execution | `execution.note` | 内部目标确认、预览、保存 |
| 3.3 | execution | `execution.reminder` | 条件、时间、预览、确认、原位更新 |
| 通用 | unknown | `unknown` | 不支持或低置信度时追问 |

## 2. Slots

`Slots` 是受限类型的联合槽位容器；不适用字段为空。相同意图的非空新槽位合并，跨意图清空业务槽位。活动实体、比较对象、草稿独立保存。模型返回的 `order_ids` 必须出现在当轮用户原文，不能通过猜测绕过候选查询；已由服务器解析的上下文 ID 可以续用。

| 子意图 | Required | Optional | Missing 时行为 |
|---|---|---|---|
| lookup | ID，或至少一种检索属性；最终须唯一 | customer/product/quantity/due_date | 无检索条件则问订单或客户；多个候选展示 ID、产品、数量、到期日；零匹配要求纠正 |
| refresh | 唯一 order_id 或 active_order | reference/action | 无活动订单追问；比较后歧义代词必须明确 ID |
| risk | 唯一订单 | action=explain/evidence/recommend | 同上；缺少事件或 blocker 字段明示不可知 |
| compare | 两个不同订单、comparison_fields | criterion=due_date/last_activity_date | 缺对象问两 ID；缺维度问字段；“更危险”缺准则再追问 |
| commitment | product/quantity/due_date/delivery_point | delivery_buffer_days、packing_loss_days | 首先问 factory/customer 交付点，再补产品数量日期；缺运输缓冲用明确标注的 2 个工作日情景假设，不作承诺 |
| prioritize | window_days | customer、order_ids（排名质疑） | “今天需要关注什么”仍追问 today-only / next 7 days；0 明确表示今天；包含逾期活动订单 |
| normality | stage/target_date/baseline | observed_output（用户观察） | 缺时间或基线追问；至少 3 条历史同 weekday 工作日记录；无有效基线则不给正常性结论 |
| deviation | stage/target_date | action | 缺阶段日期追问；无需用户提供因果解释 |
| chase | 唯一订单、recipient；发送时须有该订单草稿 | tone/text/deadline/action | 缺收件人追问；无草稿不能发送；相对 deadline 转带时区时间；发送前展示最终全文 |
| note | 唯一订单、text、目标确认 | action=confirm_target | active_order 目标先确认；预览 exact note 后还须再次“Save it” |
| reminder | 唯一订单、condition、deadline | action=update | 支持 no_reply/no_activity；缺条件或确切时间追问；Friday morning 不猜小时 |

字段约束：quantity > 0，observed_output ≥ 0，window_days 0–365；阶段只接受四个枚举；订单列表最多 10 条。`reference` 为 explicit/active/ambiguous/none，`action` 为 read/draft/revise/send/save/create/update/explain/evidence/recommend/rank/confirm_target。`confidence < 0.65` 或 unknown 不执行业务工具。高置信度意图的缺槽由 Python 判断，不依赖模型的 `needs_clarification` 建议。

时间解析：以业务时钟解析 today/yesterday/tomorrow、当月 25th、ISO 日期，时间支持 ISO 带时区或 noon、a.m./p.m.；无精确小时追问。`tomorrow noon` 在回放时钟 `2026-04-01T09:00:00+08:00` 下是 `2026-04-02T12:00:00+08:00`，随后 `2 p.m.` 保留日期。未知表达不回退为“现在”。

## 3. DialogState

| 字段 | 作用 |
|---|---|
| session_id | 服务器生成的随机 UUID；客户端只传 ID，不上传可信状态 |
| active_order / active_customer | 唯一解析的活动订单和正式客户名称 |
| pending_clarification | 原 intent、已知 slots、最小问题、候选 ID |
| last_intent / slots | 延续“为什么”“改到两点”等短回合 |
| comparison_orders | 比较后保留两个对象并清空 active_order，阻止歧义代词 |
| last_order_ids | 最近结果的实际展示顺序 |
| draft | 订单 ID、收件人、语气、未发送正文，与内部备注隔离 |
| pending_action | 操作 UUID、kind、订单 ID、最终 payload、完整 preview、生成时间 |
| history / revision | 有界历史与轮次；发送模型时只保留近 8 条并截断超长解释 |

每轮在本地进程锁内完成，SQLite 保存状态，重启可恢复。新提问或修订使旧待确认预览失效；有效期 15 分钟。确认前重新读取订单，预览后订单字段改变或提醒截止时间已过时，必须重新预览。已成功操作凭 `confirmation_id` 重试返回历史结果，不重复执行。发送失败或结果不确定时保留同一幂等键。

本地单用户部署；随机会话 ID 是 bearer capability，请勿分享。当前进程锁不是分布式会话锁，应以 **单个 Uvicorn worker** 运行。多用户/多 worker 部署前需接入用户身份与归属校验、分布式锁或数据库版本 CAS，不能直接把本地示例当多租户服务。

## 4. Tools

工具不会通过模型任意执行。`ToolCall` 对每次实际调用返回 name、arguments、result、idempotent、requires_confirmation、executed。

| 工具 | 入参 | 出参 | 幂等性 | 二次确认 |
|---|---|---|---|---|
| search_orders | ID/客户/产品/数量/日期筛选 | 正式候选记录与行引用 | 只读；源变化则结果变化 | 否 |
| refresh_order | order_id | 当前数据库完整记录 | 只读 | 否 |
| assess_order_risk | order_id，业务时钟 | idle_days、days_to_due、overdue、completed_late、原因、局限 | 确定性 | 否 |
| compare_orders | 两 ID、字段 | 并排原始字段 | 只读 | 否 |
| rank_comparison | criterion | 活动订单的透明顺序 | 确定性 | 否 |
| prioritize_orders | window_days/customer | 实际排序、规则、证据 | 确定性 | 否 |
| estimate_capacity | 产品、数量、日期、交付点、缓冲、损失日 | 阶段基线、积压、瓶颈、base/scenario、假设、外协候选、建议 | 确定性 | 否 |
| check_normality | stage/date/baseline/observed_output | 同 weekday 样本、范围、均值、上下界判断 | 确定性 | 否 |
| explain_deviation | stage/date | 当日四阶段记录、历史对照、共现解释和数据缺口 | 只读 | 否 |
| draft_chase | order_id、收件人、文本/语气/回复时限 | 内存/会话内未发送草稿 | 替换该草稿 | 否；仅会话内容 |
| send_chase | 已确认 action_id + 订单 + 收件人 + 最终正文 | sent/unknown/not_sent、真实 receipt | action_id + 网关幂等键 | **是** |
| save_internal_note | 已确认 action_id + order_id + text | saved、私有审计记录 | action_id 唯一 | **是** |
| upsert_reminder | 已确认 action_id + order_id + condition/deadline/since | 创建或原位更新 | session/order/condition 唯一 | **是** |
| evaluate_reminders（后台） | 时钟、刷新后的订单/真实回复记录 | 条件满足则静默，否则站内通知 | reminder/deadline 唯一 | 使用已确认的创建授权 |
| record_reply（集成） | event_id、order_id、带时区 received_at | recorded | event_id 唯一 | 受 REPLY_INGEST_TOKEN 认证的上游事件，不开放聊天伪造 |

规则细节：

- 风险阈值是 7 个日历日无记录或距到期 ≤7 天。当前逾期、已完成迟交、预测风险分别呈现；完成订单不会被列为当前催办异常。
- 每日列表按到期日升序、最后活动日期升序、订单 ID 升序。没有黑盒加权分数，也不把工厂级产量摊到单个订单。
- 正常性采用目标日期之前最近 8 个同 weekday 的工作日；至少 3 条。使用 min/max 描述范围，非统计控制图。用户提供的 800 明确标为未被来源验证；若存在正式同日记录，以正式记录为准并保留用户值供对照。
- 偏差解释展示同日上游和选定阶段记录，并对“低于正常”的前提进行同 weekday 检查。没有 downtime、blocker、staffing 字段就不编造原因。
- 产能模型明确保守：当前阶段及后续阶段都计完整剩余订单量；取过去 20 个工作日均值；每阶段 ceil((backlog + new quantity)/rate)，串行相加；周日不工作；再加运输缓冲与 packing 损失日。这是估算而非排产，不能无条件承诺。外协排除暂停厂，展示类别、批量上限、队列、运输、缺陷批次概率，阶段兼容性仍待确认。
- no_reply 只考虑创建以来、截止前的真实回复事件；no_activity 基于日粒度 last_activity_date，无法判断同一天几点的更新，因此不承诺小时级生产事件判断。提醒写入私有 notifications 表，页面每 30 秒读取，API 也可读取。

每个回答含结构化 `evidence`（source、row、url、record、record_id、version、updated_at、original_source）。`row` 在数据库适配器中是稳定记录 ID；`/api/evidence/orders/{id}` 返回当前记录及来源。回答保留计算时的内容和版本，链接不是不可变历史存档。

## 5. FastAPI 目录

```text
backend/
  app/
    main.py                 # 应用、客户端生命周期、健康检查
    streaming.py            # 工作流 SSE 事件编码
    schemas.py              # Intent/Slots/DialogState/ToolCall/ChatResponse
    intent_classifier.py    # 独立 SYSTEM_PROMPT + OpenAI 结构化识别
    workflow_engine.py      # 路由、状态机、确认门禁、回复
    workflow_tools.py       # 业务算法，在线使用 DatabaseDataTools 适配器
    workflow_store.py       # SQLite、发送适配器、内部备注、提醒、回复事件
    workflow_api.py         # 新 JSON/SSE/证据/通知/回复集成接口
  runtime/                  # 已 gitignore；私有 SQLite 与本地评测报告
  tests/
    fixtures/dialogs.json   # 场景工作簿 A:G 非空单元格转录，带行号
    test_workflow.py        # 11 场景逐轮 + 确认/刷新/提醒边界
  scripts/evaluate_workflow.py # 可选真实模型逐轮评测，发送始终用测试替身
data/                       # 正式业务 CSV 与原 dialogs.xlsx，不改写
docs/openapi.json           # 从运行代码导出的接口契约
```

## 6. 实现与运行

分类器负责意图提取，工作流引擎负责规则与路由，工具及存储模块负责数据访问和状态持久化。回复的数值、状态、证据、限制由 Python 模板产生，避免第二次自由生成覆盖确定性结论。

```powershell
cd D:\GitProjects\DSS5105\threadpilot\backend
uv sync --locked
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

沿用 `backend/.env` 的 OPENAI_API_KEY/OPENAI_MODEL。不读取或提交密钥。前端直接访问 `http://127.0.0.1:8000/#/ai`，Swagger 为 `/docs`。

首轮：

```json
{"message":"Show me the TrendCart order."}
```

续轮传响应 `state.session_id`：

```json
{"message":"The scarf order.","session_id":"<server UUID>"}
```

业务写操作：先提出并阅读完整预览，再发送确认文本和 `confirmation_id`：

```json
{"message":"Send now.","session_id":"<server UUID>","confirmation_id":"<preview UUID>"}
```

同一会话可用明确自然语言 `Send now` / `Save it` / `Confirm` 确认当前唯一待执行预览；推荐客户端携带确认 ID 以避免过时 UI 误确认。单纯“Send it”只生成预览。“Yes, ORD-005”只确认备注目标。

发送适配器：配置 `CHASE_WEBHOOK_URL` 与 `CHASE_WEBHOOK_TOKEN`，服务接收订单、recipient、text、tone 与 `Idempotency-Key`，成功响应必须是 `{"status":"sent","receipt":"provider-message-id"}`。网关负责把 Maya 等联系人映射为真实地址并实施同一 key 的幂等发送。未配置则返回 `not_sent`，不会模拟成功；网络结果不确定则 `unknown`，重试保持原键。

提醒模式：默认使用 `BUSINESS_NOW=live`；历史演示及回归需显式冻结时钟。实际持续监控需持续更新 MySQL / 上游回复事件。离线重启后评估到期的未处理提醒。业务日回放可把 BUSINESS_NOW 改为另一个带时区时间并重启。服务停止时没有后台执行能力，重启后补检。

回复集成：`POST /api/v1/workflow/replies`，头 `Authorization: Bearer <REPLY_INGEST_TOKEN>`，body 包含 event_id/order_id/received_at。没有上游回复接入时“无回复”仅表示本地系统未记录回复，不等于现实中没有回复。站内通知通过 `/api/v1/workflow/notifications/{session_id}` 读取。

SSE 接口在规则验证和必要操作完成后输出 start/delta/done，客户端接收经验证的完整答案。取消浏览器读取不等于撤销已经确认并完成的写操作；客户端可以用原确认键安全重试。所有聊天入口统一使用 `/chat` 或 workflow 路径及其会话、确认契约。

## 7. pytest 与真实模型评测

```powershell
uv run --locked pytest -q
uv run --locked python -m scripts.export_openapi
# 可选：实际调用 API、消耗额度；不会发出业务消息
uv run --locked python -m scripts.verify_live_llm
```

`test_workbook_multiturn_scenario` 在 CSV 与数据库两种适配器下分别参数化生成 11 个 pytest 用例（共 22 个场景用例），从工作簿原始 F 列读 Turn 1–N，逐轮断言 intent、追问、工具和回复约束。合计 45 轮。3.1/3.2/3.3 的确认轮不调用分类模型，由服务器直接校验。离线使用真实 SDK + MockTransport 验证 JSON Schema 协议，模型输出是人工标注意图，**不能用离线通过率代表实际 LLM 准确率**。真实评测使用专用 MySQL 测试库，需配置 LIVE_DATABASE_URL/LIVE_AI_DATABASE_URL；输出保存在 `runtime/live-*/report.json`。`scripts.evaluate_workflow` 用于 CSV 基准评测；MySQL 实时读取验收使用 `scripts.verify_live_llm`。

种子数据的事实边界：TrendCart 仅一个活动 Scarf（ORD-005），因此第 1.1 的 Turn 2 已可唯一识别，应按唯一候选处理；ORD-021 和 ORD-014 已完成，不能把 ORD-014 说成每日异常第一名；生产日志没有活动事件明细或 blocker，相关轮次展示可查询记录并说明数据缺口。

独立边界用例覆盖：多候选不选第一条、磁盘字段刷新、比较代词、变更后旧确认失效、重复确认、重启恢复、提醒原位修改、已有回复时静默、截止前不通知、重复评估不重复提醒、packing 损失日重新计算、未配置发送通道不能报告发送成功。

验收结果集中记录于 [验证报告](live_model_verification.md)，包括离线回归、MySQL 集成、真实模型调用及浏览器测试。真实外部送达和目标部署环境需单独验收。
