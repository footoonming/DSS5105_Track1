[English version](CONTRIBUTING.md)

# 团队协作约定

## 环境

按 [README](README.md) 使用 uv sync --locked；从 backend/.env.example 创建本地 .env。提交 pyproject.toml、uv.lock，不提交 .env、.venv。忽略规则由根目录 .gitignore 定义；已跟踪文件须单独检查，忽略规则不会取消其跟踪。

## 分支与 PR

从主分支创建 feat/功能、fix/问题 或 docs/主题分支。完成后提交 PR，请队友检查再合并。PR 说明问题、修改后的行为、受影响接口与页面、验证结果，以及是否要同步依赖或更新配置。

提交前须在本地执行以下检查。仓库未配置自动化 CI，检查结果应随评审提交。

## 接口修改

1. 更新 backend/app/ 与调用方。
2. 更新 backend/tests/，运行 uv run --locked pytest -q。
3. 更新 backend/API_DOCUMENTATION.md 的字段、SSE 事件和错误语义。
4. 在 backend 运行 uv run --locked python -m scripts.export_openapi，提交 docs/openapi.json。
5. 破坏兼容时在 PR 写明迁移方式，不静默改变 delta/done 或字段类型。

OpenAPI 与 Markdown 随同一个 PR 更新；Apipost 导入后检查实际 Base URL。统一部署前，每位成员运行自己的本地服务。

## 数据与测试

data/*.csv 是种子和回归基准。在线数据通过管理 API、上传或白名单定时同步写入 MySQL。frontend/data.js 是动态加载器，不覆盖、不提交生成快照；scripts.gen_snapshot 与 scripts.build_frontend_data 仅导出被忽略的 data/snapshots/data.snapshot.json。

流式 UI 修改运行 tests/e2e 的 mock 测试。scripts.smoke_stream 与 smoke_live 分别查询当前工作流 SSE 和 JSON 接口，会调用真实 API，手动按需执行。错误报告和截图不包含 Key。

应用维护使用 backend/scripts 中的脚本，数据库结构变更使用 Alembic 迁移。


数据库变更遵循 [数据链路](docs/data_pipeline.md)：修改 ORM/Pydantic 后生成并审核 Alembic 迁移，更新 schema.yaml、OpenAPI 和锁文件。原始数据、runtime、凭据不入 Git。生产代码必须从数据库读取，CSV 适配器只用于回归和导入基准。

真实模型评测按 [验证报告](docs/live_model_verification.md) 配置独立测试库；会消耗实际 API 用量。记录初次失败和限流重跑，不将合并覆盖率写成一次运行通过率，不将测试库通过等同于正式部署完成。
