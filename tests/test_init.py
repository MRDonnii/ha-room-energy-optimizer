"""Home Assistant tests for the heat demand runtime (model v3)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.room_energy_optimizer.const import DOMAIN

ROOM = {
    "name": "Kontor",
    "climate_entity": "climate.office",
    "rated_power_w": 1000,
    "area_m2": 10,
    "radiator_count": 1,
    "initial_valve_hours": 0,
    "better_thermostat_extension_enabled": False,
    "external_heat_entities": [],
    "stove_temperature_entity": "",
    "stove_on_temperature": 25,
    "stove_off_temperature": 24,
    "system_type_override": "",
}


def options(**extra):
    return {
        "system_type": "two_pipe",
        "flow_temperature_entity": "sensor.flow",
        "outdoor_temperature_entity": "sensor.outdoor",
        "wind_speed_entity": "sensor.wind",
        "monthly_cost_entity": "",
        "monthly_cost_baseline_entity": "",
        "loop_order": "",
        "loop_drop_per_station_c": 2,
        "rooms": [ROOM],
        **extra,
    }


def set_climate(hass: HomeAssistant, valve: float, *, window_open: bool = False) -> None:
    hass.states.async_set(
        "climate.office",
        "heat",
        {
            "current_temperature": 21.0,
            "temperature": 21.0,
            "hvac_action": "heating" if valve else "idle",
            "window_open": window_open,
            "calibration_balance": {"climate.office_trv": {"valve%": valve}},
        },
    )


def set_weather(hass: HomeAssistant, outdoor: str = "5.0") -> None:
    hass.states.async_set("sensor.flow", "45.0")
    hass.states.async_set("sensor.outdoor", outdoor)
    hass.states.async_set("sensor.wind", "18", {"unit_of_measurement": "km/h"})


async def setup_entry(hass: HomeAssistant, **extra) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="main", options=options(**extra))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_alert_controls_persist(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 100)
    entry = await setup_entry(hass, alert_notify_entity="notify.test")
    registry = er.async_get(hass)
    switch_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_radiator_stress_notifications"
    )
    number_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{entry.entry_id}_radiator_alert_observation_time"
    )
    assert switch_id and number_id
    assert hass.states.get(switch_id).state == "off"
    assert float(hass.states.get(number_id).state) == 60
    await hass.services.async_call(
        "number", "set_value", {"value": 45}, target={"entity_id": number_id}, blocking=True
    )
    await hass.services.async_call(
        "switch", "turn_on", target={"entity_id": switch_id}, blocking=True
    )
    assert float(hass.states.get(number_id).state) == 45
    assert hass.states.get(switch_id).state == "on"
    assert hass.states.get("binary_sensor.kontor_radiator_stressed") is not None
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert float(hass.states.get(number_id).state) == 45
    assert hass.states.get(switch_id).state == "on"


async def test_learns_the_recent_window_live(hass: HomeAssistant, freezer) -> None:
    set_weather(hass)
    set_climate(hass, 50)
    await setup_entry(hass)

    status = hass.states.get("sensor.kontor_heat_demand_status")
    assert status.state == "learning"
    assert status.attributes["reason"] == "collecting_days"
    assert status.attributes["method"] == "energy_signature"
    assert hass.states.get("sensor.kontor_heat_demand_per_degree").state == "unavailable"

    for _ in range(12 * 30):
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    status = hass.states.get("sensor.kontor_heat_demand_status")
    assert status.attributes["recent_observation_hours"] == pytest.approx(30.0, abs=0.2)
    assert status.attributes["recent_mean_lift_c"] == 16.0
    assert status.attributes["recent_mean_wind_ms"] == 5.0
    per_degree = float(hass.states.get("sensor.kontor_heat_demand_per_degree").state)
    assert per_degree > 0


async def test_open_window_is_left_out(hass: HomeAssistant, freezer) -> None:
    set_weather(hass)
    set_climate(hass, 100, window_open=True)
    await setup_entry(hass)
    for _ in range(12 * 3):
        freezer.tick(timedelta(minutes=5))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    status = hass.states.get("sensor.kontor_heat_demand_status")
    assert status.attributes["recent_observation_hours"] == 0
    assert status.attributes["recent_excluded_hours"] == pytest.approx(3.0, abs=0.1)


async def test_old_storage_keeps_valve_hours(hass: HomeAssistant, hass_storage) -> None:
    set_weather(hass)
    set_climate(hass, 0)
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="main", options=options())
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "heat_demand_model_version": 2,
            "month": dt_util.now().strftime("%Y-%m"),
            "hours": {"kontor": 5.0},
            "baseline": {
                "kontor": {"ratio": 3.0, "hours": 60, "recent_ratio": 13, "recent_hours": 60}
            },
        },
    }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kontor_valve_hours_this_month").state == "5.0"
    status = hass.states.get("sensor.kontor_heat_demand_status")
    assert status.state == "learning"
    assert status.attributes["learned_baseline_w_per_degree"] is None


async def test_missing_outdoor_temperature_is_a_data_problem(hass: HomeAssistant) -> None:
    set_weather(hass, outdoor="unavailable")
    set_climate(hass, 20)
    entry = await setup_entry(hass)
    entity_id = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_data_problem"
    )
    problem = hass.states.get(entity_id)
    assert problem.state == "on"
    assert problem.attributes["unavailable_weather_inputs"] == ["sensor.outdoor"]


async def test_wind_setting_must_be_a_sensor(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "name": "Test",
            "system_type": "two_pipe",
            "flow_temperature_entity": "sensor.flow",
            "outdoor_temperature_entity": "sensor.outdoor",
            "wind_speed_entity": "light.kitchen",
        },
    )
    assert result["errors"] == {"wind_speed_entity": "invalid_sensor"}


async def test_history_is_rebuilt_from_the_recorder(recorder_mock, hass: HomeAssistant, freezer):
    from pytest_homeassistant_custom_component.components.recorder.common import (
        async_wait_recording_done,
    )

    now = dt_util.utcnow().replace(minute=30, second=0, microsecond=0)
    # Start a little before the replayed window, as real sensors always have
    # a state from before it.
    freezer.move_to(now - timedelta(days=10, hours=2))
    set_weather(hass)
    for hour in range(10 * 24 + 2):
        # One hour on at 60 %, one hour closed: a steady duty cycle.
        set_climate(hass, 60 if hour % 2 == 0 else 0)
        await hass.async_block_till_done()
        freezer.tick(timedelta(hours=1))
    await async_wait_recording_done(hass)

    freezer.move_to(now)
    await setup_entry(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    status = hass.states.get("sensor.kontor_heat_demand_status")
    assert status.attributes["valid_days"] >= 7
    assert status.attributes["compared_days"] >= 5
    assert status.state == "normal"
    assert status.attributes["current_w_per_degree"] == pytest.approx(
        status.attributes["learned_baseline_w_per_degree"], rel=0.1
    )


async def test_room_devices_link_to_the_hub(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 0)
    entry = await setup_entry(hass)
    registry = dr.async_get(hass)
    hub = registry.async_get_device(identifiers={(DOMAIN, entry.entry_id)})
    room = registry.async_get_device(identifiers={(DOMAIN, f"{entry.entry_id}_kontor")})
    assert hub is not None
    assert room.via_device_id == hub.id


def add_leftover(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str, **extra):
    return er.async_get(hass).async_get_or_create(
        domain, DOMAIN, f"{entry.entry_id}_{key}", config_entry=entry, **extra
    )


async def test_entities_older_versions_left_behind_are_removed(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 50)
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="main", options=options())
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    stale = [
        add_leftover(hass, entry, "binary_sensor", "kontor_external_heat"),
        add_leftover(hass, entry, "binary_sensor", "kontor_opening_contact"),
        add_leftover(hass, entry, "sensor", "kontor_experimental_cascade_power"),
    ]
    hidden = add_leftover(
        hass,
        entry,
        "binary_sensor",
        "kontor_external_heat_hidden",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    current = add_leftover(hass, entry, "sensor", "kontor_power")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    for leftover in stale:
        assert registry.async_get(leftover.entity_id) is None
        assert hass.states.get(leftover.entity_id) is None
    assert registry.async_get(hidden.entity_id) is not None
    assert registry.async_get(current.entity_id) is not None
    assert not hass.states.get(current.entity_id).attributes.get("restored")


async def test_leftovers_stay_when_a_platform_fails_to_set_up(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 50)
    entry = MockConfigEntry(domain=DOMAIN, title="Test", unique_id="main", options=options())
    entry.add_to_hass(hass)
    leftover = add_leftover(hass, entry, "binary_sensor", "kontor_external_heat")

    with patch(
        "custom_components.room_energy_optimizer.sensor.async_setup_entry",
        side_effect=RuntimeError("platform failed"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert er.async_get(hass).async_get(leftover.entity_id) is not None


async def test_entities_for_bt_and_cascade_rooms_are_kept(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 50)
    room = {**ROOM, "better_thermostat_extension_enabled": True}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test",
        unique_id="main",
        options=options(system_type="one_pipe", loop_order="Kontor|kontor", rooms=[room]),
    )
    entry.add_to_hass(hass)
    kept = [
        add_leftover(hass, entry, "binary_sensor", "kontor_external_heat"),
        add_leftover(hass, entry, "binary_sensor", "kontor_opening_contact"),
        add_leftover(hass, entry, "sensor", "kontor_experimental_cascade_power"),
    ]

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    for registered in kept:
        assert registry.async_get(registered.entity_id) is not None
        assert not hass.states.get(registered.entity_id).attributes.get("restored")


async def test_entities_of_a_removed_room_are_removed(hass: HomeAssistant) -> None:
    set_weather(hass)
    set_climate(hass, 50)
    living = {**ROOM, "name": "Stue", "climate_entity": "climate.living"}
    entry = await setup_entry(hass, rooms=[ROOM, living])
    registry = er.async_get(hass)
    valve = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_stue_valve")
    assert valve is not None

    hass.config_entries.async_update_entry(entry, options=options(rooms=[ROOM]))
    await hass.async_block_till_done()

    assert registry.async_get(valve) is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_kontor_valve")


async def test_phone_alert_goes_through_mobile_app_with_icon(hass: HomeAssistant) -> None:
    """A phone's notify entity is sent through notify.mobile_app_* so it can carry an icon."""
    set_weather(hass)
    set_climate(hass, 100)
    phone = MockConfigEntry(domain="mobile_app", title="JTH-iPhone")
    phone.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=phone.entry_id, identifiers={("mobile_app", "phone")}, name="JTH-iPhone"
    )
    er.async_get(hass).async_get_or_create(
        "notify", "mobile_app", "phone", suggested_object_id="jth_iphone", device_id=device.id
    )
    calls = []
    hass.services.async_register("notify", "mobile_app_jth_iphone", lambda call: calls.append(call))
    entry = await setup_entry(hass, alert_notify_entity="notify.jth_iphone")
    runtime = hass.data[DOMAIN][entry.entry_id]
    assert runtime._mobile_app_service("notify.jth_iphone") == "mobile_app_jth_iphone"
    assert runtime._mobile_app_service("notify.test") is None
