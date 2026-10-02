"""
Tool 1: get_order_status      - 查询单个订单
Tool 2: get_customer_orders   - 查询客户所有订单
"""
from __future__ import annotations

import pandas as pd

from schemas.tool_outputs import make_envelope, not_found
from tools.data_access import load_orders


def _row_to_order_dict(row: pd.Series) -> dict:
    return {
        "order_id": row["order_id"],
        "customer": row["customer"],
        "product": row["product"],
        "category": row["category"],
        "pieces": int(row["pieces"]),
        "order_date": _fmt_date(row["order_date"]),
        "due_date": _fmt_date(row["due_date"]),
        "status": row["status"],
        "current_stage": row["current_stage"],
        "last_activity_date": _fmt_date(row["last_activity_date"]),
        "completed_date": _fmt_date(row["completed_date"]),
        "days_late": None if pd.isna(row["days_late"]) else int(row["days_late"]),
    }


def _fmt_date(value) -> str | None:
    if pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def get_order_status(order_id: str) -> dict:
    """Tool 1：查询单个订单当前状态。"""
    orders = load_orders()
    match = orders[orders["order_id"] == order_id]

    if match.empty:
        return not_found(
            tool="get_order_status",
            query={"order_id": order_id},
            message=f"No order found with id '{order_id}'.",
        )

    row = match.iloc[0]
    return make_envelope(
        tool="get_order_status",
        query={"order_id": order_id},
        data=_row_to_order_dict(row),
    )


def get_customer_orders(customer: str) -> dict:
    """Tool 2：查询某个客户名下的所有订单。

    注意：客户名可能对应多个订单，Agent 拿到结果后如果需要针对
    "某一个订单"回答问题，应该向用户澄清是哪一个，而不是自己猜。
    """
    orders = load_orders()
    match = orders[orders["customer"].str.lower() == customer.lower()]

    if match.empty:
        return not_found(
            tool="get_customer_orders",
            query={"customer": customer},
            message=f"No orders found for customer '{customer}'.",
        )

    order_list = [_row_to_order_dict(row) for _, row in match.iterrows()]

    completed = match[match["status"] == "COMPLETE"]
    on_time_mask = completed["days_late"].fillna(0) <= 0

    return make_envelope(
        tool="get_customer_orders",
        query={"customer": customer},
        data={
            "customer": customer,
            "order_count": int(len(match)),
            "status_breakdown": match["status"].value_counts().to_dict(),
            "orders": order_list,
        },
        calculation={
            "completed_orders": int(len(completed)),
            "on_time_orders": int(on_time_mask.sum()),
            "on_time_rate": round(float(on_time_mask.mean()), 3) if len(completed) else None,
        },
    )


if __name__ == "__main__":
    import json

    print(json.dumps(get_order_status("ORD-001"), indent=2, ensure_ascii=False, default=str))
    print(json.dumps(get_customer_orders("TrendCart"), indent=2, ensure_ascii=False, default=str))
