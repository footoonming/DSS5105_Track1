"""
Tool 3: get_at_risk_orders

规则型（非 ML）风险判断，找出当前正在进行、且有风险迹象的订单。

三条规则：
  R1  LATE               ：已经过了 due_date 但还没 COMPLETE
  R2  STALLED             ：最近 N 天没有任何活动更新
  R3  DEADLINE_PRESSURE   ：临近 due_date 但剩余时间很紧张
"""
from __future__ import annotations

import pandas as pd

from schemas.tool_outputs import make_envelope
from tools.data_access import get_today, load_orders

STALLED_THRESHOLD_DAYS = 5
DEADLINE_PRESSURE_DAYS = 5


def get_at_risk_orders(
    stalled_threshold_days: int = STALLED_THRESHOLD_DAYS,
    deadline_pressure_days: int = DEADLINE_PRESSURE_DAYS,
) -> dict:
    """Tool 3：扫描所有 IN_PROGRESS 订单，标出风险订单及风险原因。"""
    orders = load_orders()
    today = get_today()

    in_progress = orders[orders["status"] == "IN_PROGRESS"].copy()

    if in_progress.empty:
        return make_envelope(
            tool="get_at_risk_orders",
            query={
                "stalled_threshold_days": stalled_threshold_days,
                "deadline_pressure_days": deadline_pressure_days,
            },
            data={"risk_orders": []},
        )

    in_progress["days_since_activity"] = (today - in_progress["last_activity_date"]).dt.days
    in_progress["days_to_due"] = (in_progress["due_date"] - today).dt.days

    risk_orders = []
    for _, row in in_progress.iterrows():
        reasons = []
        risk_score = 0

        if row["days_to_due"] < 0:
            reasons.append("Past due date and not yet completed")
            risk_score += 3
        elif row["days_to_due"] <= deadline_pressure_days:
            reasons.append(
                f"Due date is within {deadline_pressure_days} days "
                f"({int(row['days_to_due'])} days left)"
            )
            risk_score += 2

        if row["days_since_activity"] >= stalled_threshold_days:
            reasons.append(
                f"No activity update for {int(row['days_since_activity'])} days"
            )
            risk_score += 2

        if not reasons:
            continue

        risk_level = "HIGH" if risk_score >= 4 else "MEDIUM" if risk_score >= 2 else "LOW"

        risk_orders.append(
            {
                "order_id": row["order_id"],
                "customer": row["customer"],
                "current_stage": row["current_stage"],
                "days_since_activity": int(row["days_since_activity"]),
                "days_to_due": int(row["days_to_due"]),
                "risk_score": risk_score,
                "risk_level": risk_level,
                "risk_reasons": reasons,
            }
        )

    risk_orders.sort(key=lambda x: x["risk_score"], reverse=True)

    return make_envelope(
        tool="get_at_risk_orders",
        query={
            "stalled_threshold_days": stalled_threshold_days,
            "deadline_pressure_days": deadline_pressure_days,
        },
        data={
            "risk_order_count": len(risk_orders),
            "risk_orders": risk_orders,
        },
        calculation={
            "rules": [
                "LATE: days_to_due < 0",
                f"DEADLINE_PRESSURE: 0 <= days_to_due <= {deadline_pressure_days}",
                f"STALLED: days_since_activity >= {stalled_threshold_days}",
            ]
        },
        limitations=[
            "This is a rule-based screen, not a probability estimate. "
            "Use predict_order_delay for a modeled delay probability."
        ],
    )


if __name__ == "__main__":
    import json

    print(json.dumps(get_at_risk_orders(), indent=2, ensure_ascii=False, default=str))
