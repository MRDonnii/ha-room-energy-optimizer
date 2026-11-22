"""Boundary cases for optional radiator-stress notifications."""

import sys
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components/room_energy_optimizer/alerts.py"
SPEC = spec_from_file_location("room_energy_optimizer_alerts", PATH)
alerts = module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = alerts
SPEC.loader.exec_module(alerts)

START = datetime(2026, 1, 1, tzinfo=UTC)


def evaluate(period=None, *, minute=0, valve=100, current=20, target=21, enabled=True):
    return alerts.evaluate_stress(
        period,
        now=START + timedelta(minutes=minute),
        valve=valve,
        current=current,
        target=target,
        minutes=60,
        enabled=enabled,
    )


def test_only_one_alert_after_full_observation_period():
    period, due = evaluate()
    assert due is None
    period, due = evaluate(period, minute=59, current=20.1)
    assert due is None
    period, due = evaluate(period, minute=60, current=20.1)
    assert due == (0.9, 0.1)
    assert evaluate(period, minute=120, current=20.1)[1] is None


def test_good_progress_consumes_period_without_alert():
    period, _ = evaluate()
    period, due = evaluate(period, minute=60, current=20.2)
    assert due is None and period.notified
    assert evaluate(period, minute=120, current=20.1)[1] is None


def test_disabled_switch_and_reset_between_stress_periods():
    period, _ = evaluate()
    period, due = evaluate(period, minute=60, current=20.1, enabled=False)
    assert due is None and not period.notified
    period, due = evaluate(period, minute=61, current=20.1, enabled=True)
    assert due == (0.9, 0.1)
    assert evaluate(period, minute=62, valve=98)[0] is None


def test_invalid_measurements_and_exact_thresholds_do_not_alert():
    period, _ = evaluate()
    assert evaluate(period, minute=60, current=None)[0] is None
    assert evaluate(period, minute=60, current=20.7, target=21)[0] is None
    assert evaluate(period, minute=60, valve=98.9)[0] is None
