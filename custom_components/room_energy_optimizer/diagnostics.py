"""Diagnostics without personal state values."""

from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    return {
        "version": "1.0.0",
        "system_type": entry.options.get("system_type"),
        "room_count": len(runtime.rooms),
        "rooms": [
            {
                "slug": room.slug,
                "rated_power_w": room.rated_power_w,
                "area_m2": room.area_m2,
                "valve_data_available": runtime.valves[room.slug] is not None,
            }
            for room in runtime.rooms
        ],
    }
