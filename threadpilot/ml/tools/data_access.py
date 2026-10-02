"""
共享数据加载层。

- 统一负责读取 data/orders.csv、production_log.csv、workshops.csv
- 统一做日期解析 / 类型转换
- 用 functools.lru_cache 做简单缓存，避免每个 Tool 调用都重新读 CSV

真实接入时，只需要把 DATA_DIR 指向你们真实的数据目录，
或者把 load_orders / load_production_log / load_workshops
换成读数据库的实现，其它 Tool 代码不用改。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"

# ---- 「今天」的定义 ----
# 这些 CSV 是某个时间点的业务快照，不是实时数据库，
# 所以不能用系统当前时间（比如运行代码那天的真实日期）当作"今天"，
# 那样 due_date / last_activity_date 会全部显得离谱地"过期"或"逾期"。
# 默认策略：自动取数据里出现过的最晚日期（订单活动 + 生产记录）作为"今天"，
# 也可以用 set_today() 手动指定（比如经理说"就当今天是 4 月 1 日"）。
TODAY_OVERRIDE: pd.Timestamp | None = None


def set_today(date: str | pd.Timestamp | None) -> None:
    """手动指定"今天"是哪一天。传 None 可以恢复自动检测。"""
    global TODAY_OVERRIDE
    TODAY_OVERRIDE = pd.Timestamp(date) if date is not None else None


@lru_cache(maxsize=1)
def _infer_today_from_data() -> pd.Timestamp:
    """没有手动指定时，用数据里出现过的最晚日期作为"今天"的代理。"""
    candidates = []

    orders_path = DATA_DIR / "orders.csv"
    if orders_path.exists():
        raw = pd.read_csv(orders_path)
        for col in ["last_activity_date", "order_date", "completed_date"]:
            if col in raw.columns:
                candidates.append(pd.to_datetime(raw[col], errors="coerce").max())

    log_path = DATA_DIR / "production_log.csv"
    if log_path.exists():
        raw = pd.read_csv(log_path)
        if "date" in raw.columns:
            candidates.append(pd.to_datetime(raw["date"], errors="coerce").max())

    candidates = [c for c in candidates if pd.notna(c)]
    if not candidates:
        return pd.Timestamp.now().normalize()
    return max(candidates).normalize()


def get_today() -> pd.Timestamp:
    if TODAY_OVERRIDE is not None:
        return TODAY_OVERRIDE
    return _infer_today_from_data()


@lru_cache(maxsize=1)
def load_orders() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "orders.csv")
    for col in ["order_date", "due_date", "last_activity_date", "completed_date"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    df["days_late"] = pd.to_numeric(df["days_late"], errors="coerce")
    return df


@lru_cache(maxsize=1)
def load_production_log() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "production_log.csv")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["pieces_completed"] = pd.to_numeric(df["pieces_completed"], errors="coerce")
    return df


@lru_cache(maxsize=1)
def load_workshops() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / "workshops.csv")
    numeric_cols = [
        "capacity_pieces_per_day",
        "pickup_lead_days",
        "defect_rate",
        "cost_per_piece",
        "max_batch_pieces",
        "current_queue_days",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def clear_cache() -> None:
    """测试 / 数据更新后调用，清空缓存重新读取 CSV。"""
    load_orders.cache_clear()
    load_production_log.cache_clear()
    load_workshops.cache_clear()
    _infer_today_from_data.cache_clear()
