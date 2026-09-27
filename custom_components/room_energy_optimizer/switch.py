"""Switch for optional radiator-stress notifications."""

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .entity import OptimizerEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([RadiatorAlertSwitch(runtime)])


class RadiatorAlertSwitch(OptimizerEntity, SwitchEntity):
    _attr_translation_key = "radiator_stress_notifications"
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "radiator_stress_notifications")

    @property
    def available(self) -> bool:
        return bool(self.runtime.alert_notify_entity)

    @property
    def is_on(self) -> bool:
        return self.runtime.alert_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.runtime.async_set_alert_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.runtime.async_set_alert_enabled(False)
