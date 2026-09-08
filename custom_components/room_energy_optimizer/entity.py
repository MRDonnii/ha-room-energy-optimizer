"""Shared entity base."""

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN


class OptimizerEntity(Entity):
    """Base entity tied to one config entry."""

    _attr_has_entity_name = True

    def __init__(self, runtime, key: str) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, runtime.entry.entry_id)},
            name=runtime.entry.title,
            manufacturer="Room Energy Optimizer",
            model="Local hydronic estimator",
            sw_version="1.1.1",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))
