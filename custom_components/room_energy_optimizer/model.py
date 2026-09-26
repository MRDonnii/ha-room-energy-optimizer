"""Pure calculation and configuration helpers."""

from __future__ import annotations

import json
import math
import re
import statistics
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

SLUG_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class RoomConfig:
    """One configured heated room."""

    name: str
    slug: str
    climate_entity: str
    rated_power_w: float
    area_m2: float
    radiator_count: int = 1
    initial_valve_hours: float = 0.0
    better_thermostat_extension_enabled: bool = False
    external_heat_entities: tuple[str, ...] = ()
    stove_temperature_entity: str = ""
    stove_on_temperature: float = 25.0
    stove_off_temperature: float = 24.0
    # "" = inherit the house-wide system_type; "one_pipe"/"two_pipe" overrides it
    # for a room on its own dedicated branch (e.g. a two-pipe garage circuit
    # off an otherwise one-pipe house).
    system_type_override: str = ""


def slugify(value: str) -> str:
    """Return a stable ASCII-ish object-id fragment."""
    replacements = str.maketrans({"æ": "ae", "ø": "oe", "å": "aa"})
    value = value.strip().lower().translate(replacements).replace(" ", "_")
    return SLUG_RE.sub("", value).strip("_")


def parse_rooms(raw: str) -> list[RoomConfig]:
    """Parse NAME|CLIMATE|RATED_W|AREA_M2 lines."""
    rooms: list[RoomConfig] = []
    seen: set[str] = set()
    for number, source_line in enumerate(raw.splitlines(), 1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) not in (4, 5):
            raise ValueError(f"line {number}: expected 4 or 5 fields")
        name, climate_entity, rated_text, area_text = parts[:4]
        slug = slugify(name)
        if not name or not slug:
            raise ValueError(f"line {number}: invalid room name")
        if not climate_entity.startswith("climate."):
            raise ValueError(f"line {number}: climate entity must start with climate.")
        try:
            rated = float(rated_text.replace(",", "."))
            area = float(area_text.replace(",", "."))
            initial_hours = float(parts[4].replace(",", ".")) if len(parts) == 5 else 0.0
        except ValueError as err:
            raise ValueError(f"line {number}: power and area must be numbers") from err
        if rated <= 0 or area <= 0 or initial_hours < 0:
            raise ValueError(f"line {number}: power and area must be positive")
        if slug in seen:
            raise ValueError(f"line {number}: duplicate room name")
        seen.add(slug)
        rooms.append(RoomConfig(name, slug, climate_entity, rated, area, 1, initial_hours))
    if not rooms:
        raise ValueError("at least one room is required")
    return rooms


def room_to_dict(room: RoomConfig) -> dict[str, Any]:
    """Serialise a room for config entry option storage."""
    return {
        "name": room.name,
        "climate_entity": room.climate_entity,
        "rated_power_w": room.rated_power_w,
        "area_m2": room.area_m2,
        "radiator_count": room.radiator_count,
        "initial_valve_hours": room.initial_valve_hours,
        "better_thermostat_extension_enabled": room.better_thermostat_extension_enabled,
        "external_heat_entities": list(room.external_heat_entities),
        "stove_temperature_entity": room.stove_temperature_entity,
        "stove_on_temperature": room.stove_on_temperature,
        "stove_off_temperature": room.stove_off_temperature,
        "system_type_override": room.system_type_override,
    }


