"""
特征工程模块。

核心原则：训练时用什么逻辑算特征，预测时就必须用【同一个函数】算特征，
否则会出现 train/serve skew。所以这里只暴露一个函数：

    build_features_for_order(order_row, reference_date) -> dict

训练脚本（train_delay_model.py）和预测 Tool（prediction_tools.py）
都只调用这一个函数。

特征列表（都是 production_log 没有 order_id 前提下，仍然可以合理计算的特征）：
    - pieces                       订单数量
    - category                     TOPS / BOTTOMS / OUTERWEAR（one-hot）
    - planned_lead_days            due_date - order_date
    - workshop_avg_capacity        能接这个 category 的活跃工坊的平均产能
    - workshop_avg_queue_days      能接这个 category 的活跃工坊的平均排队天数
    - workshop_avg_defect_rate     能接这个 category 的活跃工坊的平均缺陷率
    - factory_output_trend         参考日期前，工厂整体日产出的近期趋势
                                    （不能归因到具体订单，只能代表"当时工厂整体产能状况"）
"""
from __future__ import annotations

import pandas as pd

from tools.data_access import load_orders, load_production_log, load_workshops

FEATURE_COLUMNS = [
    "pieces",
    "category",
    "planned_lead_days",
    "workshop_avg_capacity",
    "workshop_avg_queue_days",
    "workshop_avg_defect_rate",
    "factory_output_trend",
]

NUMERIC_FEATURES = [
    "pieces",
    "planned_lead_days",
    "workshop_avg_capacity",
    "workshop_avg_queue_days",
    "workshop_avg_defect_rate",
    "factory_output_trend",
]
CATEGORICAL_FEATURES = ["category"]


def _matching_workshop_stats(category: str) -> dict:
    """找出能生产该 category、且状态 ACTIVE 的工坊，取平均产能/排队/缺陷率。"""
    workshops = load_workshops()
    active = workshops[workshops["status"] == "ACTIVE"]
    match = active[active["makes"].str.contains(category, case=False, na=False)]

    if match.empty:
        # 没有工坊能做这个品类 —— 这本身就是一个重要信号，用全体活跃工坊兜底
        match = active

    if match.empty:
        return {
            "workshop_avg_capacity": 0.0,
            "workshop_avg_queue_days": 0.0,
            "workshop_avg_defect_rate": 0.0,
        }

    return {
        "workshop_avg_capacity": round(float(match["capacity_pieces_per_day"].mean()), 1),
        "workshop_avg_queue_days": round(float(match["current_queue_days"].mean()), 2),
        "workshop_avg_defect_rate": round(float(match["defect_rate"].mean()), 3),
    }


def get_factory_output_trend(reference_date: pd.Timestamp, recent_days: int = 14, baseline_days: int = 45) -> float:
    """计算参考日期之前，工厂整体（所有工序合计）日产出的近期趋势。

    正数 = 近期产出比历史基线高；负数 = 产出在下滑。
    这是【工厂整体】指标，不代表任何单个订单的进度。
    """
    log = load_production_log()
    daily = log.groupby("date", as_index=False)["pieces_completed"].sum()

    recent = daily[
        (daily["date"] <= reference_date)
        & (daily["date"] > reference_date - pd.Timedelta(days=recent_days))
    ]
    baseline = daily[
        (daily["date"] <= reference_date)
        & (daily["date"] > reference_date - pd.Timedelta(days=baseline_days))
    ]

    recent_avg = recent["pieces_completed"].mean()
    baseline_avg = baseline["pieces_completed"].mean()

    if pd.isna(baseline_avg) or baseline_avg == 0 or pd.isna(recent_avg):
        return 0.0

    return round(float((recent_avg - baseline_avg) / baseline_avg), 4)


def build_features_for_order(order_row: pd.Series, reference_date: pd.Timestamp) -> dict:
    """给定一行订单数据 + 参考日期（训练时用 due_date，预测时用"今天"），算出特征字典。"""
    category = order_row["category"]
    planned_lead_days = (order_row["due_date"] - order_row["order_date"]).days

    workshop_stats = _matching_workshop_stats(category)
    trend = get_factory_output_trend(reference_date)

    return {
        "pieces": float(order_row["pieces"]),
        "category": category,
        "planned_lead_days": float(planned_lead_days),
        "workshop_avg_capacity": workshop_stats["workshop_avg_capacity"],
        "workshop_avg_queue_days": workshop_stats["workshop_avg_queue_days"],
        "workshop_avg_defect_rate": workshop_stats["workshop_avg_defect_rate"],
        "factory_output_trend": trend,
    }


def build_training_table() -> pd.DataFrame:
    """构建训练表：只用 COMPLETE 订单（有明确的 delayed / not delayed 结果）。

    reference_date 用 due_date，模拟"临近截止日期时能看到的信息"。
    target: delayed = 1 if days_late > 0 else 0
    """
    orders = load_orders()
    completed = orders[orders["status"] == "COMPLETE"].copy()

    rows = []
    for _, order_row in completed.iterrows():
        features = build_features_for_order(order_row, reference_date=order_row["due_date"])
        features["order_id"] = order_row["order_id"]
        features["delayed"] = int(order_row["days_late"] > 0)
        rows.append(features)

    return pd.DataFrame(rows)


if __name__ == "__main__":
    table = build_training_table()
    print(table.head(10).to_string())
    print("\nClass balance:")
    print(table["delayed"].value_counts())
    print(f"\nTotal training rows: {len(table)}")
