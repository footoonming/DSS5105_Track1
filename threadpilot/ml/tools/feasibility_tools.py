"""
Tool 6: estimate_completion_date  - 预计一个在制订单何时能完成
Tool 7: assess_order_feasibility  - 判断一个新订单能不能按期接
"""
from __future__ import annotations

import pandas as pd

from schemas.tool_outputs import make_envelope, not_found
from tools.data_access import get_today, load_orders, load_workshops


def _pick_workshop(category: str, workshop_id: str | None = None) -> pd.Series | None:
    """选一个工坊：如果指定了 workshop_id 就用它，否则挑该品类里产能最高的 ACTIVE 工坊。"""
    workshops = load_workshops()
    active = workshops[workshops["status"] == "ACTIVE"]

    if workshop_id:
        match = workshops[workshops["workshop_id"] == workshop_id]
        return match.iloc[0] if not match.empty else None

    candidates = active[active["makes"].str.contains(category, case=False, na=False)]
    if candidates.empty:
        return None
    return candidates.sort_values("capacity_pieces_per_day", ascending=False).iloc[0]


def _effective_capacity(workshop: pd.Series) -> float:
    return round(
        float(workshop["capacity_pieces_per_day"]) * (1 - float(workshop["defect_rate"])), 1
    )


def estimate_completion_date(order_id: str, workshop_id: str | None = None) -> dict:
    """Tool 6：估算一个 IN_PROGRESS 订单的预计完成日期（capacity-based forecast）。"""
    orders = load_orders()
    match = orders[orders["order_id"] == order_id]

    if match.empty:
        return not_found(
            tool="estimate_completion_date",
            query={"order_id": order_id},
            message=f"No order found with id '{order_id}'.",
        )

    order_row = match.iloc[0]

    if order_row["status"] != "IN_PROGRESS":
        return make_envelope(
            tool="estimate_completion_date",
            status="not_found",
            query={"order_id": order_id},
            data={
                "order_id": order_id,
                "status": order_row["status"],
                "message": "Completion-date forecast only applies to IN_PROGRESS orders.",
            },
        )

    workshop = _pick_workshop(order_row["category"], workshop_id)
    if workshop is None:
        return make_envelope(
            tool="estimate_completion_date",
            status="error",
            query={"order_id": order_id, "workshop_id": workshop_id},
            data={"message": f"No active workshop found that makes category '{order_row['category']}'."},
        )

    today = get_today()
    # 数据限制：orders.csv 没有 completed_quantity，所以无法知道已完成多少件，
    # 只能保守地把全部 pieces 当作"剩余待完成数量"。
    remaining_pieces = float(order_row["pieces"])

    effective_capacity = _effective_capacity(workshop)
    production_days = round(remaining_pieces / effective_capacity, 2) if effective_capacity > 0 else None
    queue_days = float(workshop["current_queue_days"])
    pickup_days = float(workshop["pickup_lead_days"])

    total_days = None
    estimated_completion_date = None
    if production_days is not None:
        total_days = round(production_days + queue_days + pickup_days, 2)
        estimated_completion_date = (today + pd.Timedelta(days=total_days)).date().isoformat()

    return make_envelope(
        tool="estimate_completion_date",
        query={"order_id": order_id, "workshop_id": workshop_id},
        data={
            "order_id": order_id,
            "pieces": int(order_row["pieces"]),
            "remaining_pieces": int(remaining_pieces),
            "workshop": {
                "workshop_id": workshop["workshop_id"],
                "name": workshop["name"],
                "capacity_per_day": float(workshop["capacity_pieces_per_day"]),
                "defect_rate": float(workshop["defect_rate"]),
                "effective_capacity_per_day": effective_capacity,
                "current_queue_days": queue_days,
                "pickup_lead_days": pickup_days,
            },
            "forecast": {
                "production_days": production_days,
                "queue_days": queue_days,
                "pickup_days": pickup_days,
                "total_estimated_days": total_days,
                "estimated_completion_date": estimated_completion_date,
            },
        },
        calculation={
            "effective_capacity_per_day": "capacity_pieces_per_day * (1 - defect_rate)",
            "production_days": "remaining_pieces / effective_capacity_per_day",
            "total_estimated_days": "production_days + current_queue_days + pickup_lead_days",
        },
        assumptions=[
            "Workshop capacity and defect rate remain stable during production.",
            "No disruption to the workshop or supply chain.",
            "Order is assumed to receive the workshop's full stated capacity exclusively.",
        ],
        limitations=[
            "orders.csv has no completed_quantity field, so remaining_pieces "
            "conservatively assumes 0 pieces completed so far.",
        ],
    )


