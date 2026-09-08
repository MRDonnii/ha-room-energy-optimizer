"""Pure calculation and configuration helpers."""

from __future__ import annotations

import json
import math
import re
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
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError("power, area and radiator count must be numbers") from err
    if rated <= 0 or area <= 0 or radiator_count <= 0 or initial_hours < 0:
        raise ValueError("power, area and radiator count must be positive")
    return RoomConfig(name, slug, climate_entity, rated, area, radiator_count, initial_hours)


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


def heat_demand_ratio(
    power_w: float,
    indoor_target: float,
    outdoor_temp: float,
    min_delta: float = 2.0,
) -> float | None:
    """Return estimated heat output per degree of indoor/outdoor lift (W/°C).

    This normalises heat demand for outdoor temperature, so a room's ratio is
    comparable across a mild and a cold day. Returns None when the lift is
    too small for the ratio to be meaningful (near-zero denominator).
    """
    delta = indoor_target - outdoor_temp
    if delta < min_delta:
        return None
    return power_w / delta


def update_ema(
    previous: float | None,
    sample: float,
    elapsed_hours: float,
    half_life_hours: float,
) -> float:
    """Time-weighted exponential moving average update.

    Unlike a fixed-alpha EMA, the weight given to `sample` scales with how
    much time actually elapsed since the previous update, so a missed or
    delayed poll does not silently change the effective averaging window.
    """
    if previous is None or elapsed_hours <= 0:
        return sample
    alpha = 1 - 0.5 ** (elapsed_hours / half_life_hours)
    return previous + alpha * (sample - previous)


def classify_heat_demand(
    recent_ratio: float | None,
    baseline_ratio: float | None,
    baseline_hours: float,
    min_baseline_hours: float,
    deviation_threshold: float,
) -> str:
    """Classify a room's current weather-normalised heat demand.

    Returns "learning" until enough baseline data exists to judge, then
    "normal" or "deviating" depending on how far the recent ratio has moved
    from the room's own learned baseline ratio.
    """
    if (
        recent_ratio is None
        or baseline_ratio is None
        or baseline_ratio <= 0
        or baseline_hours < min_baseline_hours
    ):
        return "learning"
    deviation = abs(recent_ratio - baseline_ratio) / baseline_ratio
    return "deviating" if deviation > deviation_threshold else "normal"
