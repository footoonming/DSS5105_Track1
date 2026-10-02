# ThreadPilot 本机后端

运行环境：Python 3.12–3.13、uv 和已启动的 MySQL 8.x。所有命令从本目录执行。

1. 执行 `uv sync --locked --group dev`。
2. 仅在 `.env` 不存在时复制 `.env.example`，填写 DATABASE_URL、AI_DATABASE_URL、模型配置和管理令牌。
3. 按 [根 README 第7节](../README.md#7-详细操作步骤) 临时设置 MySQL 初始化变量，执行 `uv run python -m scripts.provision_mysql`。
4. 执行 `uv run python -m scripts.init_db --skip-migrate --seed-existing`。
5. Windows 执行 `./start.ps1 -Reload`；macOS/Linux 执行 `sh start.sh --reload`。

默认地址为 http://127.0.0.1:8000。端口冲突时分别使用 `-Port 8001` 或 `--port 8001`。启动脚本不自动创建配置、建库或导入数据。

本机应用只读取 backend/.env 与进程环境变量，不读取根目录 .env。管理员密码仅用于初始化进程；业务账号负责读写，AI 账号仅获三张业务表 SELECT 权限。

会话、确认、备注和提醒默认存储于 runtime/workflow.sqlite3，可通过 WORKFLOW_DB 调整。数据库不可用时返回明确错误，不回退到 CSV。切换运行环境不会自动复制其他环境的 MySQL 或 SQLite 数据。

验证命令：`uv run pytest -q`；API 契约导出：`uv run python -m scripts.export_openapi`。

参考：[API 文档](API_DOCUMENTATION.md)、[数据链路](../docs/data_pipeline.md)、[验证报告](../docs/live_model_verification.md)。