def assess_order_feasibility(
    product: str,
    category: str,
    pieces: int,
    due_date: str,
    workshop_id: str | None = None,
) -> dict:
    """Tool 7：判断一个假设中的新订单能否按 due_date 完成。"""
    today = get_today()
    due = pd.Timestamp(due_date)

    workshop = _pick_workshop(category, workshop_id)
    if workshop is None:
        return make_envelope(
            tool="assess_order_feasibility",
            status="error",
            query={
                "product": product,
                "category": category,
                "pieces": pieces,
                "due_date": due_date,
            },
            data={"message": f"No active workshop found that makes category '{category}'."},
        )

    effective_capacity = _effective_capacity(workshop)
    production_days = round(pieces / effective_capacity, 2) if effective_capacity > 0 else None
    queue_days = float(workshop["current_queue_days"])
    pickup_days = float(workshop["pickup_lead_days"])

    total_days = round(production_days + queue_days + pickup_days, 2) if production_days is not None else None
    estimated_completion_date = (
        (today + pd.Timedelta(days=total_days)) if total_days is not None else None
    )

    days_available = (due - today).days
    buffer_days = (
        round((due - estimated_completion_date).days, 1) if estimated_completion_date is not None else None
    )
    feasible = buffer_days is not None and buffer_days >= 0

    if buffer_days is None:
        confidence = "LOW"
    elif buffer_days >= 5:
        confidence = "HIGH"
    elif buffer_days >= 0:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"  # 明确不可行，也是"高置信度"的判断

    risks = []
    if pieces > float(workshop["max_batch_pieces"]):
        risks.append(
            f"Requested pieces ({pieces}) exceed workshop max batch size "
            f"({int(workshop['max_batch_pieces'])}); may need to split across batches."
        )
    if buffer_days is not None and 0 <= buffer_days < 3:
        risks.append("Buffer is thin (<3 days); any small disruption could cause a delay.")
    risks.append("Capacity estimate depends on the historical/stated production rate holding steady.")

    return make_envelope(
        tool="assess_order_feasibility",
        query={
            "product": product,
            "category": category,
            "pieces": pieces,
            "due_date": due_date,
            "workshop_id": workshop_id,
        },
        data={
            "request": {
                "product": product,
                "category": category,
                "pieces": pieces,
                "due_date": due_date,
            },
            "capacity": {
                "workshop_id": workshop["workshop_id"],
                "workshop_name": workshop["name"],
                "effective_capacity_per_day": effective_capacity,
                "current_queue_days": queue_days,
            },
            "forecast": {
                "estimated_production_days": production_days,
                "estimated_completion_date": (
                    estimated_completion_date.date().isoformat()
                    if estimated_completion_date is not None
                    else None
                ),
            },
            "decision": {
                "feasible": feasible,
                "days_available": days_available,
                "buffer_days": buffer_days,
                "confidence": confidence,
            },
        },
        calculation={
            "effective_capacity_per_day": "capacity_pieces_per_day * (1 - defect_rate)",
            "estimated_completion_date": "today + production_days + queue_days + pickup_lead_days",
            "buffer_days": "due_date - estimated_completion_date",
        },
        assumptions=[
            "Active workshops only.",
            "Current workshop capacity and queue remain stable.",
            "No major production disruption.",
        ],
        evidence=[
            {
                "workshop_id": workshop["workshop_id"],
                "capacity_pieces_per_day": float(workshop["capacity_pieces_per_day"]),
                "defect_rate": float(workshop["defect_rate"]),
                "current_queue_days": queue_days,
                "pickup_lead_days": pickup_days,
                "max_batch_pieces": float(workshop["max_batch_pieces"]),
            }
        ],
        limitations=risks,
    )


if __name__ == "__main__":
    import json

    orders = load_orders()
    sample_id = orders[orders["status"] == "IN_PROGRESS"].iloc[0]["order_id"]
    print(json.dumps(estimate_completion_date(sample_id), indent=2, ensure_ascii=False, default=str))
    print(
        json.dumps(
            assess_order_feasibility("Hoodie", "TOPS", 800, "2026-05-01"),
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
