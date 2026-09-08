"""Diagnostics without personal state values."""

from .const import DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    return {
        "version": VERSION,
        "system_type": entry.options.get("system_type"),
        "outdoor_temperature_configured": bool(entry.options.get("outdoor_temperature_entity")),
        "room_count": len(runtime.rooms),
        "rooms": [
            {
                "slug": room.slug,
                "rated_power_w": room.rated_power_w,
                "area_m2": room.area_m2,
                "valve_data_available": runtime.valves[room.slug] is not None,
                "heat_demand_baseline_hours": round(runtime.baseline_hours[room.slug], 1),
            }
            for room in runtime.rooms
        ],
    }
