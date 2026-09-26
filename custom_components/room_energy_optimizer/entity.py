"""Shared entity base."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, VERSION

# Home Assistant 2026.8 links a device to its parent by registry id and
# deprecates the identifier tuple; older versions only know the tuple.
_VIA_DEVICE_ID = "via_device_id" in DeviceInfo.__annotations__


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
                sw_version=VERSION,
            )
            if _VIA_DEVICE_ID and runtime.hub_device_id:
                self._attr_device_info["via_device_id"] = runtime.hub_device_id
            else:
                self._attr_device_info["via_device"] = (DOMAIN, runtime.entry.entry_id)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.runtime.add_listener(self.async_write_ha_state))