def room_from_dict(data: dict[str, Any], existing_slugs: set[str]) -> RoomConfig:
    """Build and validate one room from a step-by-step wizard submission."""
    name = str(data.get("name", "")).strip()
    slug = slugify(name)
    if not name or not slug:
        raise ValueError("invalid room name")
    if slug in existing_slugs:
        raise ValueError("duplicate room name")
    climate_entity = str(data.get("climate_entity", ""))
    if not climate_entity.startswith("climate."):
        raise ValueError("climate entity must start with climate.")
    try:
        rated = float(str(data["rated_power_w"]).replace(",", "."))
        area = float(str(data["area_m2"]).replace(",", "."))
        radiator_count = int(float(str(data.get("radiator_count", 1) or 1).replace(",", ".")))
        initial_hours = float(str(data.get("initial_valve_hours", 0) or 0).replace(",", "."))
        stove_on = float(str(data.get("stove_on_temperature", 25) or 25).replace(",", "."))
        stove_off = float(str(data.get("stove_off_temperature", 24) or 24).replace(",", "."))
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError("power, area and radiator count must be numbers") from err
    if rated <= 0 or area <= 0 or radiator_count <= 0 or initial_hours < 0:
        raise ValueError("power, area and radiator count must be positive")
    external_heat_entities = tuple(
        str(entity_id)
        for entity_id in data.get("external_heat_entities", [])
        if str(entity_id).startswith(("binary_sensor.", "climate."))
    )
    stove_entity = str(data.get("stove_temperature_entity", "") or "")
    extension_enabled = bool(
        data.get(
            "better_thermostat_extension_enabled",
            bool(external_heat_entities or stove_entity),
        )
    )
    if stove_entity and not stove_entity.startswith("sensor."):
        raise ValueError("stove temperature entity must be a sensor")
    if stove_off >= stove_on:
        raise ValueError("stove off temperature must be below on temperature")
    system_type_override = str(data.get("system_type_override", "") or "")
    if system_type_override == "inherit":
        system_type_override = ""
    if system_type_override not in ("", "one_pipe", "two_pipe"):
        raise ValueError("system type override must be one_pipe or two_pipe")
    return RoomConfig(
        name,
        slug,
        climate_entity,
        rated,
        area,
        radiator_count,
        initial_hours,
        extension_enabled,
        external_heat_entities,
        stove_entity,
        stove_on,
        stove_off,
        system_type_override,
    )


def rooms_from_options(raw: list[dict[str, Any]] | str) -> list[RoomConfig]:
    """Build the configured room list from stored options.

    Accepts either the current list-of-dicts format (the step-by-step setup
    wizard, 1.4.0+) or the legacy pipe-delimited string format from 1.3.x and
    earlier, so existing installs keep working without a manual re-setup.
    """
    if isinstance(raw, str):
        return parse_rooms(raw)
    rooms: list[RoomConfig] = []
    seen: set[str] = set()
    for entry in raw:
        room = room_from_dict(entry, seen)
        seen.add(room.slug)
        rooms.append(room)
    if not rooms:
        raise ValueError("at least one room is required")
    return rooms


def room_one_pipe(room: RoomConfig, global_system_type: str) -> bool:
    """Resolve whether one room's estimate should use the one-pipe formula.

    A room's own `system_type_override` wins when set (e.g. Garage/Køkken on
    a dedicated two-pipe branch off an otherwise one-pipe house); otherwise
    it falls back to the house-wide system_type.
    """
    return (room.system_type_override or global_system_type) == "one_pipe"


