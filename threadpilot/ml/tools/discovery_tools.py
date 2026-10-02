"""
Tool 8: discover_factory_risks

主动扫描（而不是等人来问）三类风险，统一打分排序，供 "Morning Briefing" 使用：
    1. ORDER_DELAY_RISK  —— 来自 get_at_risk_orders 的规则型风险
                             （如果模型可用，补充 predict_order_delay 的概率）
    2. PRODUCTION_DROP   —— 某个工序近期产出相对历史基线明显下滑
    3. WORKSHOP_OVERLOAD —— 工坊排队天数过长 / 逼近最大批量
"""
from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd

from models.feature_engineering import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    build_features_for_order,
)
from schemas.tool_outputs import make_envelope
from tools.data_access import get_today, load_orders, load_workshops
from tools.production_tools import get_stage_stats
from tools.risk_tools import get_at_risk_orders

MODEL_PATH = Path(__file__).parent.parent / "models" / "delay_model.pkl"

PRODUCTION_DROP_THRESHOLD = -0.15  # 近期均值比历史基线低 15% 以上，算风险
QUEUE_DAYS_WARNING = 3.0


def _order_delay_findings() -> list[dict]:
    findings = []
    risk_result = get_at_risk_orders()
    risk_orders = risk_result["data"].get("risk_orders", [])

    model = None
    if MODEL_PATH.exists():
        model = joblib.load(MODEL_PATH)

    orders = load_orders()
    today = get_today()

    for r in risk_orders:
        score = min(r["risk_score"] / 5.0, 1.0)  # 规则分数归一化到 0-1

        prob = None
        if model is not None:
            order_row = orders[orders["order_id"] == r["order_id"]].iloc[0]
            features = build_features_for_order(order_row, reference_date=today)
            X = pd.DataFrame([{k: features[k] for k in NUMERIC_FEATURES + CATEGORICAL_FEATURES}])
            prob = round(float(model.predict_proba(X)[0, 1]), 3)
            score = max(score, prob)

        findings.append(
            {
                "type": "ORDER_DELAY_RISK",
                "severity": r["risk_level"],
                "entity_id": r["order_id"],
                "score": round(score, 3),
                "summary_data": {
                    "customer": r["customer"],
                    "days_since_activity": r["days_since_activity"],
                    "days_to_due": r["days_to_due"],
                    "risk_reasons": r["risk_reasons"],
                    "delay_probability": prob,
                },
            }
        )
    return findings


def _production_drop_findings() -> list[dict]:
    findings = []
    orders = load_orders()
    stages = sorted(set(o for o in [] ) )  # placeholder, replaced below
    from tools.data_access import load_production_log

    stages = sorted(load_production_log()["stage"].unique())

    for stage in stages:
        stats = get_stage_stats(stage)
        if stats["baseline_avg"] and stats["trend"] is not None and stats["trend"] <= PRODUCTION_DROP_THRESHOLD:
            change_pct = round(stats["trend"] * 100, 1)
            severity = "HIGH" if stats["trend"] <= -0.30 else "MEDIUM"
            findings.append(
                {
                    "type": "PRODUCTION_DROP",
                    "severity": severity,
                    "entity_id": stage,
                    "score": round(min(abs(stats["trend"]), 1.0), 3),
                    "summary_data": {
                        "recent_avg": stats["recent_avg"],
                        "baseline_avg": stats["baseline_avg"],
                        "change_pct": change_pct,
                    },
                }
            )
    return findings


def _workshop_overload_findings() -> list[dict]:
    findings = []
    workshops = load_workshops()
    active = workshops[workshops["status"] == "ACTIVE"]

    for _, w in active.iterrows():
        if w["current_queue_days"] >= QUEUE_DAYS_WARNING:
            severity = "HIGH" if w["current_queue_days"] >= 5 else "MEDIUM"
            findings.append(
                {
                    "type": "WORKSHOP_OVERLOAD",
                    "severity": severity,
                    "entity_id": w["workshop_id"],
                    "score": round(min(float(w["current_queue_days"]) / 7.0, 1.0), 3),
                    "summary_data": {
                        "name": w["name"],
                        "current_queue_days": float(w["current_queue_days"]),
                        "capacity_pieces_per_day": float(w["capacity_pieces_per_day"]),
                    },
                }
            )
    return findings


def discover_factory_risks(top_n: int = 10) -> dict:
    """Tool 8：主动发现当前需要关注的风险，按 score 排序。"""
    findings = (
        _order_delay_findings() + _production_drop_findings() + _workshop_overload_findings()
    )
    findings.sort(key=lambda f: f["score"], reverse=True)

    for i, f in enumerate(findings, start=1):
        f["rank"] = i

    return make_envelope(
        tool="discover_factory_risks",
        query={"top_n": top_n},
        data={
            "generated_at": get_today().date().isoformat(),
            "finding_count": len(findings),
            "findings": findings[:top_n],
        },
        calculation={
            "ranking_method": "sorted by score descending "
            "(order-delay: rule score or model probability; "
            "production-drop: |trend|; workshop-overload: queue_days / 7)",
        },
        limitations=[
            "PRODUCTION_DROP findings are factory-wide per stage, not attributable "
            "to individual orders (production_log has no order_id).",
        ],
    )


if __name__ == "__main__":
    import json

    print(json.dumps(discover_factory_risks(), indent=2, ensure_ascii=False, default=str))
