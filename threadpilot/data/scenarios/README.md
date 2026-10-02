# 对话场景数据

[dialogs.xlsx](../dialogs.xlsx) 定义 11 个子场景、45 轮对话，是工作流验收输入，不导入 MySQL。F 列提供用户输入，G 列提供示例回复；示例回复不能替代业务数据事实。

测试转录见 [dialogs.json](../../backend/tests/fixtures/dialogs.json)，包含工作簿行号。业务事实来自订单、阶段产出和外协厂三表，字段见 [数据字典](../data_dictionary.md)。场景约束与验收规则见 [意图工作流](../../docs/INTENT_WORKFLOW.md)。
