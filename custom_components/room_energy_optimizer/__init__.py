"""Room Energy Optimizer integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alerts import StressPeriod, evaluate_stress
from .const import (
    CONF_ALERT_LANGUAGE,
    CONF_ALERT_NOTIFY_ENTITY,
    CONF_ALERT_OBSERVATION_MINUTES,
    CONF_FLOW_TEMPERATURE,
    CONF_LOOP_DROP_PER_STATION,
    CONF_LOOP_ORDER,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_ROOMS,
    CONF_SYSTEM_TYPE,
    CONF_WIND_SPEED,
    DEFAULT_ALERT_OBSERVATION_MINUTES,
    DEFAULT_LOOP_DROP_PER_STATION,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    HEAT_DEMAND_BACKFILL_DAYS,
    HEAT_DEMAND_EXCLUSION_TAIL_HOURS,
    HEAT_DEMAND_HISTORY_DAYS,
    HEAT_DEMAND_KEEP_DAYS,
    HEAT_DEMAND_MAX_SIMILAR_DAYS,
    HEAT_DEMAND_MIN_DAY_CLEAN_HOURS,
    HEAT_DEMAND_MIN_MEAN_LIFT,
    HEAT_DEMAND_MIN_RECENT_CLEAN_HOURS,
    HEAT_DEMAND_MIN_RELATIVE_SPREAD,
    HEAT_DEMAND_MIN_SIMILAR_DAYS,
    HEAT_DEMAND_MIN_SPREAD_W,
    HEAT_DEMAND_MIN_VALID_DAYS,
    HEAT_DEMAND_MODEL_VERSION,
    HEAT_DEMAND_RECENT_WINDOW_HOURS,
    HEAT_DEMAND_SIMILAR_MAX_LIFT_DIFF,
    HEAT_DEMAND_SIMILAR_WIND_SCALE_MS,
    HEAT_DEMAND_Z_ENTER,
    HEAT_DEMAND_Z_EXIT,
    PLATFORMS,
    SYSTEM_ONE_PIPE,
    VERSION,
)
from .model import (
    DemandBaseline,
    DemandDay,
    DemandModel,
    DemandTotals,
    ExclusionTail,
    RoomConfig,
    StepSeries,
    cascade_flow_temperature,
    classify_demand,
    contact_open,
    demand_sample,
    evaluate_external_heat,
    learn_demand_baseline,
    parse_loop_order,
    room_loop_positions,
    room_one_pipe,
    room_to_dict,
    rooms_from_options,
    valve_percentage,
    wind_speed_ms,
)

_LOGGER = logging.getLogger(__name__)

# Only these climate attributes are needed to replay history.
_REPLAY_ATTRIBUTES = (
    "calibration_balance",
    "current_temperature",
    "window_open",
    "door_open",
    "hvac_action",
)


@dataclass(frozen=True, slots=True)
class DemandView:
    """A room's evaluated heat demand, shared by its sensors."""

    status: str
    reason: str | None
    recent: DemandTotals
    recent_w_per_degree: float | None
    baseline: DemandBaseline
    z_score: float | None
    baseline_clean_hours: float


