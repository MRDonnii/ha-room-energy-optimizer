"""Evaluate sustained radiator stress without sending duplicate alerts."""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class StressPeriod:
    started: datetime
    start_temperature: float
    notified: bool = False


def evaluate_stress(
    period: StressPeriod | None,
    *,
    now: datetime,
    valve: float | None,
    current: float | None,
    target: float | None,
    minutes: int,
    enabled: bool,
) -> tuple[StressPeriod | None, tuple[float, float] | None]:
    """Return the active period and (deficit, rise) when one alert is due."""
    if (
        valve is None
        or current is None
        or target is None
        or valve < 99
        or round(target - current, 2) <= 0.3
    ):
        return None, None
    if period is None:
        return StressPeriod(now, current), None
    if period.notified or (now - period.started).total_seconds() < minutes * 60:
        return period, None
    deficit = round(target - current, 2)
    rise = round(current - period.start_temperature, 2)
    if rise >= 0.2:
        period.notified = True
        return period, None
    if not enabled:
        return period, None
    period.notified = True
    return period, (deficit, rise)
