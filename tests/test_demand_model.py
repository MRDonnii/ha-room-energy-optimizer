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


def transition():
    return model.SetpointTransition(0.5, 0.3, 12.0, 2.0)


def test_setpoint_transition_starts_on_a_real_change_only():
    t = transition()
    assert t.update(BASE, 21.0, 21.0) is False  # the first setpoint is the reference
    assert t.update(BASE + HOUR, 21.3, 21.0) is False  # a small step is no transition
    assert t.active is False
    assert t.update(BASE + 2 * HOUR, 21.6, 21.0) is True  # small steps add up (0.6 °C)
    assert t.active is True


def test_setpoint_transition_lasts_until_reached_plus_tail():
    t = transition()
    t.update(BASE, 20.0, 20.0)
    assert t.update(BASE + HOUR, 22.0, 20.1) is True
    assert t.update(BASE + 3 * HOUR, 22.0, 21.5) is True  # still heating up
    assert t.update(BASE + 4 * HOUR, 22.0, 21.8) is True  # reached (within 0.3 °C), tail starts
    assert t.update(BASE + 5 * HOUR, 22.0, 22.0) is True  # in the 2 h tail
    assert t.update(BASE + 6 * HOUR, 22.0, 22.0) is False  # done
    assert t.active is False


def test_setpoint_transition_works_downwards_and_is_capped():
    t = transition()
    t.update(BASE, 22.0, 22.0)
    assert t.update(BASE + HOUR, 18.0, 22.0) is True
    # Never reaches 18 °C: after 12 h it counts as settled, then the 2 h tail.
    assert t.update(BASE + 12 * HOUR, 18.0, 20.5) is True
    assert t.update(BASE + 13 * HOUR, 18.0, 20.4) is True
    assert t.update(BASE + 15 * HOUR, 18.0, 20.3) is False


def test_setpoint_transition_restarts_on_a_new_change():
    t = transition()
    t.update(BASE, 20.0, 20.0)
    t.update(BASE + HOUR, 22.0, 20.0)
    t.update(BASE + 3 * HOUR, 22.0, 22.0)  # reached, tail running
    assert t.update(BASE + 4 * HOUR, 20.0, 22.0) is True  # back down: a new transition
    assert t.since == BASE + 4 * HOUR and t.settled_at is None


def test_setpoint_transition_ignores_missing_values_and_round_trips():
    t = transition()
    t.update(BASE, 20.0, 20.0)
    t.update(BASE + HOUR, 22.0, None)
    assert t.update(BASE + 2 * HOUR, None, None) is True  # unavailable keeps the state
    copy = transition()
    copy.restore(t.to_list())
    assert copy.to_list() == t.to_list() and copy.active
    damaged = transition()
    damaged.restore(["x", 1, 2])
    damaged.restore({"target": 1})
    assert damaged.to_list() == [None, None, None]


def test_setpoint_and_temperature_reads_a_climate():
    assert model.setpoint_and_temperature({"temperature": "22", "current_temperature": 21.5}) == (
        22.0,
        21.5,
    )
    assert model.setpoint_and_temperature({"temperature": None}) == (None, None)


def test_days_with_other_heat_are_not_compared_with_days_without():
    """A stove day needs less radiator heat; a day without fire is compared with its kind."""
    days = [model.DemandDay(10.0, 8.0, None, 0.3) for _ in range(7)] + [
        model.DemandDay(20.0, 8.0, None, 0.0) for _ in range(6)
    ]
    options = dict(
        min_days=7, max_lift_diff=3.0, wind_scale=2.0, min_similar=5, max_similar=10,
        min_relative_spread=0.1, min_spread_w=5.0, max_share_diff=0.15, share_scale=0.1,
    )
    no_fire = model.learn_demand_baseline(days, 8.0, None, excluded_share=0.0, **options)
    assert no_fire.expected == 20.0 and no_fire.share_range == (0.0, 0.0)
    fire = model.learn_demand_baseline(days, 8.0, None, excluded_share=0.3, **options)
    assert fire.expected == 10.0
    # Weather like it but conditions never seen: not judged, and the reason can tell.
    odd = model.learn_demand_baseline(days, 8.0, None, excluded_share=0.7, **options)
    assert odd.expected is None and odd.weather_compared == 13


def test_a_few_watts_on_an_idle_radiator_is_not_a_deviation():
    """30 W more in a room that normally needs ~0 W was +400 % but means nothing."""
    days = [model.DemandDay(0.1 * (i % 3), 11.0, None, 0.0) for i in range(10)]
    options = dict(
        min_days=7, max_lift_diff=3.0, wind_scale=2.0, min_similar=5, max_similar=10,
        min_relative_spread=0.1,
    )
    old = model.learn_demand_baseline(days, 11.0, None, min_spread_w=5.0, **options)
    new = model.learn_demand_baseline(days, 11.0, None, min_spread_w=60.0, **options)
    recent = 30.0 / 11.0
    assert classify(recent, old)[0] == "deviating"
    assert classify(recent, new)[0] == "normal"
    # A radiator suddenly running 600 W (window ajar, stuck valve) is still caught.
    assert classify(600.0 / 11.0, new)[0] == "deviating"


def confirm(raw, previous, pending, now):
    return model.confirm_status(
        raw, previous, pending, now, enter_seconds=12 * HOUR, exit_seconds=3 * HOUR
    )


def test_deviating_must_last_twelve_hours():
    status, pending = confirm("deviating", "normal", None, BASE)
    assert status == "normal" and pending == ("deviating", BASE)
    status, pending = confirm("deviating", status, pending, BASE + 11 * HOUR)
    assert status == "normal"
    status, pending = confirm("deviating", status, pending, BASE + 12 * HOUR)
    assert status == "deviating" and pending is None


def test_an_interrupted_deviation_starts_over():
    status, pending = confirm("deviating", "normal", None, BASE)
    status, pending = confirm("normal", status, pending, BASE + 6 * HOUR)
    assert status == "normal" and pending is None
    status, pending = confirm("deviating", status, pending, BASE + 7 * HOUR)
    status, pending = confirm("deviating", status, pending, BASE + 18 * HOUR)
    assert status == "normal"  # only 11 h since it came back
    assert confirm("deviating", status, pending, BASE + 19 * HOUR)[0] == "deviating"


def test_deviating_clears_after_three_hours_and_learning_is_immediate():
    status, pending = confirm("normal", "deviating", None, BASE)
    assert status == "deviating"
    status, pending = confirm("normal", status, pending, BASE + 3 * HOUR)
    assert status == "normal" and pending is None
    assert confirm("learning", "normal", None, BASE) == ("learning", None)
    assert confirm("normal", "learning", None, BASE) == ("normal", None)
    # From learning straight to a deviation still needs the twelve hours.
    assert confirm("deviating", "learning", None, BASE) == ("normal", ("deviating", BASE))


def test_pending_status_survives_storage():
    m = model.DemandModel()
    m.status, m.pending = "normal", ("deviating", float(BASE))
    copy = model.DemandModel.from_dict(m.to_dict())
    assert copy.pending == ("deviating", float(BASE))
    damaged = model.DemandModel.from_dict({"status": "normal", "pending": ["x", "y"]})
    assert damaged.pending is None
