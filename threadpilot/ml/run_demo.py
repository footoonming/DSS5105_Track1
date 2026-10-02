"""
一键跑通全部 9 个 Tool，打印每个的 JSON 输出，方便你直接看格式 / 接大模型前自测。

运行：
    cd project/
    python run_demo.py
"""
from __future__ import annotations

import json

from tools.data_access import load_orders
from tools.discovery_tools import discover_factory_risks
from tools.feasibility_tools import assess_order_feasibility, estimate_completion_date
from tools.order_tools import get_customer_orders, get_order_status
from tools.prediction_tools import predict_order_delay
from tools.production_tools import get_order_performance
from tools.risk_tools import get_at_risk_orders
from tools.tracing_tools import trace_order_evidence


def show(title: str, result: dict) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def main() -> None:
    orders = load_orders()
    complete_id = orders[orders["status"] == "COMPLETE"].iloc[0]["order_id"]
    in_progress_id = orders[orders["status"] == "IN_PROGRESS"].iloc[0]["order_id"]
    a_customer = orders.iloc[0]["customer"]

    show("Tool 1: get_order_status", get_order_status(complete_id))
    show("Tool 2: get_customer_orders", get_customer_orders(a_customer))
    show("Tool 3: get_at_risk_orders", get_at_risk_orders())
    show("Tool 4: get_order_performance", get_order_performance(complete_id))
    show("Tool 5: predict_order_delay", predict_order_delay(in_progress_id))
    show("Tool 6: estimate_completion_date", estimate_completion_date(in_progress_id))
    show(
        "Tool 7: assess_order_feasibility",
        assess_order_feasibility("Hoodie", "TOPS", 800, "2026-05-01"),
    )
    show("Tool 8: discover_factory_risks", discover_factory_risks(top_n=5))
    show("Tool 9: trace_order_evidence", trace_order_evidence(in_progress_id))


if __name__ == "__main__":
    main()
