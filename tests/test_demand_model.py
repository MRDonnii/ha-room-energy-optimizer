"""Tests for the energy-signature heat demand model (model v3)."""

import sys
from datetime import date, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components/room_energy_optimizer/model.py"
SPEC = spec_from_file_location("room_energy_optimizer_model_v3", PATH)
model = module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)

HOUR = 3600
BASE = 500_000 * HOUR  # hour-aligned epoch for the window tests


def learn(values, lifts=None, winds=None, lift=8.0, wind=None, **overrides):
    options = {
        "min_days": 7,
        "max_lift_diff": 3.0,
        "wind_scale": 2.0,
        "min_similar": 5,
        "max_similar": 10,
        "min_relative_spread": 0.1,
        "min_spread_w": 5.0,
    }
    options.update(overrides)
    lifts = lifts or [8.0] * len(values)
    winds = winds or [None] * len(values)
    days = [
        model.DemandDay(value, day_lift, day_wind)
        for value, day_lift, day_wind in zip(values, lifts, winds, strict=True)
    ]
    return model.learn_demand_baseline(days, lift, wind, **options)


def classify(recent, baseline, previous="learning"):
    return model.classify_demand(recent, baseline, previous, z_enter=3.0, z_exit=2.0)


def test_closed_radiator_counts_as_zero_output():
    totals = model.DemandTotals()
    totals.add(1.0, 500.0, 10.0, None, True)
    totals.add(3.0, 0.0, 10.0, None, True)
    assert totals.w_per_degree(1.0, 3.0) == 12.5


def test_excluded_time_is_left_out_of_the_balance():
    totals = model.DemandTotals()
    totals.add(1.0, 500.0, 10.0, None, True)
    totals.add(2.0, 1500.0, 10.0, None, False)
    assert totals.w_per_degree(1.0, 3.0) == 50.0
    assert totals.excluded_hours == 2.0


def test_w_per_degree_needs_enough_clean_hours_and_lift():
    short = model.DemandTotals()
    short.add(2.0, 100.0, 10.0, None, True)
    assert short.w_per_degree(24.0, 3.0) is None
    mild = model.DemandTotals()
    mild.add(30.0, 50.0, 1.0, None, True)
    assert mild.w_per_degree(24.0, 3.0) is None


def test_recent_window_covers_the_last_48_clock_hours():
    demand = model.DemandModel()
    demand.add(BASE - 60 * HOUR, "d1", 1.0, 900.0, 10.0, None, True)
    demand.add(BASE - 10 * HOUR, "d2", 1.0, 100.0, 10.0, None, True)
    recent = demand.recent(BASE + 1800, 48)
    assert recent.energy_wh == 100.0
    assert recent.clean_hours == 1.0


def test_valid_days_skip_today_and_thin_days():
    demand = model.DemandModel()
    demand.add(BASE, "2026-09-20", 20.0, 100.0, 8.0, None, True)
    demand.add(BASE, "2026-09-21", 5.0, 100.0, 8.0, None, True)
    demand.add(BASE, "2026-09-22", 20.0, 100.0, 8.0, None, True)
    days = demand.valid_days("2026-09-22", 28, 12.0, 3.0)
    assert [key for key, _ in days] == ["2026-09-20"]


def test_first_sample_does_not_anchor_the_learned_normal():
    """Regression: model v2 flagged a steady garage because its baseline kept
    most of the weight of the very first, unusually low sample."""
    values = [3.1, 13.0, 14.0, 13.5, 12.8, 14.2, 13.6, 13.1, 13.9, 13.4, 13.7]
    baseline = learn(values)
    assert 13.0 < baseline.expected < 14.0
    assert classify(13.2, baseline)[0] == "normal"


def test_spread_uses_the_rooms_variation_with_floors():
    assert learn([10.0] * 8).spread == 1.0
    varied = learn([6.0, 14.0, 8.0, 12.0, 10.0, 7.0, 13.0, 10.0])
    assert varied.spread > 1.0
    assert learn([0.0] * 8, lift=10.0).spread == 0.5


def test_idle_radiator_is_normal_until_it_starts_working():
    baseline = learn([0.0, 0.1, 0.0, 0.0, 0.2, 0.0, 0.1], lift=10.0)
    assert baseline.expected == 0.0
    assert classify(0.1, baseline)[0] == "normal"
    assert classify(2.0, baseline)[0] == "deviating"


def test_learning_until_seven_valid_days():
    baseline = learn([10.0] * 6)
    assert baseline.expected is None
    assert baseline.days == 6
    assert classify(10.0, baseline) == ("learning", None)


def test_deviating_needs_three_spreads_and_clears_with_hysteresis():
    baseline = learn([10.0, 11.0, 9.0, 10.0, 10.5, 9.5, 10.0])
    assert baseline.expected == 10.0
    assert baseline.spread == 1.0
    status, z_score = classify(13.5, baseline)
    assert status == "deviating"
    assert round(z_score, 1) == 3.5
    assert classify(12.5, baseline, "deviating")[0] == "deviating"
    assert classify(11.5, baseline, "deviating")[0] == "normal"
    assert classify(12.5, baseline, "normal")[0] == "normal"


def test_only_days_with_similar_weather_are_compared():
    # Mild days need less radiator heat per degree than cold ones (free heat
    # matters more); a cold spell must be compared with cold days only.
    lifts = [5.0] * 7 + [12.0] * 7
    values = [1.0] * 7 + [4.0] * 7
    cold = learn(values, lifts, lift=12.5)
    assert cold.expected == 4.0
    assert cold.lift_range == (12.0, 12.0)
    assert learn(values, lifts, lift=5.5).expected == 1.0


