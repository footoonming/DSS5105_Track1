"""
Tool 5: predict_order_delay

加载训练好的 Logistic Regression pipeline，对一个 IN_PROGRESS 订单
预测"延期概率"。

如果模型还没训练 / 样本不足没有产出 delay_model.pkl，
会明确返回 status="error" 并说明原因，而不是编造一个概率。
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd

from models.feature_engineering import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    build_features_for_order,
)
from schemas.tool_outputs import error, make_envelope, not_found
from tools.data_access import get_today, load_orders

MODELS_DIR = Path(__file__).parent.parent / "models"
MODEL_PATH = MODELS_DIR / "delay_model.pkl"
REPORT_PATH = MODELS_DIR / "training_report.json"

HIGH_RISK_THRESHOLD = 0.6
MEDIUM_RISK_THRESHOLD = 0.35


def _risk_level(p: float) -> str:
    if p >= HIGH_RISK_THRESHOLD:
        return "HIGH"
    if p >= MEDIUM_RISK_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def predict_order_delay(order_id: str) -> dict:
    """Tool 5：预测一个订单未来延期的概率。"""
    orders = load_orders()
    match = orders[orders["order_id"] == order_id]

    if match.empty:
        return not_found(
            tool="predict_order_delay",
            query={"order_id": order_id},
            message=f"No order found with id '{order_id}'.",
        )

    order_row = match.iloc[0]

    if order_row["status"] != "IN_PROGRESS":
        return make_envelope(
            tool="predict_order_delay",
            status="not_found",
            query={"order_id": order_id},
            data={
                "order_id": order_id,
                "status": order_row["status"],
                "message": "Delay prediction only applies to IN_PROGRESS orders.",
            },
        )

    if not MODEL_PATH.exists():
        return error(
            tool="predict_order_delay",
            query={"order_id": order_id},
            message=(
                "No trained model available. Run `python -m models.train_delay_model` "
                "first, or fall back to get_at_risk_orders for a rule-based estimate."
            ),
        )

    pipeline = joblib.load(MODEL_PATH)
    training_report = {}
    if REPORT_PATH.exists():
        training_report = json.loads(REPORT_PATH.read_text())

    today = get_today()
    features = build_features_for_order(order_row, reference_date=today)

    X = pd.DataFrame([{k: features[k] for k in NUMERIC_FEATURES + CATEGORICAL_FEATURES}])
    proba = float(pipeline.predict_proba(X)[0, 1])
    risk_level = _risk_level(proba)

    days_since_activity = (today - order_row["last_activity_date"]).days
    days_to_due = (order_row["due_date"] - today).days

    return make_envelope(
        tool="predict_order_delay",
        query={"order_id": order_id},
        data={
            "order_id": order_id,
            "prediction": {
                "delay_probability": round(proba, 3),
                "risk_level": risk_level,
                "predicted_delay": proba >= 0.5,
            },
            "features": {
                **features,
                "days_since_activity": days_since_activity,
                "days_to_due": days_to_due,
            },
            "model": {
                "name": training_report.get("model_name", "LogisticRegression"),
                "version": training_report.get("model_version", "v1"),
                "training_samples": training_report.get("total_samples"),
                "target": "order_delayed (days_late > 0)",
            },
        },
        calculation={
            "thresholds": {
                "HIGH": f">= {HIGH_RISK_THRESHOLD}",
                "MEDIUM": f">= {MEDIUM_RISK_THRESHOLD}",
                "LOW": f"< {MEDIUM_RISK_THRESHOLD}",
            }
        },
        assumptions=[
            "Workshop capacity/queue/defect-rate features reflect current snapshot, "
            "not necessarily the workshop this order will actually use.",
            "factory_output_trend is a whole-factory signal, not specific to this order.",
        ],
        limitations=[
            "production_log has no order_id, so no production feature is directly "
            "attributable to this specific order.",
            "Model trained on a small historical sample "
            f"({training_report.get('total_samples', 'unknown')} orders); "
            "treat this as a risk estimate, not a guarantee.",
        ],
    )


if __name__ == "__main__":
    orders = load_orders()
    sample_id = orders[orders["status"] == "IN_PROGRESS"].iloc[0]["order_id"]
    print(json.dumps(predict_order_delay(sample_id), indent=2, ensure_ascii=False, default=str))
