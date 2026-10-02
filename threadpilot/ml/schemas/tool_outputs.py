"""
统一的 Tool 输出信封（envelope）。
所有 Tool 最终都返回这个结构，方便后面接 LLM：

{
  "tool": "TOOL_NAME",
  "status": "success" | "not_found" | "error",
  "query": {...},          # 用户/上游传入的参数
  "data": {...},           # LLM 真正可以引用/复述的结构化结果
  "calculation": {...},    # 计算过程 / 公式（可选）
  "evidence": [...],       # 支撑结论的原始数据行（可选）
  "assumptions": [...],    # 预测/估算所依赖的前提（可选）
  "limitations": [...],    # 明确声明"这个 Tool 不能回答什么"（可选）
  "timestamp": "2026-04-01T00:00:00"
}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def make_envelope(
    tool: str,
    status: str = "success",
    query: Optional[dict] = None,
    data: Optional[dict] = None,
    calculation: Optional[dict] = None,
    evidence: Optional[list] = None,
    assumptions: Optional[list] = None,
    limitations: Optional[list] = None,
) -> dict[str, Any]:
    """构造标准输出信封。"""
    return {
        "tool": tool,
        "status": status,
        "query": query or {},
        "data": data or {},
        "calculation": calculation or {},
        "evidence": evidence or [],
        "assumptions": assumptions or [],
        "limitations": limitations or [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def not_found(tool: str, query: dict, message: str, limitations: Optional[list] = None) -> dict:
    """标准"未找到"响应，避免 LLM 编造不存在的订单/客户。"""
    return make_envelope(
        tool=tool,
        status="not_found",
        query=query,
        data={"message": message},
        limitations=limitations or [],
    )


def error(tool: str, query: dict, message: str) -> dict:
    """标准错误响应。"""
    return make_envelope(
        tool=tool,
        status="error",
        query=query,
        data={"message": message},
    )
