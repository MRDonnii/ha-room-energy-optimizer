"""Shared entity base."""

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN, VERSION


class OptimizerEntity(Entity):
    """Base entity tied to one config entry.

    Entry-level entities (totals, data health) stay on the shared hub
    device. Passing `room` instead puts the entity on its own per-room
    device, linked back to the hub via `via_device`, so each room gets its
    own page under Settings -> Devices & services.
    """

    _attr_has_entity_name = True

    def __init__(self, runtime, key: str, room=None) -> None:
        self.runtime = runtime
        self._attr_unique_id = f"{runtime.entry.entry_id}_{key}"
        if room is None:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, runtime.entry.entry_id)},
                name=f"{runtime.entry.title} (Totals)",
                manufacturer="Room Energy Optimizer",
                model="Local hydronic estimator",
                sw_version=VERSION,
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{runtime.entry.entry_id}_{room.slug}")},
                name=room.name,
                manufacturer="Room Energy Optimizer",
                model="Room estimator",
                via_device=(DOMAIN, runtime.entry.entry_id),
                sw_version=VERSION,
            )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))