def parse_loop_order(raw: str) -> list[tuple[str, str]]:
    """Parse the free-text one-pipe loop order into (label, room_slug) stops.

    One stop per physical point in the loop, in flow order: `label` on its
    own for an unmetered stop (e.g. a floor-heating loop with no climate
    entity), or `label|room_slug` to link a stop to a configured room. A
    room with several radiators on the loop (e.g. two thermostats grouped
    under one climate entity) gets one line per radiator, all pointing at
    the same slug. Blank lines and '#' comments are ignored.
    """
    stops: list[tuple[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            label, slug = (part.strip() for part in line.split("|", 1))
        else:
            label, slug = line, ""
        stops.append((label, slug))
    return stops


def room_loop_positions(room_slug: str, stops: list[tuple[str, str]]) -> list[int]:
    """1-based flow positions of a room's radiator(s) in the parsed loop order."""
    return [index for index, (_, slug) in enumerate(stops, 1) if slug == room_slug]


def cascade_flow_temperature(
    flow_temperature: float, positions: list[int], drop_per_station_c: float
) -> float | None:
    """EXPERIMENTAL: estimate the flow temperature reaching a room's own
    radiator(s) on a one-pipe loop, assuming a flat temperature drop at
    each preceding stop. This is not calibrated against any measured
    per-radiator temperature - it is a rough, assumed decay rate applied
    to the loop position the room was told to be at. Treat any sensor
    built on this as an indication to sanity-check, not a trusted figure.
    """
    if not positions:
        return None
    average_position = sum(positions) / len(positions)
    return flow_temperature - drop_per_station_c * (average_position - 1)


def valve_percentage(attributes: dict[str, Any]) -> float | None:
    """Read Better Thermostat calibration_balance without modifying it."""
    balance = attributes.get("calibration_balance")
    if isinstance(balance, str):
        try:
            balance = json.loads(balance)
        except (TypeError, ValueError):
            return None
    if not isinstance(balance, dict) or not balance:
        return None
    values: list[float] = []
    for item in balance.values():
        if not isinstance(item, dict):
            continue
        value = item.get("valve%")
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            values.append(max(0.0, min(100.0, float(value))))
    return sum(values) / len(values) if values else None


def estimated_power(
    rated_power_w: float,
    valve_percent: float,
    flow_temperature: float | None,
    room_temperature: float | None,
    one_pipe: bool,
) -> float | None:
    """Estimate radiator output using an EN 442 style LMTD ratio."""
    if flow_temperature is None or room_temperature is None:
        return None
    delta_flow = flow_temperature - room_temperature
    if delta_flow <= 0:
        return 0.0
    # Without a per-radiator return sensor, one-pipe systems must not use a
    # shared return. Estimate 70/40/20 reference behaviour instead.
    return_temperature = (
        room_temperature + 0.4 * delta_flow if one_pipe else flow_temperature - 10.0
    )
    delta_return = return_temperature - room_temperature
    if delta_return <= 0:
        return 0.0
    if abs(delta_flow - delta_return) < 1e-9:
        lmtd = delta_flow
    else:
        lmtd = (delta_flow - delta_return) / math.log(delta_flow / delta_return)
    reference_lmtd = (50.0 - 20.0) / math.log(50.0 / 20.0)
    temperature_factor = max(0.0, lmtd / reference_lmtd) ** 1.3
    return max(0.0, rated_power_w * valve_percent / 100.0 * temperature_factor)


# --- Weather-normalised heat demand, model v3 (energy signature) -------------
#
# A room's heat demand is judged from an energy balance instead of from single
# samples: estimated radiator energy divided by the degree-hours between room and
# outdoor temperature over the same clean period (W/°C). Minutes with a closed
# radiator count as zero output, so heating longer or shorter is visible. The
# recent 48-hour value is compared with the room's own completed days that had
# the most similar weather, using their median and robust spread.

DEMAND_STATUSES = ("learning", "normal", "deviating")

_WIND_TO_MS = {"m/s": 1.0, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "ft/s": 0.3048}


def wind_speed_ms(value: float, unit: str | None) -> float:
    """Convert a wind speed reading to m/s (Beaufort via the WMO relation)."""
    if unit == "Beaufort":
        return 0.836 * max(0.0, value) ** 1.5
    return value * _WIND_TO_MS.get(unit or "m/s", 1.0)


@dataclass(slots=True)
class DemandTotals:
    """Energy-balance sums for one hour, one day or one window."""

    energy_wh: float = 0.0
    degree_hours: float = 0.0
    clean_hours: float = 0.0
    excluded_hours: float = 0.0
    wind_ms_hours: float = 0.0
    wind_hours: float = 0.0

    def add(
        self, hours: float, power_w: float, lift: float, wind_ms: float | None, clean: bool
    ) -> None:
        """Add one sample; excluded samples only count as excluded time."""
        if not clean:
            self.excluded_hours += hours
            return
        self.energy_wh += power_w * hours
        self.degree_hours += lift * hours
        self.clean_hours += hours
        if wind_ms is not None:
            self.wind_ms_hours += wind_ms * hours
            self.wind_hours += hours

    def merge(self, other: DemandTotals) -> None:
        self.energy_wh += other.energy_wh
        self.degree_hours += other.degree_hours
        self.clean_hours += other.clean_hours
        self.excluded_hours += other.excluded_hours
        self.wind_ms_hours += other.wind_ms_hours
        self.wind_hours += other.wind_hours

    @property
    def mean_lift(self) -> float | None:
        return self.degree_hours / self.clean_hours if self.clean_hours > 0 else None

    @property
    def mean_wind(self) -> float | None:
        return self.wind_ms_hours / self.wind_hours if self.wind_hours > 0 else None

    def w_per_degree(self, min_clean_hours: float, min_mean_lift: float) -> float | None:
        """Estimated radiator heat per degree of room/outdoor difference (W/°C)."""
        lift = self.mean_lift
        if (
            self.clean_hours < min_clean_hours
            or lift is None
            or lift < min_mean_lift
            or self.degree_hours <= 0
        ):
            return None
        return self.energy_wh / self.degree_hours

    def to_list(self) -> list[float]:
        return [
            round(value, 4)
            for value in (
                self.energy_wh,
                self.degree_hours,
                self.clean_hours,
                self.excluded_hours,
                self.wind_ms_hours,
                self.wind_hours,
            )
        ]

    @classmethod
    def from_list(cls, values: Any) -> DemandTotals:
        if not isinstance(values, list) or len(values) != 6:
            return cls()
        try:
            return cls(*(float(value) for value in values))
        except (TypeError, ValueError):
            return cls()


@dataclass(frozen=True, slots=True)
class DemandBaseline:
    """What a room normally needs in weather like the recent window's."""

    days: int
    compared: int = 0
    expected: float | None = None
    spread: float | None = None
    lift_range: tuple[float, float] | None = None
    wind_range: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class DemandDay:
    """One valid completed day of a room's energy balance."""

    w_per_degree: float
    lift: float
    wind: float | None


def learn_demand_baseline(
    days: list[DemandDay],
    lift: float | None,
    wind: float | None,
    *,
    min_days: int,
    max_lift_diff: float,
    wind_scale: float,
    min_similar: int,
    max_similar: int,
    min_relative_spread: float,
    min_spread_w: float,
) -> DemandBaseline:
    """Learn a room's normal W/°C from its days with the most similar weather.

    Days count as comparable when their mean room/outdoor difference is within
    `max_lift_diff` of the recent one; the closest are chosen, with wind as a
    tie-breaker (`wind_scale` m/s weighs as much as 1 °C). The normal is their
    median and the spread their robust standard deviation (MAD), never below
    `min_relative_spread` of the normal or `min_spread_w` of average output.
    """
    if len(days) < min_days or lift is None or lift <= 0:
        return DemandBaseline(len(days))

    def distance(day: DemandDay) -> float:
        wind_part = 0.0 if wind is None or day.wind is None else abs(day.wind - wind) / wind_scale
        return abs(day.lift - lift) + wind_part

    similar = sorted((day for day in days if abs(day.lift - lift) <= max_lift_diff), key=distance)[
        :max_similar
    ]
    if len(similar) < min_similar:
        return DemandBaseline(len(days), len(similar))
    values = [day.w_per_degree for day in similar]
    expected = statistics.median(values)
    mad = statistics.median(abs(value - expected) for value in values)
    spread = max(1.4826 * mad, min_relative_spread * expected, min_spread_w / lift)
    lifts = [day.lift for day in similar]
    winds = [day.wind for day in similar if day.wind is not None]
    return DemandBaseline(
        len(days),
        len(similar),
        expected,
        spread,
        (min(lifts), max(lifts)),
        (min(winds), max(winds)) if winds else None,
    )


def classify_demand(
    recent: float | None,
    baseline: DemandBaseline,
    previous_status: str,
    *,
    z_enter: float,
    z_exit: float,
) -> tuple[str, float | None]:
    """Return the status and robust z-score of the recent W/°C value.

    Entering "deviating" requires the recent value to lie `z_enter` spreads from
    the room's normal; leaving it requires coming back within `z_exit`.
    """
    if recent is None or baseline.expected is None or not baseline.spread:
        return "learning", None
    z_score = (recent - baseline.expected) / baseline.spread
    if previous_status == "deviating":
        return ("normal" if abs(z_score) < z_exit else "deviating"), z_score
    return ("deviating" if abs(z_score) > z_enter else "normal"), z_score


class DemandModel:
    """Hourly and daily energy-balance history of one room."""

    def __init__(self) -> None:
        self.hours: dict[int, DemandTotals] = {}
        self.days: dict[str, DemandTotals] = {}
        self.status = "learning"

    @property
    def empty(self) -> bool:
        return not self.hours and not self.days

    def add(
        self,
        when: float,
        day: str,
        hours: float,
        power_w: float,
        lift: float,
        wind_ms: float | None,
        clean: bool,
    ) -> None:
        """Add a sample taken at epoch `when` on local date `day`."""
        hour = int(when // 3600) * 3600
        for bucket in (
            self.hours.setdefault(hour, DemandTotals()),
            self.days.setdefault(day, DemandTotals()),
        ):
            bucket.add(hours, power_w, lift, wind_ms, clean)

    def merge(self, other: DemandModel) -> None:
        """Fold in samples from a disjoint period, e.g. replayed history."""
        for key, bucket in other.hours.items():
            self.hours.setdefault(key, DemandTotals()).merge(bucket)
        for key, bucket in other.days.items():
            self.days.setdefault(key, DemandTotals()).merge(bucket)

    def prune(self, now: float, window_hours: int, keep_days: int) -> None:
        oldest = int(now // 3600) * 3600 - window_hours * 3600
        self.hours = {key: bucket for key, bucket in self.hours.items() if key >= oldest}
        for key in sorted(self.days)[:-keep_days]:
            del self.days[key]

    def recent(self, now: float, window_hours: int) -> DemandTotals:
        """Sums over the last `window_hours` clock hours, the running hour included."""
        oldest = int(now // 3600) * 3600 - (window_hours - 1) * 3600
        totals = DemandTotals()
        for key, bucket in self.hours.items():
            if key >= oldest:
                totals.merge(bucket)
        return totals

    def valid_days(
        self, today: str, history_days: int, min_clean_hours: float, min_mean_lift: float
    ) -> list[tuple[str, DemandTotals]]:
        """The newest `history_days` completed days with enough clean data."""
        days = [
            (key, bucket)
            for key, bucket in sorted(self.days.items())
            if key < today and bucket.w_per_degree(min_clean_hours, min_mean_lift) is not None
        ]
        return days[-history_days:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "hours": {str(key): bucket.to_list() for key, bucket in self.hours.items()},
            "days": {key: bucket.to_list() for key, bucket in self.days.items()},
        }

    @classmethod
    def from_dict(cls, data: Any) -> DemandModel:
        model = cls()
        if not isinstance(data, dict):
            return model
        if data.get("status") in DEMAND_STATUSES:
            model.status = data["status"]
        for key, values in (data.get("hours") or {}).items():
            try:
                model.hours[int(key)] = DemandTotals.from_list(values)
            except (TypeError, ValueError):
                continue
        for key, values in (data.get("days") or {}).items():
            if isinstance(key, str):
                model.days[key] = DemandTotals.from_list(values)
        return model


class ExclusionTail:
    """Keep samples out for a while after external heat or an opening ends.

    Right after an air-conditioner stops the radiator has little to do, and
    right after a window closes it has extra to do; neither is normal demand.
    """

    def __init__(self, tail_hours: float) -> None:
        self.tail_seconds = tail_hours * 3600
        self.until: float | None = None

    def clean(self, when: float, excluded: bool) -> bool:
        if excluded:
            self.until = when + self.tail_seconds
            return False
        return self.until is None or when >= self.until


def contact_open(attributes: Mapping[str, Any]) -> bool:
    """Better Thermostat's debounced window/door state."""
    return bool(attributes.get("window_open", False) or attributes.get("door_open", False))


def evaluate_external_heat(
    room: RoomConfig,
    lookup: Callable[[str], tuple[str, Mapping[str, Any]] | None],
    stove_active: bool,
) -> tuple[bool | None, list[str], bool]:
    """Return (active, active sources, stove state) for a room's external heat.

    `lookup` returns (state, attributes) for an entity or None when it is
    missing. Active is None when a configured source cannot be read. Climate
    sources count only while `hvac_action` is heating; the stove temperature
    uses its on/off hysteresis.
    """
    if not room.better_thermostat_extension_enabled:
        return False, [], stove_active
    active_sources: list[str] = []
    valid = True
    for entity_id in room.external_heat_entities:
        item = lookup(entity_id)
        if item is None or item[0] in ("unknown", "unavailable"):
            valid = False
            continue
        state, attributes = item
        active = (
            attributes.get("hvac_action") == "heating"
            if entity_id.startswith("climate.")
            else state == "on"
        )
        if active:
            active_sources.append(entity_id)
    if room.stove_temperature_entity:
        item = lookup(room.stove_temperature_entity)
        try:
            temperature = float(item[0] if item else "")
        except (TypeError, ValueError):
            valid = False
        else:
            if stove_active:
                stove_active = temperature >= room.stove_off_temperature
            else:
                stove_active = temperature > room.stove_on_temperature
            if stove_active:
                active_sources.append(room.stove_temperature_entity)
    return (bool(active_sources) if valid else None), active_sources, stove_active


def demand_sample(
    rated_power_w: float,
    one_pipe: bool,
    valve: float | None,
    flow_temperature: float | None,
    room_temperature: float | None,
    outdoor_temperature: float | None,
) -> tuple[float, float] | None:
    """Return (estimated radiator W, room minus outdoor °C) or None when unknown."""
    if valve is None or room_temperature is None or outdoor_temperature is None:
        return None
    power = estimated_power(rated_power_w, valve, flow_temperature, room_temperature, one_pipe)
    if power is None:
        return None
    return power, room_temperature - outdoor_temperature


class StepSeries:
    """Forward-filled lookup in a time-ordered series while stepping forward."""

    def __init__(self, points: list[tuple[float, Any]]) -> None:
        self._points = sorted(points, key=lambda point: point[0])
        self._index = -1

    def at(self, when: float) -> Any:
        while self._index + 1 < len(self._points) and self._points[self._index + 1][0] <= when:
            self._index += 1
        return self._points[self._index][1] if self._index >= 0 else None
