"""Room Energy Optimizer integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_FLOW_TEMPERATURE,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_ROOMS,
    CONF_SYSTEM_TYPE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HEAT_DEMAND_BASELINE_HALF_LIFE_HOURS,
    HEAT_DEMAND_MIN_DELTA,
    HEAT_DEMAND_RECENT_HALF_LIFE_HOURS,
    PLATFORMS,
    SYSTEM_ONE_PIPE,
)
from .model import (
    RoomConfig,
    estimated_power,
    heat_demand_ratio,
    room_to_dict,
    rooms_from_options,
    update_ema,
    valve_percentage,
)


class RuntimeData:
    """Shared, persistent runtime data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.rooms: list[RoomConfig] = rooms_from_options(entry.options.get(CONF_ROOMS, []))
        self.valves: dict[str, float | None] = {room.slug: None for room in self.rooms}
        self.hours: dict[str, float] = {room.slug: room.initial_valve_hours for room in self.rooms}
        # Weather-normalised heat-demand baseline (W per °C of indoor/outdoor
        # lift). `ratio_recent` is a fast EMA of the live ratio, `ratio_baseline`
        # a slow EMA that represents "normal" for that room, and
        # `baseline_hours` counts how many hours of valid samples fed it.
        # Unlike `hours`, these never reset on a month boundary.
        self.ratio_recent: dict[str, float | None] = {room.slug: None for room in self.rooms}
        self.ratio_baseline: dict[str, float | None] = {room.slug: None for room in self.rooms}
        self.baseline_hours: dict[str, float] = {room.slug: 0.0 for room in self.rooms}
        self.listeners: list[Any] = []
        self._last_sample: datetime | None = None
        self._month = dt_util.now().strftime("%Y-%m")
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True)
        self._unsub = None

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        if stored.get("month") == self._month:
            self.hours.update(
                {
                    key: float(value)
                    for key, value in stored.get("hours", {}).items()
                    if key in self.hours
                }
            )
        for slug, data in stored.get("baseline", {}).items():
            if slug not in self.ratio_baseline or not isinstance(data, dict):
                continue
            ratio = data.get("ratio")
            self.ratio_baseline[slug] = None if ratio is None else float(ratio)
            self.baseline_hours[slug] = float(data.get("hours", 0.0))
        await self.async_update()
        from datetime import timedelta

        self._unsub = async_track_time_interval(
            self.hass, self.async_update, timedelta(seconds=DEFAULT_SCAN_INTERVAL)
        )

    def _outdoor_temperature(self) -> float | None:
        entity_id = self.entry.options.get(CONF_OUTDOOR_TEMPERATURE, "")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _flow_temperature(self) -> float | None:
        entity_id = self.entry.options.get(CONF_FLOW_TEMPERATURE)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _update_heat_demand_baseline(
        self, room: RoomConfig, valve: float | None, elapsed_hours: float
    ) -> None:
        outdoor_temp = self._outdoor_temperature()
        flow_temp = self._flow_temperature()
        if valve is None or outdoor_temp is None or flow_temp is None:
            return
        state = self.hass.states.get(room.climate_entity)
        if state is None:
            return
        try:
            room_temp = float(state.attributes["current_temperature"])
            target_temp = float(state.attributes["temperature"])
        except (KeyError, TypeError, ValueError):
            return
        one_pipe = self.entry.options.get(CONF_SYSTEM_TYPE) == SYSTEM_ONE_PIPE
        power = estimated_power(room.rated_power_w, valve, flow_temp, room_temp, one_pipe)
        if power is None:
            return
        ratio = heat_demand_ratio(power, target_temp, outdoor_temp, HEAT_DEMAND_MIN_DELTA)
        if ratio is None:
            return
        self.ratio_recent[room.slug] = update_ema(
            self.ratio_recent[room.slug], ratio, elapsed_hours, HEAT_DEMAND_RECENT_HALF_LIFE_HOURS
        )
        self.ratio_baseline[room.slug] = update_ema(
            self.ratio_baseline[room.slug],
            ratio,
            elapsed_hours,
            HEAT_DEMAND_BASELINE_HALF_LIFE_HOURS,
        )
        self.baseline_hours[room.slug] += elapsed_hours

    async def async_update(self, _now: datetime | None = None) -> None:
        now = dt_util.now()
        month = now.strftime("%Y-%m")
        if month != self._month:
            self._month = month
            self.hours = {room.slug: 0.0 for room in self.rooms}
            self._last_sample = None
        elapsed_hours = 0.0
        if self._last_sample is not None:
            elapsed_hours = min(300.0, max(0.0, (now - self._last_sample).total_seconds())) / 3600.0
        for room in self.rooms:
            state = self.hass.states.get(room.climate_entity)
            current = None if state is None else valve_percentage(state.attributes)
            previous = self.valves.get(room.slug)
            if previous is not None and elapsed_hours:
                self.hours[room.slug] += previous / 100.0 * elapsed_hours
            self.valves[room.slug] = current
            self._update_heat_demand_baseline(room, current, elapsed_hours)
        self._last_sample = now
        self._store.async_delay_save(self._data_to_save, 300)
        for listener in list(self.listeners):
            listener()

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "month": self._month,
            "hours": self.hours,
            "baseline": {
                room.slug: {
                    "ratio": self.ratio_baseline[room.slug],
                    "hours": self.baseline_hours[room.slug],
                }
                for room in self.rooms
            },
        }

    def add_listener(self, listener: Any) -> Any:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener) if listener in self.listeners else None

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
        await self._store.async_save(self._data_to_save())


async def _async_migrate_room_storage(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """One-time upgrade from the pre-1.4.0 pipe-delimited rooms string.

    Runs before the update listener is registered, so this does not trigger
    a self-inflicted reload. Existing valve-hours and heat-demand baselines
    are keyed by room slug and are unaffected by the storage format change.
    """
    raw = entry.options.get(CONF_ROOMS, [])
    if not isinstance(raw, str):
        return
    rooms = rooms_from_options(raw)
    new_options = {**entry.options, CONF_ROOMS: [room_to_dict(room) for room in rooms]}
    hass.config_entries.async_update_entry(entry, options=new_options)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_migrate_room_storage(hass, entry)
    runtime = RuntimeData(hass, entry)
    await runtime.async_start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await hass.data[DOMAIN].pop(entry.entry_id).async_stop()
    return unloaded
