"""Working-day calendar shared by every module: the factory works Monday to Saturday and is closed on Sundays."""
from __future__ import annotations

from datetime import date, timedelta


def is_working(day: date) -> bool:
    return day.weekday() != 6


def prev_working(day: date) -> date:
    """The last working day before `day`."""
    day -= timedelta(days=1)
    while not is_working(day):
        day -= timedelta(days=1)
    return day


def working_days_between(a: date, b: date) -> int:
    """Working days in (a, b]; negative if b < a."""
    if b < a:
        return -working_days_between(b, a)
    return sum(is_working(a + timedelta(days=i)) for i in range(1, (b - a).days + 1))


def working_days_inclusive(a: date, b: date) -> int:
    """Working days in [a, b]; 0 if b < a."""
    return sum(is_working(a + timedelta(days=i)) for i in range((b - a).days + 1)) if b >= a else 0


def add_working_days(day: date, n: int) -> date:
    """The date n working days after `day`."""
    while n > 0:
        day += timedelta(days=1)
        if is_working(day):
            n -= 1
    return day


def kth_working_day(start: date, k: int) -> date:
    """The date of the k-th working day, counting `start` as day 1 if it is a working day."""
    d, c = start, 1 if is_working(start) else 0
    while c < k:
        d += timedelta(days=1)
        if is_working(d):
            c += 1
    return d