class RuntimeData:
    """Shared, persistent runtime data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.rooms: list[RoomConfig] = rooms_from_options(entry.options.get(CONF_ROOMS, []))
        # EXPERIMENTAL one-pipe cascade estimate - see model.cascade_flow_temperature.
        self.loop_stops = parse_loop_order(entry.options.get(CONF_LOOP_ORDER, "") or "")
        self.loop_drop_per_station_c = float(
            entry.options.get(CONF_LOOP_DROP_PER_STATION, DEFAULT_LOOP_DROP_PER_STATION)
            or DEFAULT_LOOP_DROP_PER_STATION
        )
        self.valves: dict[str, float | None] = {room.slug: None for room in self.rooms}
        self.hours: dict[str, float] = {room.slug: room.initial_valve_hours for room in self.rooms}
        # Weather-normalised heat demand (model v3): an hourly and daily energy
        # balance per room. Unlike `hours`, it never resets on a month boundary.
        self.demand: dict[str, DemandModel] = {room.slug: DemandModel() for room in self.rooms}
        self.demand_views: dict[str, DemandView] = {}
        self._tails = {
            room.slug: ExclusionTail(HEAT_DEMAND_EXCLUSION_TAIL_HOURS) for room in self.rooms
        }
        self.external_heat_active: dict[str, bool | None] = {room.slug: None for room in self.rooms}
        self.external_heat_sources: dict[str, list[str]] = {room.slug: [] for room in self.rooms}
        self.contact_open: dict[str, bool] = {room.slug: False for room in self.rooms}
        self._stove_active: dict[str, bool] = {room.slug: False for room in self.rooms}
        self.listeners: list[Any] = []
        # Registry id of the hub device the room devices link to.
        self.hub_device_id: str | None = None
        self._last_sample: datetime | None = None
        self._month = dt_util.now().strftime("%Y-%m")
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}", atomic_writes=True)
        self._unsub = None
        self.alert_notify_entity = entry.options.get(CONF_ALERT_NOTIFY_ENTITY, "")
        self.alert_minutes = int(
            entry.options.get(CONF_ALERT_OBSERVATION_MINUTES, DEFAULT_ALERT_OBSERVATION_MINUTES)
        )
        self.alert_enabled = False
        self._stress_periods: dict[str, StressPeriod | None] = {
            room.slug: None for room in self.rooms
        }

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        self.alert_enabled = bool(stored.get("alert_enabled", False))
        self.alert_minutes = int(stored.get("alert_minutes", self.alert_minutes))
        if stored.get("month") == self._month:
            self.hours.update(
                {
                    key: float(value)
                    for key, value in stored.get("hours", {}).items()
                    if key in self.hours
                }
            )
        # Models v1/v2 kept per-sample moving averages whose learned baseline
        # started from the very first sample. They are dropped once; the
        # energy-balance history is rebuilt from the recorder instead.
        # Configuration, valve-hours and all other persisted data are kept.
        if stored.get("heat_demand_model_version") == HEAT_DEMAND_MODEL_VERSION:
            for slug, data in stored.get("demand", {}).items():
                if slug in self.demand:
                    self.demand[slug] = DemandModel.from_dict(data)
        backfill_until = dt_util.utcnow()
        await self.async_update()
        self._unsub = async_track_time_interval(
            self.hass, self.async_update, timedelta(seconds=DEFAULT_SCAN_INTERVAL)
        )
        missing = [room for room in self.rooms if self.demand[room.slug].empty]
        if missing and self._outdoor_entity():
            self.entry.async_create_background_task(
                self.hass,
                self._async_backfill(missing, backfill_until),
                f"{DOMAIN} heat demand history",
            )

    def _outdoor_entity(self) -> str:
        return self.entry.options.get(CONF_OUTDOOR_TEMPERATURE, "") or ""

    def _wind_entity(self) -> str:
        return self.entry.options.get(CONF_WIND_SPEED, "") or ""

    def _outdoor_temperature(self) -> float | None:
        entity_id = self._outdoor_entity()
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def _wind_speed(self) -> float | None:
        entity_id = self._wind_entity()
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            return None
        return wind_speed_ms(value, state.attributes.get("unit_of_measurement"))

    def _flow_temperature(self) -> float | None:
        entity_id = self.entry.options.get(CONF_FLOW_TEMPERATURE)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    def experimental_cascade_flow_temperature(self, room: RoomConfig) -> float | None:
        """EXPERIMENTAL: this room's assumed local flow temperature on the
        one-pipe loop. None when the room has no configured loop position
        (e.g. a dedicated two-pipe branch, or the loop order is unset).
        """
        positions = room_loop_positions(room.slug, self.loop_stops)
        flow_temperature = self._flow_temperature()
        if not positions or flow_temperature is None:
            return None
        return cascade_flow_temperature(flow_temperature, positions, self.loop_drop_per_station_c)

    def _one_pipe(self, room: RoomConfig) -> bool:
        return room_one_pipe(room, self.entry.options.get(CONF_SYSTEM_TYPE, SYSTEM_ONE_PIPE))

    def _read_external_heat(self, room: RoomConfig) -> tuple[bool | None, list[str]]:
        """Return external-heat state and the sources currently producing heat."""

        def lookup(entity_id: str):
            state = self.hass.states.get(entity_id)
            return None if state is None else (state.state, state.attributes)

        active, sources, self._stove_active[room.slug] = evaluate_external_heat(
            room, lookup, self._stove_active[room.slug]
        )
        return active, sources

    def _evaluate_demand(self, room: RoomConfig, now: datetime) -> DemandView:
        """Compare the recent window with the room's own learned days."""
        model = self.demand[room.slug]
        now_ts = now.timestamp()
        recent = model.recent(now_ts, HEAT_DEMAND_RECENT_WINDOW_HOURS)
        recent_value = recent.w_per_degree(
            HEAT_DEMAND_MIN_RECENT_CLEAN_HOURS, HEAT_DEMAND_MIN_MEAN_LIFT
        )
        today = dt_util.as_local(now).date().isoformat()
        days = model.valid_days(
            today,
            HEAT_DEMAND_HISTORY_DAYS,
            HEAT_DEMAND_MIN_DAY_CLEAN_HOURS,
            HEAT_DEMAND_MIN_MEAN_LIFT,
        )
        learned = [
            DemandDay(value, bucket.mean_lift, bucket.mean_wind)
            for _, bucket in days
            if (
                value := bucket.w_per_degree(
                    HEAT_DEMAND_MIN_DAY_CLEAN_HOURS, HEAT_DEMAND_MIN_MEAN_LIFT
                )
            )
            is not None
            and bucket.mean_lift is not None
        ]
        baseline = learn_demand_baseline(
            learned,
            recent.mean_lift,
            recent.mean_wind,
            min_days=HEAT_DEMAND_MIN_VALID_DAYS,
            max_lift_diff=HEAT_DEMAND_SIMILAR_MAX_LIFT_DIFF,
            wind_scale=HEAT_DEMAND_SIMILAR_WIND_SCALE_MS,
            min_similar=HEAT_DEMAND_MIN_SIMILAR_DAYS,
            max_similar=HEAT_DEMAND_MAX_SIMILAR_DAYS,
            min_relative_spread=HEAT_DEMAND_MIN_RELATIVE_SPREAD,
            min_spread_w=HEAT_DEMAND_MIN_SPREAD_W,
        )
        status, z_score = classify_demand(
            recent_value,
            baseline,
            model.status,
            z_enter=HEAT_DEMAND_Z_ENTER,
            z_exit=HEAT_DEMAND_Z_EXIT,
        )
        model.status = status
        reason = None
        if len(learned) < HEAT_DEMAND_MIN_VALID_DAYS:
            reason = "collecting_days"
        elif recent_value is None:
            lift = recent.mean_lift
            reason = (
                "too_mild"
                if recent.clean_hours >= HEAT_DEMAND_MIN_RECENT_CLEAN_HOURS
                and (lift is None or lift < HEAT_DEMAND_MIN_MEAN_LIFT)
                else "recent_window_incomplete"
            )
        elif baseline.expected is None:
            reason = "outside_learned_weather"
        return DemandView(
            status,
            reason,
            recent,
            recent_value,
            baseline,
            z_score,
            sum(bucket.clean_hours for _, bucket in days),
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
        outdoor = self._outdoor_temperature()
        flow = self._flow_temperature()
        wind = self._wind_speed()
        now_ts = now.timestamp()
        day = dt_util.as_local(now).date().isoformat()
        for room in self.rooms:
            state = self.hass.states.get(room.climate_entity)
            attributes = state.attributes if state else {}
            current = None if state is None else valve_percentage(attributes)
            external_heat, sources = self._read_external_heat(room)
            self.external_heat_active[room.slug] = external_heat
            self.external_heat_sources[room.slug] = sources
            opened = contact_open(attributes)
            self.contact_open[room.slug] = bool(room.better_thermostat_extension_enabled and opened)
            previous = self.valves.get(room.slug)
            if previous is not None and elapsed_hours:
                self.hours[room.slug] += previous / 100.0 * elapsed_hours
            self.valves[room.slug] = current
            if elapsed_hours:
                self._sample_demand(
                    room,
                    now_ts,
                    day,
                    elapsed_hours,
                    current,
                    flow,
                    attributes,
                    outdoor,
                    wind,
                    excluded=external_heat is not False or opened,
                )
            self.demand[room.slug].prune(
                now_ts, HEAT_DEMAND_RECENT_WINDOW_HOURS, HEAT_DEMAND_KEEP_DAYS
            )
            self.demand_views[room.slug] = self._evaluate_demand(room, now)
            await self._check_radiator_alert(room, state, current, now)
        self._last_sample = now
        self._store.async_delay_save(self._data_to_save, 300)
        for listener in list(self.listeners):
            listener()

    async def _check_radiator_alert(self, room, state, valve, now: datetime) -> None:
        try:
            current = float(state.attributes["current_temperature"])
            target = float(state.attributes["temperature"])
        except (AttributeError, KeyError, TypeError, ValueError):
            current = target = None
        period, alert = evaluate_stress(
            self._stress_periods[room.slug],
            now=now,
            valve=valve,
            current=current,
            target=target,
            minutes=self.alert_minutes,
            enabled=self.alert_enabled and bool(self.alert_notify_entity),
        )
        self._stress_periods[room.slug] = period
        if alert is None:
            return
        deficit, rise = alert
        flow = self._flow_temperature()
        language = self.entry.options.get(CONF_ALERT_LANGUAGE, "auto")
        if language == "da" or (language == "auto" and self.hass.config.language == "da"):
            title = f"Radiator presset: {room.name}"
            message = (
                f"Ventilen har været fuldt åben i {self.alert_minutes} min. "
                f"Underskud: {deficit} °C, temperaturstigning: {rise} °C, "
                f"fremløb: {flow if flow is not None else 'ukendt'} °C."
            )
        else:
            title = f"Radiator stressed: {room.name}"
            message = (
                f"The valve has been fully open for {self.alert_minutes} minutes. "
                f"Temperature deficit: {deficit} °C; rise: {rise} °C; "
                f"flow: {flow if flow is not None else 'unknown'} °C."
            )
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"title": title, "message": message},
                blocking=True,
                target={"entity_id": self.alert_notify_entity},
            )
        except Exception:
            _LOGGER.exception("Could not send radiator-stress notification for %s", room.name)

    async def async_set_alert_enabled(self, enabled: bool) -> None:
        self.alert_enabled = enabled
        await self._store.async_save(self._data_to_save())
        for listener in list(self.listeners):
            listener()

    async def async_set_alert_minutes(self, minutes: int) -> None:
        self.alert_minutes = minutes
        await self._store.async_save(self._data_to_save())
        for listener in list(self.listeners):
            listener()

    def _sample_demand(
        self,
        room: RoomConfig,
        when: float,
        day: str,
        hours: float,
        valve: float | None,
        flow: float | None,
        attributes: Any,
        outdoor: float | None,
        wind: float | None,
        *,
        excluded: bool,
        model: DemandModel | None = None,
        tail: ExclusionTail | None = None,
    ) -> None:
        """Feed one live or replayed sample into a room's energy balance."""
        try:
            room_temperature = float(attributes["current_temperature"])
        except (KeyError, TypeError, ValueError):
            room_temperature = None
        sample = demand_sample(
            room.rated_power_w, self._one_pipe(room), valve, flow, room_temperature, outdoor
        )
        clean = (tail or self._tails[room.slug]).clean(when, excluded)
        if sample is None:
            return
        (model or self.demand[room.slug]).add(when, day, hours, sample[0], sample[1], wind, clean)

    async def _async_backfill(self, rooms: list[RoomConfig], until: datetime) -> None:
        """Rebuild the energy balance of `rooms` once from recorded history."""
        if "recorder" not in self.hass.config.components:
            return
        try:
            from homeassistant.components.recorder import get_instance, history

            instance = get_instance(self.hass)
            if not await instance.async_db_ready:
                return
            start = until - timedelta(days=HEAT_DEMAND_BACKFILL_DAYS)
            wind_state = self.hass.states.get(self._wind_entity()) if self._wind_entity() else None
            wind_unit = wind_state.attributes.get("unit_of_measurement") if wind_state else None
            series: dict[str, list[tuple[float, Any]]] = {}
            for entity_id in self._replay_entities(rooms):
                # One entity at a time keeps memory low for chatty climate entities.
                states = await instance.async_add_executor_job(
                    partial(
                        history.get_significant_states,
                        self.hass,
                        start,
                        until,
                        [entity_id],
                        include_start_time_state=True,
                        significant_changes_only=False,
                        minimal_response=False,
                        no_attributes=not entity_id.startswith("climate."),
                    )
                )
                series[entity_id] = [
                    (
                        item.last_updated.timestamp(),
                        (
                            item.state,
                            {
                                key: item.attributes[key]
                                for key in _REPLAY_ATTRIBUTES
                                if key in item.attributes
                            },
                        ),
                    )
                    for item in states.get(entity_id, [])
                ]
            models = await self.hass.async_add_executor_job(
                self._replay, rooms, series, start.timestamp(), until.timestamp(), wind_unit
            )
        except Exception:  # noqa: BLE001 - history is a bonus; live learning continues
            _LOGGER.warning(
                "Could not rebuild heat demand history from the recorder", exc_info=True
            )
            return
        for slug, model in models.items():
            self.demand[slug].merge(model)
        self._store.async_delay_save(self._data_to_save, 1)
        _LOGGER.info("Rebuilt heat demand history for %s rooms", len(models))
        await self.async_update()

    def _replay_entities(self, rooms: list[RoomConfig]) -> list[str]:
        entity_ids = {
            self.entry.options.get(CONF_FLOW_TEMPERATURE, ""),
            self._outdoor_entity(),
            self._wind_entity(),
        }
        for room in rooms:
            entity_ids.add(room.climate_entity)
            if room.better_thermostat_extension_enabled:
                entity_ids.update(room.external_heat_entities)
                entity_ids.add(room.stove_temperature_entity)
        return sorted(entity_id for entity_id in entity_ids if entity_id)

    def _replay(
        self,
        rooms: list[RoomConfig],
        series: dict[str, list[tuple[float, Any]]],
        start: float,
        end: float,
        wind_unit: str | None,
    ) -> dict[str, DemandModel]:
        """Run recorded history through the live sampling rules (executor)."""
        lookups = {entity_id: StepSeries(points) for entity_id, points in series.items()}

        def value(entity_id: str) -> float | None:
            item = lookups[entity_id].at(when) if entity_id in lookups else None
            try:
                return float(item[0])
            except (TypeError, ValueError):
                return None

        def lookup(entity_id: str):
            return lookups[entity_id].at(when) if entity_id in lookups else None

        models = {room.slug: DemandModel() for room in rooms}
        tails = {room.slug: ExclusionTail(HEAT_DEMAND_EXCLUSION_TAIL_HOURS) for room in rooms}
        stoves = {room.slug: False for room in rooms}
        zone = dt_util.get_default_time_zone()
        step = float(DEFAULT_SCAN_INTERVAL)
        hours = step / 3600
        flow_id = self.entry.options.get(CONF_FLOW_TEMPERATURE, "")
        when = start + step
        while when <= end:
            flow = value(flow_id)
            outdoor = value(self._outdoor_entity())
            wind_raw = value(self._wind_entity()) if self._wind_entity() else None
            wind = None if wind_raw is None else wind_speed_ms(wind_raw, wind_unit)
            day = datetime.fromtimestamp(when, zone).date().isoformat()
            for room in rooms:
                climate = lookup(room.climate_entity)
                attributes = climate[1] if climate else {}
                external_heat, _, stoves[room.slug] = evaluate_external_heat(
                    room, lookup, stoves[room.slug]
                )
                self._sample_demand(
                    room,
                    when,
                    day,
                    hours,
                    valve_percentage(attributes),
                    flow,
                    attributes,
                    outdoor,
                    wind,
                    excluded=external_heat is not False or contact_open(attributes),
                    model=models[room.slug],
                    tail=tails[room.slug],
                )
            when += step
        return models

    def _data_to_save(self) -> dict[str, Any]:
        return {
            "alert_enabled": self.alert_enabled,
            "alert_minutes": self.alert_minutes,
            "heat_demand_model_version": HEAT_DEMAND_MODEL_VERSION,
            "month": self._month,
            "hours": self.hours,
            "demand": {room.slug: self.demand[room.slug].to_dict() for room in self.rooms},
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
    # Room devices point at the hub via `via_device`, so the hub must exist
    # before the platforms add the first room entity.
    hub = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=f"{entry.title} (Totals)",
        manufacturer="Room Energy Optimizer",
        model="Local hydronic estimator",
        sw_version=VERSION,
    )
    runtime = RuntimeData(hass, entry)
    runtime.hub_device_id = hub.id
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
