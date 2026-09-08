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
