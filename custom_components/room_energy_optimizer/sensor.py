"""Sensors supplied by Room Energy Optimizer."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfArea, UnitOfPower

from .const import (
    CONF_FLOW_TEMPERATURE,
    CONF_MONTHLY_COST,
    CONF_MONTHLY_COST_BASELINE,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    HEAT_DEMAND_DEVIATION_THRESHOLD,
    HEAT_DEMAND_MIN_BASELINE_HOURS,
    SYSTEM_ONE_PIPE,
)
from .entity import OptimizerEntity
from .model import classify_heat_demand, estimated_power


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for room in runtime.rooms:
        entities.extend(
            [
                RoomSensor(runtime, room, "valve", "Valve opening", "%", "mdi:valve"),
                RoomSensor(
                    runtime, room, "hours", "Valve hours this month", "h", "mdi:timer-outline"
                ),
                RoomSensor(
                    runtime,
                    room,
                    "power",
                    "Estimated heat output",
                    UnitOfPower.WATT,
                    "mdi:radiator",
                ),
                RoomSensor(runtime, room, "capacity", "Capacity utilisation", "%", "mdi:gauge"),
                RoomSensor(
                    runtime, room, "share", "Heating share this month", "%", "mdi:chart-donut"
                ),
                RoomSensor(
                    runtime,
                    room,
                    "cost",
                    "Estimated cost this month",
                    hass.config.currency,
                    "mdi:cash",
                ),
                RoomSensor(
                    runtime, room, "area", "Room area", UnitOfArea.SQUARE_METERS, "mdi:set-square"
                ),
                RoomSensor(runtime, room, "radiator_count", "Radiator count", None, "mdi:radiator"),
                RoomSensor(
                    runtime,
                    room,
                    "rated_power",
                    "Rated radiator output",
                    UnitOfPower.WATT,
                    "mdi:radiator",
                ),
                RoomSensor(
                    runtime,
                    room,
                    "heat_loss",
                    "Learned heat loss",
                    "°C/min",
                    "mdi:home-thermometer-outline",
                ),
                HeatDemandStatusSensor(runtime, room),
            ]
        )
    entities.append(TotalPowerSensor(runtime))
    async_add_entities(entities)


class RoomSensor(OptimizerEntity, SensorEntity):
    def __init__(self, runtime, room, kind, name, unit, icon) -> None:
        super().__init__(runtime, f"{room.slug}_{kind}", room=room)
        self.room = room
        self.kind = kind
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        if kind in ("valve", "power", "capacity", "share", "heat_loss"):
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif kind == "hours":
            self._attr_state_class = SensorStateClass.TOTAL
        elif kind == "cost":
            self._attr_device_class = SensorDeviceClass.MONETARY
            self._attr_state_class = SensorStateClass.TOTAL
        elif kind == "rated_power":
            self._attr_device_class = SensorDeviceClass.POWER

    def _power(self):
        climate = self.hass.states.get(self.room.climate_entity)
        flow = self.hass.states.get(self.runtime.entry.options[CONF_FLOW_TEMPERATURE])
        valve = self.runtime.valves[self.room.slug]
        if climate is None or valve is None:
            return None
        try:
            room_temp = float(climate.attributes["current_temperature"])
            flow_temp = float(flow.state) if flow is not None else None
        except (KeyError, TypeError, ValueError):
            return None
        return estimated_power(
            self.room.rated_power_w,
            valve,
            flow_temp,
            room_temp,
            self.runtime.entry.options[CONF_SYSTEM_TYPE] == SYSTEM_ONE_PIPE,
        )

    @property
    def available(self) -> bool:
        if self.kind in ("valve", "power", "capacity"):
            return self.runtime.valves[self.room.slug] is not None
        return True

    @property
    def native_value(self):
        valve = self.runtime.valves[self.room.slug]
        hours = self.runtime.hours[self.room.slug]
        weighted = hours * self.room.rated_power_w
        total_weighted = sum(
            self.runtime.hours[item.slug] * item.rated_power_w for item in self.runtime.rooms
        )
        if self.kind == "valve":
            return None if valve is None else round(valve, 1)
        if self.kind == "hours":
            return round(hours, 3)
        if self.kind == "power":
            power = self._power()
            return None if power is None else round(power)
        if self.kind == "capacity":
            power = self._power()
            return None if power is None else round(100 * power / self.room.rated_power_w, 1)
        if self.kind == "share":
            return round(100 * weighted / total_weighted, 3) if total_weighted > 0 else 0
        if self.kind == "cost":
            entity_id = self.runtime.entry.options.get(CONF_MONTHLY_COST, "")
            state = self.hass.states.get(entity_id) if entity_id else None
            try:
                total_cost = max(0.0, float(state.state))
            except (AttributeError, TypeError, ValueError):
                return 0
            baseline_id = self.runtime.entry.options.get(CONF_MONTHLY_COST_BASELINE, "")
            baseline_state = self.hass.states.get(baseline_id) if baseline_id else None
            try:
                baseline = max(0.0, float(baseline_state.state))
            except (AttributeError, TypeError, ValueError):
                baseline = 0.0
            distributable = max(0.0, total_cost - baseline)
            return round(distributable * weighted / total_weighted, 2) if total_weighted > 0 else 0
        if self.kind == "rated_power":
            return self.room.rated_power_w
        if self.kind == "radiator_count":
            return self.room.radiator_count
        if self.kind == "heat_loss":
            climate = self.hass.states.get(self.room.climate_entity)
            try:
                return round(float(climate.attributes.get("heat_loss", 0)), 4)
            except (AttributeError, TypeError, ValueError):
                return 0
        return self.room.area_m2


class HeatDemandStatusSensor(OptimizerEntity, SensorEntity):
    """Whether a room's weather-normalised heat demand looks normal.

    Compares a fast (recent) and a slow (learned baseline) moving average of
    the room's own watt-per-degree-of-lift ratio. Requires the optional
    outdoor temperature sensor to be configured; stays "learning" until
    enough hours of valid samples have been collected.
    """

    _attr_icon = "mdi:thermometer-check"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["learning", "normal", "deviating"]
    _attr_translation_key = "heat_demand_status"

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_heat_demand_status", room=room)
        self.room = room
        self._attr_name = "Heat demand status"

    @property
    def available(self) -> bool:
        return bool(self.runtime.entry.options.get(CONF_OUTDOOR_TEMPERATURE, ""))

    @property
    def native_value(self):
        return classify_heat_demand(
            self.runtime.ratio_recent[self.room.slug],
            self.runtime.ratio_baseline[self.room.slug],
            self.runtime.baseline_hours[self.room.slug],
            HEAT_DEMAND_MIN_BASELINE_HOURS,
            HEAT_DEMAND_DEVIATION_THRESHOLD,
        )

    @property
    def extra_state_attributes(self):
        recent = self.runtime.ratio_recent[self.room.slug]
        baseline = self.runtime.ratio_baseline[self.room.slug]
        deviation_percent = None
        if recent is not None and baseline:
            deviation_percent = round(100 * (recent - baseline) / baseline, 1)
        return {
            "current_w_per_degree": None if recent is None else round(recent, 2),
            "learned_baseline_w_per_degree": None if baseline is None else round(baseline, 2),
            "deviation_percent": deviation_percent,
            "baseline_learning_hours": round(self.runtime.baseline_hours[self.room.slug], 1),
            "baseline_ready": self.runtime.baseline_hours[self.room.slug]
            >= HEAT_DEMAND_MIN_BASELINE_HOURS,
        }


class TotalPowerSensor(OptimizerEntity, SensorEntity):
    _attr_name = "Estimated total heat demand"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:home-lightning-bolt-outline"

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "total_power")

    @property
    def native_value(self):
        values = []
        for room in self.runtime.rooms:
            climate = self.hass.states.get(room.climate_entity)
            flow = self.hass.states.get(self.runtime.entry.options[CONF_FLOW_TEMPERATURE])
            valve = self.runtime.valves[room.slug]
            try:
                value = estimated_power(
                    room.rated_power_w,
                    valve,
                    float(flow.state),
                    float(climate.attributes["current_temperature"]),
                    self.runtime.entry.options[CONF_SYSTEM_TYPE] == SYSTEM_ONE_PIPE,
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                value = None
            if value is not None:
                values.append(value)
        return round(sum(values)) if values else None
