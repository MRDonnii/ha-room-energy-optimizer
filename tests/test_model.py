"""Tests for calculations that do not need Home Assistant."""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components/room_energy_optimizer/model.py"
SPEC = spec_from_file_location("room_energy_optimizer_model", PATH)
model = module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = model
SPEC.loader.exec_module(model)


def test_parse_rooms_and_danish_slug():
    rooms = model.parse_rooms("Køkken|climate.kitchen|1129|18,5")
    assert rooms[0].slug == "koekken"
    assert rooms[0].rated_power_w == 1129
    assert rooms[0].area_m2 == 18.5


def test_parse_rooms_accepts_migration_seed():
    rooms = model.parse_rooms("Living room|climate.living_room|2000|30|12,45")
    assert rooms[0].initial_valve_hours == 12.45


def test_parse_rooms_rejects_bad_entity():
    try:
        model.parse_rooms("Kitchen|sensor.temperature|1000|20")
    except ValueError as err:
        assert "climate." in str(err)
    else:
        raise AssertionError("invalid room accepted")


def test_valve_percentage_averages_and_clamps():
    attributes = {
        "calibration_balance": {
            "climate.one": {"valve%": 20},
            "climate.two": {"valve%": 140},
        }
    }
    assert model.valve_percentage(attributes) == 60


def test_valve_percentage_missing_is_not_zero():
    assert model.valve_percentage({}) is None


def test_valve_percentage_accepts_json_attribute():
    attributes = {
        "calibration_balance": ('{"climate.one":{"valve%":20},"climate.two":{"valve%":60}}')
    }
    assert model.valve_percentage(attributes) == 40


def test_one_pipe_reference_power():
    value = model.estimated_power(1000, 50, 70, 20, True)
    assert value is not None
    assert round(value) == 500


def test_no_temperature_lift_means_no_power():
    assert model.estimated_power(1000, 100, 20, 21, True) == 0


def test_heat_demand_ratio_normalises_by_lift():
    assert model.heat_demand_ratio(600, 21, 11) == 60


def test_heat_demand_ratio_rejects_small_lift():
    assert model.heat_demand_ratio(600, 21, 20) is None


def test_update_ema_seeds_from_first_sample():
    assert model.update_ema(None, 42.0, 1.0, 24.0) == 42.0


def test_update_ema_moves_toward_sample_over_time():
    value = model.update_ema(10.0, 20.0, 24.0, 24.0)
    assert 14.5 < value < 15.5


def test_update_ema_barely_moves_for_short_elapsed_time():
    value = model.update_ema(10.0, 20.0, 0.01, 120.0)
    assert 10.0 < value < 10.1


def test_classify_heat_demand_learning_before_enough_hours():
    assert model.classify_heat_demand(60.0, 55.0, 10.0, 48.0, 0.4) == "learning"


def test_classify_heat_demand_learning_without_baseline():
    assert model.classify_heat_demand(60.0, None, 100.0, 48.0, 0.4) == "learning"


def test_classify_heat_demand_normal_within_threshold():
    assert model.classify_heat_demand(60.0, 50.0, 100.0, 48.0, 0.4) == "normal"


def test_classify_heat_demand_deviating_beyond_threshold():
    assert model.classify_heat_demand(90.0, 50.0, 100.0, 48.0, 0.4) == "deviating"


def test_room_from_dict_wizard_submission():
    room = model.room_from_dict(
        {
            "name": "Køkken",
            "climate_entity": "climate.kitchen",
            "rated_power_w": 1129,
            "area_m2": "18,5",
            "radiator_count": 2,
        },
        existing_slugs=set(),
    )
    assert room.slug == "koekken"
    assert room.radiator_count == 2
    assert room.initial_valve_hours == 0.0


def test_room_from_dict_rejects_duplicate_slug():
    try:
        model.room_from_dict(
            {"name": "Stue", "climate_entity": "climate.stue", "rated_power_w": 1000, "area_m2": 20},
            existing_slugs={"stue"},
        )
    except ValueError as err:
        assert "duplicate" in str(err)
    else:
        raise AssertionError("duplicate room name accepted")


def test_room_to_dict_round_trips_through_room_from_dict():
    original = model.RoomConfig("Stue", "stue", "climate.stue", 5193.0, 44.0, 3, 1.5)
    data = model.room_to_dict(original)
    rebuilt = model.room_from_dict(data, existing_slugs=set())
    assert rebuilt == original


def test_rooms_from_options_accepts_legacy_string():
    rooms = model.rooms_from_options("Stue|climate.stue|5193|44")
    assert rooms[0].name == "Stue"
    assert rooms[0].radiator_count == 1


def test_rooms_from_options_accepts_wizard_list():
    rooms = model.rooms_from_options(
        [
            {
                "name": "Stue",
                "climate_entity": "climate.stue",
                "rated_power_w": 5193,
                "area_m2": 44,
                "radiator_count": 3,
            }
        ]
    )
    assert rooms[0].radiator_count == 3


def test_rooms_from_options_rejects_empty_list():
    try:
        model.rooms_from_options([])
    except ValueError as err:
        assert "at least one room" in str(err)
    else:
        raise AssertionError("empty room list accepted")
