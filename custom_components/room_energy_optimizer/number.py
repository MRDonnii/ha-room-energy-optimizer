"""Adjust the radiator-alert observation period."""

from homeassistant.components.number import NumberEntity, NumberMode

from .const import DOMAIN
from .entity import OptimizerEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RadiatorAlertObservationTime(runtime)])


class RadiatorAlertObservationTime(OptimizerEntity, NumberEntity):
    _attr_translation_key = "radiator_alert_observation_time"
    _attr_icon = "mdi:timer-sand"
    _attr_native_min_value = 1
    _attr_native_max_value = 1440
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "radiator_alert_observation_time")

    @property
    def native_value(self) -> float:
        return self.runtime.alert_minutes

    async def async_set_native_value(self, value: float) -> None:
        await self.runtime.async_set_alert_minutes(int(value))
