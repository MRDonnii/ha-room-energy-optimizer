"""Built-in Better Thermostat learning guard (1.x and 2.x trackers).

tests/bt_trackers is a copy of utils/thermal_learning.py from Better
Thermostat 1.9.3, tests/bt_trackers_v2 the same file from 2.0.0-Beta-1.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.climate import ClimateEntity, HVACAction, HVACMode
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import DATA_ENTITY_PLATFORM, EntityPlatform
import homeassistant.util.dt as dt_util
import pytest

from custom_components.room_energy_optimizer.bt_guard import (
    ATTR_GUARD,
    ATTR_PAUSED,
    LearningGuard,
)

from tests.bt_trackers import thermal_learning as v1
from tests.bt_trackers_v2 import thermal_learning as v2

T0 = datetime(2026, 10, 6, 10, 0, tzinfo=dt_util.UTC)
GUARD = "binary_sensor.stue_ekstern_varme_aktiv"


class FakeBT(ClimateEntity):
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_should_poll = False
    version = v1

    def __init__(self, name: str) -> None:
        self._attr_name = name
        self._attr_unique_id = f"bt_{name}"
        self._heating_tracker = self.version.HeatingPowerTracker()
        self._loss_tracker = self.version.HeatLossTracker()
        self.sample = (20.0, HVACAction.IDLE, T0)

    @property
    def extra_state_attributes(self):
        return {"heating_power": round(self._heating_tracker.heating_power, 4)}

    async def calculate_heating_power(self):
        temp, action, now = self.sample
        self._heating_tracker.update(temp, action, now, target_temp=22.0)

    async def calculate_heat_loss(self):
        temp, action, now = self.sample
        self._loss_tracker.update(temp, action, now)


class FakeBT2(FakeBT):
    version = v2

    async def calculate_heating_power(self):
        temp, action, now = self.sample
        self._heating_tracker.update(temp, action, now, heat_target_temperature=22.0)


async def _add_bt_platform(hass: HomeAssistant, entities: list) -> None:
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="climate",
        platform_name="better_thermostat",
        platform=None,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    await platform.async_add_entities(entities)
    hass.data.setdefault(DATA_ENTITY_PLATFORM, {}).setdefault("better_thermostat", []).append(
        platform
    )


async def _run_cycle(entity: FakeBT, start: datetime) -> None:
    seq = (
        [(20.0, HVACAction.IDLE)]
        + [(20.0 + i * 0.1, HVACAction.HEATING) for i in range(30)]
        + [(23.0 + 0.05 * i, HVACAction.IDLE) for i in range(10)]
        + [(23.4 - 0.05 * i, HVACAction.IDLE) for i in range(60)]
        + [(20.4, HVACAction.HEATING), (20.5, HVACAction.IDLE)]
    )
    for i, (temp, action) in enumerate(seq):
        entity.sample = (temp, action, start + timedelta(minutes=5 * i))
        await entity.calculate_heating_power()
        await entity.calculate_heat_loss()


@pytest.mark.parametrize("cls", [FakeBT, FakeBT2])
async def test_guard_pauses_and_resumes_learning(hass: HomeAssistant, cls) -> None:
    hass.states.async_set(GUARD, "on")
    stue, mads = cls("Stue"), cls("Mads")
    await _add_bt_platform(hass, [stue, mads])
    guard = LearningGuard(hass, lambda: {"climate.stue": GUARD, "climate.mads": None})
    guard.async_scan()
    await hass.async_block_till_done()

    state = hass.states.get("climate.stue")
    assert state.attributes[ATTR_PAUSED] is True
    assert state.attributes[ATTR_GUARD] == GUARD
    assert ATTR_PAUSED not in hass.states.get("climate.mads").attributes

    power0 = stue._heating_tracker.heating_power
    await _run_cycle(stue, T0)
    assert len(stue._heating_tracker.cycles) == 0
    assert len(stue._loss_tracker.cycles) == 0
    assert stue._heating_tracker.heating_power == power0

    await _run_cycle(mads, T0)
    assert len(mads._heating_tracker.cycles) == 1

    hass.states.async_set(GUARD, "off")
    await hass.async_block_till_done()
    assert hass.states.get("climate.stue").attributes[ATTR_PAUSED] is False
    await _run_cycle(stue, T0 + timedelta(days=1))
    assert len(stue._heating_tracker.cycles) == 1
    assert len(stue._loss_tracker.cycles) == 1

    guard.async_stop()
    await hass.async_block_till_done()
    stue.async_write_ha_state()
    assert ATTR_PAUSED not in hass.states.get("climate.stue").attributes
    assert "calculate_heating_power" not in stue.__dict__
    assert "_bt_learning_guard_original_attrs" not in cls.__dict__


async def test_already_guarded_entity_is_left_alone(hass: HomeAssistant) -> None:
    hass.states.async_set(GUARD, "on")
    stue = FakeBT2("Stue")
    await _add_bt_platform(hass, [stue])
    first = LearningGuard(hass, lambda: {"climate.stue": GUARD})
    second = LearningGuard(hass, lambda: {"climate.stue": GUARD})
    first.async_scan()
    second.async_scan()
    assert "climate.stue" in first._attached
    assert "climate.stue" not in second._attached
    second.async_stop()
    stue.async_write_ha_state()
    assert hass.states.get("climate.stue").attributes[ATTR_PAUSED] is True
    first.async_stop()


async def test_incompatible_better_thermostat_is_reported(hass: HomeAssistant, caplog) -> None:
    class Renamed(FakeBT2):
        def __init__(self, name):
            super().__init__(name)
            del self._loss_tracker
            self._loss_learner = v2.HeatLossTracker()

    hass.states.async_set(GUARD, "on")
    stue = Renamed("Stue")
    await _add_bt_platform(hass, [stue])
    guard = LearningGuard(hass, lambda: {"climate.stue": GUARD})
    guard.async_scan()
    assert ATTR_PAUSED not in hass.states.get("climate.stue").attributes
    assert "Cannot guard climate.stue" in caplog.text