def test_unseen_weather_is_not_judged():
    baseline = learn([2.0] * 10, [5.0] * 10, lift=12.0)
    assert baseline.expected is None
    assert baseline.days == 10
    assert baseline.compared == 0
    assert classify(6.0, baseline) == ("learning", None)


def test_wind_picks_the_most_similar_days():
    lifts = [8.0] * 12
    winds = [1.0] * 6 + [9.0] * 6
    values = [2.0] * 6 + [3.0] * 6
    windy = learn(values, lifts, winds, lift=8.0, wind=8.5, max_similar=6)
    assert windy.expected == 3.0
    assert windy.wind_range == (9.0, 9.0)
    calm = learn(values, lifts, winds, lift=8.0, wind=1.5, max_similar=6)
    assert calm.expected == 2.0


def test_exclusion_tail_keeps_samples_out_after_it_ends():
    tail = model.ExclusionTail(1.0)
    assert tail.clean(0.0, False) is True
    assert tail.clean(10.0, True) is False
    assert tail.clean(1800.0, False) is False
    assert tail.clean(3610.0, False) is True


def test_external_heat_sources_and_stove_hysteresis():
    room = model.room_from_dict(
        {
            "name": "Stue",
            "climate_entity": "climate.living",
            "rated_power_w": 1000,
            "area_m2": 20,
            "better_thermostat_extension_enabled": True,
            "external_heat_entities": ["climate.heat_pump", "binary_sensor.fire"],
            "stove_temperature_entity": "sensor.stove",
            "stove_on_temperature": 25,
            "stove_off_temperature": 24,
        },
        set(),
    )
    states = {
        "climate.heat_pump": ("heat", {"hvac_action": "heating"}),
        "binary_sensor.fire": ("off", {}),
        "sensor.stove": ("24.5", {}),
    }
    active, sources, stove = model.evaluate_external_heat(room, states.get, False)
    assert (active, sources, stove) == (True, ["climate.heat_pump"], False)
    states["climate.heat_pump"] = ("heat", {"hvac_action": "idle"})
    states["sensor.stove"] = ("25.5", {})
    active, sources, stove = model.evaluate_external_heat(room, states.get, False)
    assert (active, sources, stove) == (True, ["sensor.stove"], True)
    states["sensor.stove"] = ("24.5", {})
    assert model.evaluate_external_heat(room, states.get, True)[0] is True
    states["sensor.stove"] = ("23.5", {})
    assert model.evaluate_external_heat(room, states.get, True)[0] is False
    states["binary_sensor.fire"] = ("unavailable", {})
    assert model.evaluate_external_heat(room, states.get, False)[0] is None
    plain = model.room_from_dict(
        {"name": "Kontor", "climate_entity": "climate.office", "rated_power_w": 900, "area_m2": 9},
        set(),
    )
    assert model.evaluate_external_heat(plain, states.get, False) == (False, [], False)


def test_wind_speed_units():
    assert model.wind_speed_ms(36.0, "km/h") == 10.0
    assert round(model.wind_speed_ms(10.0, "mph"), 3) == 4.470
    assert model.wind_speed_ms(5.0, "m/s") == 5.0
    assert model.wind_speed_ms(5.0, None) == 5.0
    assert round(model.wind_speed_ms(4.0, "Beaufort"), 2) == 6.69


def test_demand_model_round_trip_and_merge():
    demand = model.DemandModel()
    demand.add(BASE, "2026-09-20", 1.0, 250.0, 10.0, 4.0, True)
    demand.add(BASE, "2026-09-20", 0.5, 0.0, 10.0, None, False)
    demand.status = "normal"
    restored = model.DemandModel.from_dict(demand.to_dict())
    assert restored.status == "normal"
    assert restored.days["2026-09-20"] == demand.days["2026-09-20"]
    assert restored.hours[BASE] == demand.hours[BASE]
    restored.merge(demand)
    assert restored.days["2026-09-20"].energy_wh == 500.0
    assert restored.days["2026-09-20"].mean_wind == 4.0


def test_from_dict_ignores_damaged_storage():
    restored = model.DemandModel.from_dict(
        {"status": "odd", "hours": {"x": [1.0]}, "days": {"2026-09-20": "bad"}}
    )
    assert restored.status == "learning"
    assert not restored.hours
    assert restored.days["2026-09-20"] == model.DemandTotals()


def test_prune_keeps_the_window_and_the_newest_days():
    demand = model.DemandModel()
    newest = date(2026, 9, 25)
    for day in range(50):
        key = (newest - timedelta(days=day)).isoformat()
        demand.add(BASE - day * 24 * HOUR, key, 1.0, 10.0, 5.0, None, True)
    demand.prune(BASE, 48, 45)
    assert len(demand.days) == 45
    assert min(demand.days) == (newest - timedelta(days=44)).isoformat()
    assert all(key >= BASE - 48 * HOUR for key in demand.hours)


def test_step_series_forward_fills():
    series = model.StepSeries([(20.0, "b"), (10.0, "a")])
    assert series.at(5.0) is None
    assert series.at(10.0) == "a"
    assert series.at(15.0) == "a"
    assert series.at(25.0) == "b"


def test_demand_sample_needs_valve_and_temperatures():
    assert model.demand_sample(1000, False, None, 50.0, 21.0, 5.0) is None
    power, lift = model.demand_sample(1000, False, 50.0, 50.0, 21.0, 5.0)
    assert power > 0
    assert lift == 16.0
