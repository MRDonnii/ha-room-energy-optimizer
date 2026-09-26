"""Diagnostics without personal state values."""

from .const import DOMAIN, VERSION


async def async_get_config_entry_diagnostics(hass, entry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    return {
        "version": VERSION,
        "system_type": entry.options.get("system_type"),
        "loop_order": entry.options.get("loop_order"),
        "outdoor_temperature_configured": bool(entry.options.get("outdoor_temperature_entity")),
        "wind_speed_configured": bool(entry.options.get("wind_speed_entity")),
        "room_count": len(runtime.rooms),
        "rooms": [
            {
                "slug": room.slug,
                "rated_power_w": room.rated_power_w,
                "area_m2": room.area_m2,
                "system_type_override": room.system_type_override or None,
                "valve_data_available": runtime.valves[room.slug] is not None,
                "heat_demand_status": getattr(runtime.demand_views.get(room.slug), "status", None),
                "heat_demand_reason": getattr(runtime.demand_views.get(room.slug), "reason", None),
                "heat_demand_valid_days": getattr(
                    getattr(runtime.demand_views.get(room.slug), "baseline", None), "days", 0
                ),
                "heat_demand_stored_days": len(runtime.demand[room.slug].days),
            }
            for room in runtime.rooms
        ],
    }
