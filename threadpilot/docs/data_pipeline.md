# MySQL 数据链路

## 目录和职责

```text
threadpilot/
├── frontend/                 # 原界面；data.js 请求 /api/snapshot 后加载其余脚本
├── backend/
│   ├── app/
│   │   ├── main.py           # 生命周期、错误映射、工作流与数据 API 路由
│   │   ├── config.py         # pydantic-settings / backend/.env / 环境变量
│   │   ├── schemas.py        # 意图、状态、工具调用和证据契约
│   │   ├── intent_classifier.py
│   │   ├── workflow_engine.py
│   │   ├── workflow_tools.py # 业务算法；CSV 适配器仅用于回归测试
│   │   ├── workflow_store.py # SQLite 会话、确认、备注、提醒与发送审计
│   │   ├── workflow_api.py
│   │   ├── db/              # Base、engine、Session 依赖和初始化
│   │   ├── models/          # 三张业务表、同步日志、删除标记、写锁
│   │   ├── schemas_db/      # 类型化字段校验和 API 返回值
│   │   ├── crud/            # 业务主键、版本、规范序列化和写锁
│   │   ├── services/        # 导入、周期同步、快照、只读 SQL Agent
│   │   └── api/             # data / sync / snapshot / ai
│   ├── scripts/             # init_db、provision_mysql、gen_snapshot、OpenAPI
│   ├── tests/               # 意图测试 + 数据链路与 MySQL 集成测试
│   ├── runtime/             # 私有 SQLite、测试报告；不公开、不入 Git
│   ├── alembic.ini
│   ├── pyproject.toml
│   └── uv.lock
├── data/
│   ├── raw/                 # 原始文件，只读输入，不入 Git
│   ├── staging/             # 可选人工清洗中间文件，不入 Git
│   ├── dictionary/          # schema.yaml、列别名 field_mapping.yaml
│   ├── scenarios/           # dialogs.xlsx 的场景说明
│   ├── snapshots/           # 可选离线导出；不作为在线问答缓存
│   ├── migrations/          # Alembic env.py、模板及不可变版本脚本
│   ├── orders.csv           # 可复现种子和测试输入
│   ├── production_log.csv
│   └── workshops.csv
├── docs/                    # API、工作流、数据链路说明
├── tests/e2e/               # 快照加载 + 原 SSE 界面行为测试
├── Dockerfile
├── docker-compose.yml
└── requirements.txt         # 从 uv.lock 导出
```

`data/*.csv` 提供三表种子和回归基准，`data/dialogs.xlsx` 提供对话验收输入。其他工作簿不会自动扫描或导入。`data/raw` 用于放置待同步原始文件；上传接口读入内存后验证导入，不回写原文件。

## 类型和主键

| 表 | 业务唯一键 | 主要字段 |
|---|---|---|
| orders | order_id | customer、product、category、pieces、order_date、due_date、status、current_stage、last_activity_date、completed_date、days_late |
| production_log | date + stage | pieces_completed |
| workshops | workshop_id | capacity_pieces_per_day、pickup_lead_days、defect_rate、cost_per_piece、makes、status、max_batch_pieces、current_queue_days、notes |

每表还有数据库 `id`、UTC `created_at/updated_at`、`source/source_row`、`version`、`imported_hash`。`days_late` 是有符号整数，负值表示提前完成；`current_queue_days` 是定点小数。金额、缺陷率使用 Decimal，日期使用 DATE。表格日期单元格和 ISO 字符串均可导入。

数据库 ID 不依赖 Excel 行号。回答保存当时的记录及版本，链接 `/api/evidence/{dataset}/{id}` 返回当前记录和来源；链接是可刷新证据，不是不可变历史快照。对已删除记录返回 404，原回答仍保留当时的证据内容。

## 导入和增量同步

1. 只接受 CSV 或 XLSX。多工作表名称必须为 `orders`、`production_log`、`workshops`；单表可用 `dataset` 参数指定。未知字段、未知表、无效日期或枚举拒绝导入。
2. pandas 去除空白、统一空值和日期，Pydantic 校验业务类型；完全相同的业务键重复行去重，冲突重复行拒绝。缺少必填字段不猜测补值。
3. 规范业务字段后计算行 SHA-256；Decimal 尾零不影响哈希。数据库内已存在的行保持 ID。
4. 输入哈希等于上次导入哈希：跳过，保留期间发生的 API 修改。输入等于当前记录：确认其为新的文件基线。
5. 文件已改变且当前数据库仍等于旧文件基线：只更新该行及版本。
6. 文件与 API 同时修改同一行：整次文件导入回滚，返回 409，记录失败审计。人工比较后用 CRUD 协调，再使文件与数据库内容一致，重新导入建立基线。
7. 新记录通过 SQLAlchemy `Session.execute(insert(Model), mappings)` 批量插入。文件缺行不表示删除。显式 DELETE 留下墓碑，旧文件不能恢复；显式 POST 才可重建相同业务键。

所有 API 写入与文件导入共用数据库 `sync_lock` 行锁，防止多进程检查后覆盖。PUT/DELETE 还要求 `expected_version`，防止客户端覆盖别人刚提交的更新。一个文件的所有 sheet 在同一事务里提交；CLI 的多个独立文件分别提交。审计失败事务独立记录，不包含原始内容和数据库凭据。

