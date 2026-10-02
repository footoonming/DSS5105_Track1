# ThreadPilot 文档索引

适用版本：API 2.0.0。文档描述系统功能、部署与操作契约。测试批次与结果以验证报告为准。

| 读者 / 任务 | 文档 |
|---|---|
| 项目概览与启动 | [项目 README](../README.md) |
| 日常操作与功能范围 | [用户手册](USER_MANUAL.md) |
| 后端部署与配置 | [后端说明](../backend/README.md) |
| 接口集成 | [API 文档](../backend/API_DOCUMENTATION.md)、[请求示例](request_examples.md)、[OpenAPI](openapi.json) |
| 流式客户端 | [SSE 契约](../backend/STREAMING_API.md)、[前端说明](../frontend/README_ZH.md) |
| 架构与业务规则 | [架构概览](workflow_design.md)、[意图工作流](INTENT_WORKFLOW.md) |
| 导入、同步与迁移 | [数据链路](data_pipeline.md) |
| 字段与验收输入 | [种子数据字典](../data/data_dictionary.md)、[数据库字段](../data/dictionary/schema.yaml)、[列映射](../data/dictionary/field_mapping.yaml)、[对话场景](../data/scenarios/README.md) |
| 质量验收 | [验证报告](live_model_verification.md)、[机器可读证据摘要](reports/live_model_verification.json) |
| 维护与测试 | [贡献指南](../CONTRIBUTING.md)、[浏览器测试](../tests/e2e/README.md) |

## 文档维护规则

功能说明描述可用行为、输入输出和使用限制；开发过程与变更历史不作为操作步骤。接口变更时同步维护 OpenAPI、API 文档及请求示例，字段变更时同步维护模型、迁移和数据字典。

测试报告注明输入、环境、时间、判定口径和未验证范围；重跑结果与首轮结果分别记录。不得将隔离环境验证解释为生产部署验收，或以模拟发送作为外部送达证据。
