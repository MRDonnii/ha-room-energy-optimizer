"""Room Energy Optimizer integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_ROOMS, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .model import RoomConfig, parse_rooms, valve_percentage


class RuntimeData:
    """Shared, persistent runtime data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.rooms: list[RoomConfig] = parse_rooms(entry.options.get(CONF_ROOMS, ""))
        self.valves: dict[str, float | None] = {room.slug: None for room in self.rooms}
        self.hours: dict[str, float] = {room.slug: 0.0 for room in self.rooms}
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
        await self.async_update()
        from datetime import timedelta

        self._unsub = async_track_time_interval(
            self.hass, self.async_update, timedelta(seconds=DEFAULT_SCAN_INTERVAL)
        )

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
        self._last_sample = now
        self._store.async_delay_save(lambda: {"month": self._month, "hours": self.hours}, 300)
        for listener in list(self.listeners):
            listener()

    def add_listener(self, listener: Any) -> Any:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener) if listener in self.listeners else None

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
        await self._store.async_save({"month": self._month, "hours": self.hours})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
