"""
生产数据统计辅助函数 + Tool 4: get_order_performance

重要边界（务必读一读）：
    production_log.csv 里没有 order_id，所以这里所有关于 "stage 的统计"
    都是【整体产能/速度统计】，不能归因到某一个具体订单。
    Tool 输出里会显式带上这条 limitation，防止 LLM 把它说成
    "ORD-xxx 在 Assembly 环节的产量"。
"""
from __future__ import annotations

import pandas as pd

from schemas.tool_outputs import make_envelope, not_found
from tools.data_access import load_orders, load_production_log


def get_stage_stats(stage: str, recent_days: int = 7, baseline_days: int = 60) -> dict:
    """计算某个生产阶段的整体产出统计（历史均值/波动/近期均值/趋势）。

    Args:
        stage: 工序名，如 'ASSEMBLY'
        recent_days: "最近"窗口天数，用于计算 recent_avg
        baseline_days: 历史基线窗口天数，用于计算 avg / std
    """
    log = load_production_log()
    stage_log = log[log["stage"] == stage].sort_values("date")

    if stage_log.empty:
        return {
            "stage": stage,
            "baseline_avg": None,
            "baseline_std": None,
            "recent_avg": None,
            "trend": None,
            "sample_days": 0,
        }

    max_date = stage_log["date"].max()
    baseline_window = stage_log[stage_log["date"] > max_date - pd.Timedelta(days=baseline_days)]
    recent_window = stage_log[stage_log["date"] > max_date - pd.Timedelta(days=recent_days)]

    baseline_avg = baseline_window["pieces_completed"].mean()
    baseline_std = baseline_window["pieces_completed"].std()
    recent_avg = recent_window["pieces_completed"].mean()

    # trend：用近期均值相对历史均值的变化比例，简单但可解释
    trend = None
    if baseline_avg and baseline_avg > 0:
        trend = round(float((recent_avg - baseline_avg) / baseline_avg), 4)

    return {
        "stage": stage,
        "baseline_avg": round(float(baseline_avg), 1) if pd.notna(baseline_avg) else None,
        "baseline_std": round(float(baseline_std), 1) if pd.notna(baseline_std) else None,
        "recent_avg": round(float(recent_avg), 1) if pd.notna(recent_avg) else None,
        "trend": trend,
        "sample_days": int(len(baseline_window)),
    }


def get_order_performance(order_id: str) -> dict:
    """Tool 4：分析单个（已完成）订单的历史交付表现。"""
    orders = load_orders()
    match = orders[orders["order_id"] == order_id]

    if match.empty:
        return not_found(
            tool="get_order_performance",
            query={"order_id": order_id},
            message=f"No order found with id '{order_id}'.",
        )

    row = match.iloc[0]

    if row["status"] != "COMPLETE" or pd.isna(row["completed_date"]):
        return make_envelope(
            tool="get_order_performance",
            status="not_found",
            query={"order_id": order_id},
            data={
                "order_id": order_id,
                "status": row["status"],
                "message": "Order is not completed yet, historical performance is not available.",
            },
            limitations=[
                "Performance metrics (lead time, schedule variance) can only be computed "
                "for COMPLETE orders with a completed_date."
            ],
        )

    planned_lead_days = (row["due_date"] - row["order_date"]).days
    actual_lead_days = (row["completed_date"] - row["order_date"]).days
    schedule_variance_days = (row["completed_date"] - row["due_date"]).days
    on_time = schedule_variance_days <= 0
    delay_days = max(0, schedule_variance_days)

    return make_envelope(
        tool="get_order_performance",
        query={"order_id": order_id},
        data={
            "order_id": order_id,
            "planned_lead_days": int(planned_lead_days),
            "actual_lead_days": int(actual_lead_days),
            "schedule_variance_days": int(schedule_variance_days),
            "on_time": bool(on_time),
            "delay_days": int(delay_days),
        },
        calculation={
            "planned_lead_days": "due_date - order_date",
            "actual_lead_days": "completed_date - order_date",
            "schedule_variance_days": "completed_date - due_date",
            "delay_days": "max(0, schedule_variance_days)",
        },
    )


if __name__ == "__main__":
    import json

    orders = load_orders()
    sample_id = orders[orders["status"] == "COMPLETE"].iloc[0]["order_id"]
    print(json.dumps(get_order_performance(sample_id), indent=2, ensure_ascii=False, default=str))
    print(json.dumps(get_stage_stats("ASSEMBLY"), indent=2, ensure_ascii=False, default=str))
