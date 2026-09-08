"""Pure calculation and configuration helpers."""

from __future__ import annotations

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
        rooms.append(RoomConfig(name, slug, climate_entity, rated, area, initial_hours))
    if not rooms:
        raise ValueError("at least one room is required")
    return rooms


def valve_percentage(attributes: dict[str, Any]) -> float | None:
    """Read Better Thermostat calibration_balance without modifying it."""
    balance = attributes.get("calibration_balance")
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