APScheduler 使用 `SYNC_FILES` 白名单，每 N 分钟比较文件 SHA-256 和最近成功审计。读取前后检查 mtime/size，正在写入时跳过；建议上游写临时文件后原子重命名。失败时不推进最近成功检查点，下轮重试。API 修改无需等待调度，下次查询即可看到提交结果。文件同步延迟上限约为调度周期加处理时间，数据库“最新”不代表上游尚未提交的工厂事件已到达。

文件同步使用定时轮询。单实例默认一名 Uvicorn worker；多副本时只在一台启用调度，数据库写锁仍作为最终保护。数据量扩大后可按业务键分批查询与插入，仓库种子数据共 488 行，每次导入按目标表读入内存比较。

## 两条 AI 路径

`/chat` 执行意图分类、槽位合并、订单澄清、风险与产能规则及二次确认。`DatabaseDataTools` 在每次业务工具调用时查询 MySQL 最新已提交记录。SQLite 保存会话和确认状态；预览后的订单变化会令旧确认失效。

`/api/ai/ask` 用 LangChain `SQLDatabaseToolkit` + `create_agent` 完成临时只读分析。SQL 交给数据库做过滤、连接与聚合，避免把整张表反复塞入上下文和使用历史快照。响应的 `queries` 包含实际执行的 SQL、列、结果、查询时间及可能截断标记。当前实现是同步 JSON 响应。

多轮 SQL 会话使用独立 `sql_sessions` 表，位于同一私有 SQLite 文件；最多保留最近八条用户/助手消息。每轮查询工具都访问 MySQL，历史答案仅供解析上下文。无执行证据时返回无法验证/澄清提示，不输出模型无证据结论。写操作仍使用 `/chat` 的受控工作流。

## 只读的多层保证

- 独立 `AI_DATABASE_URL` 账号只授予三张业务表 SELECT；初始化检查直接授权，拒绝写权限、授权权及角色继承。服务账号与 AI 账号必须不同。
- 标准 `sql_db_query` 工具被移除并替换成受控执行器。list/schema 工具限定三表，不展示样本数据；同步审计和会话表不在查询范围内。
- sqlglot 按 MySQL 方言解析 AST：只允许单条 SELECT，限制表名及函数，拒绝多语句、DML/DDL、系统库、注释、变量、INTO、锁、CTE/UNION，以及 SLEEP/LOAD_FILE 等函数。相对日期使用提示中显式业务时间推导的日期字面值，禁用数据库当前时钟函数，避免回放日期或时区偏移。
- 服务端补充或收紧 LIMIT，设置 MySQL `MAX_EXECUTION_TIME` 并在 `START TRANSACTION READ ONLY` 中执行，随后回滚关闭。
- 提示词明确表格内容是数据，不是指令；模型无法调用管理写入 API。

这是一套保守 SELECT 子集；合法但超出白名单的复杂 SQL 也会拒绝。返回 SQL 便于调试，不能直接用管理账号执行未复核的模型输出。SQL Agent 的语义质量仍依赖模型，业务流程的确定性约束由 `/chat` 保障。

## 扩展字段或新表

修改 `models/data_record.py` 的 ORM 和 `schemas_db/data_record.py` 的 Pydantic 字段。新表同时更新 `crud/data_record.py` 的 MODELS/SCHEMAS/KEYS、Dataset 枚举、字典、SQL 工具白名单与只读账号授权。运行 Alembic 自动生成后人工检查：

```powershell
cd backend
# 使用有 DDL 权限的部署账号临时设置 DATABASE_URL
uv run alembic revision --autogenerate -m "add order owner"
uv run alembic upgrade head
uv run alembic check
uv run python -m scripts.export_openapi
uv run pytest -q
```

迁移文件提交 Git；不要修改已应用的 0001。新增非空字段应先加 nullable 列、回填，再收紧约束。修改业务字段会改变导入哈希，应在迁移中同步重新建立基线或制定人工协调方案。生产服务账号不拥有 DDL 权限，部署迁移单独运行。

## 运维边界

应用提供单工作区服务，读接口未提供用户级权限隔离，会话通过 ID 关联；不提供多租户登录或 RBAC。开发启动默认仅绑定本机地址；团队部署应在反向代理启用组织认证。管理写 API 需 Bearer 令牌和显式确认头。浏览器本地备注、Watch 和模拟发送仅作用于本地存储。业务记录更新使用管理 API，服务端发送、备注和提醒使用工作流接口。

MySQL 数据卷与 SQLite runtime 卷都应备份。重启会保留已提交数据、会话和提醒；原始文件要由数据拥有者保留。前端页面的数据是在页面加载时获取，刷新页面更新看板；AI 每轮独立读取数据库，不受浏览器快照时间影响。`data/snapshots/data.snapshot.json` 只在执行导出脚本时生成，不提交 Git。

参考：[SQLAlchemy Session](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)、[LangChain SQL Agent](https://docs.langchain.com/oss/python/langchain/sql-agent)。SQL Agent 使用 SQLDatabaseToolkit，依赖版本由锁文件管理。langchain-community 的维护状态提示应纳入依赖评审，升级时须重新验证只读工具链。
