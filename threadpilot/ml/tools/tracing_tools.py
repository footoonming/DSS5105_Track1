"""
Tool 9: trace_order_evidence

Track 1 的核心要求："Every number must expand into the rows behind it."
这个 Tool 不产生新结论，只负责把某个订单相关的【原始数据行】摊开给人看，
用来验证前面其它 Tool（get_order_status / predict_order_delay /
get_at_risk_orders 等）说的话有没有依据。

关键边界：production_log 没有 order_id，所以这里返回的生产记录
只是"同期/同工序的工厂整体生产记录"，不能被当成该订单自己的产量证据。
输出里会显式加一条 limitation，防止 LLM 把两者混为一谈。
"""
from __future__ import annotations

import pandas as pd

from schemas.tool_outputs import make_envelope, not_found
from tools.data_access import load_orders, load_production_log, load_workshops


def trace_order_evidence(order_id: str, evidence_window_days: int = 7) -> dict:
    """Tool 9：把某个订单相关的原始数据行摊开，供人工/LLM 核实结论。"""
    orders = load_orders()
    match = orders[orders["order_id"] == order_id]

    if match.empty:
        return not_found(
            tool="trace_order_evidence",
            query={"order_id": order_id},
            message=f"No order found with id '{order_id}'.",
        )

    order_row = match.iloc[0]

    order_evidence = {
        "order_id": order_row["order_id"],
        "customer": order_row["customer"],
        "product": order_row["product"],
        "category": order_row["category"],
        "pieces": int(order_row["pieces"]),
        "order_date": order_row["order_date"].date().isoformat(),
        "due_date": order_row["due_date"].date().isoformat(),
        "status": order_row["status"],
        "current_stage": order_row["current_stage"],
        "last_activity_date": (
            order_row["last_activity_date"].date().isoformat()
            if pd.notna(order_row["last_activity_date"])
            else None
        ),
        "completed_date": (
            order_row["completed_date"].date().isoformat()
            if pd.notna(order_row["completed_date"])
            else None
        ),
        "days_late": None if pd.isna(order_row["days_late"]) else int(order_row["days_late"]),
    }

    # 参考日期：已完成用 completed_date，进行中用 last_activity_date
    reference_date = order_row["completed_date"] if order_row["status"] == "COMPLETE" else order_row["last_activity_date"]

    production_rows = []
    if pd.notna(reference_date):
        log = load_production_log()
        window = log[
            (log["date"] <= reference_date)
            & (log["date"] > reference_date - pd.Timedelta(days=evidence_window_days))
        ].sort_values(["date", "stage"])
        production_rows = [
            {
                "date": r["date"].date().isoformat(),
                "stage": r["stage"],
                "pieces_completed": int(r["pieces_completed"]),
            }
            for _, r in window.iterrows()
        ]

    workshops = load_workshops()
    active_for_category = workshops[
        (workshops["status"] == "ACTIVE")
        & (workshops["makes"].str.contains(order_row["category"], case=False, na=False))
    ]
    workshop_rows = [
        {
            "workshop_id": w["workshop_id"],
            "name": w["name"],
            "capacity_pieces_per_day": float(w["capacity_pieces_per_day"]),
            "defect_rate": float(w["defect_rate"]),
            "current_queue_days": float(w["current_queue_days"]),
        }
        for _, w in active_for_category.iterrows()
    ]

    return make_envelope(
        tool="trace_order_evidence",
        query={"order_id": order_id, "evidence_window_days": evidence_window_days},
        data={
            "order": order_evidence,
            "factory_production_records_nearby": production_rows,
            "candidate_workshops": workshop_rows,
        },
        limitations=[
            "production_log.csv has no order_id column. The production records above "
            "are the factory's overall output in the same date window and stage — "
            "they are NOT verified to be this specific order's own output.",
            "candidate_workshops lists active workshops that CAN make this category; "
            "it does not confirm which workshop actually produced this order.",
        ],
    )


if __name__ == "__main__":
    import json

    orders = load_orders()
    sample_id = orders.iloc[0]["order_id"]
    print(json.dumps(trace_order_evidence(sample_id), indent=2, ensure_ascii=False, default=str))
