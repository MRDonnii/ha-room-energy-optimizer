"""Sensors supplied by Room Energy Optimizer."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfArea, UnitOfPower
from homeassistant.helpers.entity import EntityCategory

from .const import (
    CONF_FLOW_TEMPERATURE,
    CONF_MONTHLY_COST,
    CONF_MONTHLY_COST_BASELINE,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    HEAT_DEMAND_MIN_VALID_DAYS,
    HEAT_DEMAND_RECENT_WINDOW_HOURS,
    SYSTEM_ONE_PIPE,
)
from .entity import OptimizerEntity
from .model import estimated_power, room_loop_positions, room_one_pipe


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
                HeatDemandPerDegreeSensor(runtime, room),
            ]
        )
        if room_loop_positions(room.slug, runtime.loop_stops):
            entities.append(ExperimentalCascadePowerSensor(runtime, room))
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
        global_system_type = self.runtime.entry.options.get(CONF_SYSTEM_TYPE, SYSTEM_ONE_PIPE)
        return estimated_power(
            self.room.rated_power_w,
            valve,
            flow_temp,
            room_temp,
            room_one_pipe(self.room, global_system_type),
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


class ExperimentalCascadePowerSensor(OptimizerEntity, SensorEntity):
    """EXPERIMENTAL: estimated heat output using an assumed one-pipe cascade.

    Unlike the main "Estimated heat output" sensor (which applies a flat
    correction for the whole room regardless of loop position), this adjusts
    the flow temperature per this room's configured loop_order position(s),
    using an assumed, uncalibrated temperature drop per stop
    (loop_drop_per_station_c). Nothing here is measured - it exists so a
    room's number can be sanity-checked once real per-radiator temperatures
    are available, not to be trusted as-is. Diagnostic category, and named
    accordingly, so it never gets mistaken for the primary estimate.
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flask-outline"

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_experimental_cascade_power", room=room)
        self.room = room
        self._attr_name = "Estimated heat output (experimental cascade)"

    @property
    def available(self) -> bool:
        return self.runtime.valves[self.room.slug] is not None

    def _cascade_power(self):
        climate = self.hass.states.get(self.room.climate_entity)
        valve = self.runtime.valves[self.room.slug]
        flow_temp = self.runtime.experimental_cascade_flow_temperature(self.room)
        if climate is None or valve is None or flow_temp is None:
            return None
        try:
            room_temp = float(climate.attributes["current_temperature"])
        except (KeyError, TypeError, ValueError):
            return None
        return estimated_power(self.room.rated_power_w, valve, flow_temp, room_temp, False)

    @property
    def native_value(self):
        power = self._cascade_power()
        return None if power is None else round(power)

    @property
    def extra_state_attributes(self):
        positions = room_loop_positions(self.room.slug, self.runtime.loop_stops)
        return {
            "loop_positions": positions,
            "assumed_drop_per_station_c": self.runtime.loop_drop_per_station_c,
            "assumed_flow_temperature_c": self.runtime.experimental_cascade_flow_temperature(
                self.room
            ),
            "calibrated": False,
        }


class HeatDemandStatusSensor(OptimizerEntity, SensorEntity):
    """Whether a room's weather-normalised heat demand looks normal.

    Compares the room's energy balance over the last 48 hours (estimated
    radiator energy per degree-hour of room/outdoor difference) with its own
    completed days that had the most similar weather. Requires the optional
    outdoor temperature sensor; stays "learning" until there are seven valid
    days, a full recent window and enough days with comparable weather.
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
        return bool(self.runtime.entry.options.get(CONF_OUTDOOR_TEMPERATURE, "")) and (
            self.room.slug in self.runtime.demand_views
        )

    @property
    def native_value(self):
        return self.runtime.demand_views[self.room.slug].status

    @property
    def extra_state_attributes(self):
        view = self.runtime.demand_views.get(self.room.slug)
        if view is None:
            return {}
        recent, baseline = view.recent, view.baseline
        expected, spread = baseline.expected, baseline.spread
        current = view.recent_w_per_degree
        deviation_percent = None
        if current is not None and expected:
            deviation_percent = round(100 * (current - expected) / expected, 1)
        normal_range = None
        if expected is not None and spread is not None:
            normal_range = [
                round(max(0.0, expected - 2 * spread), 2),
                round(expected + 2 * spread, 2),
            ]

        def rounded(value, digits=2):
            return None if value is None else round(value, digits)

        return {
            "method": "energy_signature",
            "reason": view.reason,
            "current_w_per_degree": rounded(current),
            "learned_baseline_w_per_degree": rounded(expected),
            "deviation_percent": deviation_percent,
            "normal_range_w_per_degree": normal_range,
            "z_score": rounded(view.z_score),
            "valid_days": baseline.days,
            "required_days": HEAT_DEMAND_MIN_VALID_DAYS,
            "window_hours": HEAT_DEMAND_RECENT_WINDOW_HOURS,
            "recent_observation_hours": round(recent.clean_hours, 1),
            "recent_excluded_hours": round(recent.excluded_hours, 1),
            "recent_energy_kwh": round(recent.energy_wh / 1000, 2),
            "recent_mean_lift_c": rounded(recent.mean_lift, 1),
            "recent_mean_wind_ms": rounded(recent.mean_wind, 1),
            "compared_days": baseline.compared,
            "compared_lift_range_c": (
                None if baseline.lift_range is None else [round(v, 1) for v in baseline.lift_range]
            ),
            "compared_wind_range_ms": (
                None if baseline.wind_range is None else [round(v, 1) for v in baseline.wind_range]
            ),
            "baseline_learning_hours": round(view.baseline_clean_hours, 1),
            "recent_ready": current is not None,
            "baseline_ready": expected is not None,
        }


class HeatDemandPerDegreeSensor(OptimizerEntity, SensorEntity):
    """The room's recent heat demand per degree of room/outdoor difference.

    Estimated radiator energy over the last 48 hours divided by the
    degree-hours between room and outdoor temperature (closed radiator counts
    as zero output; external heat and open windows/doors are left out).
    """

    _attr_icon = "mdi:home-thermometer"
    _attr_native_unit_of_measurement = "W/°C"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_heat_demand_per_degree", room=room)
        self.room = room
        self._attr_name = "Heat demand per degree"

    @property
    def available(self) -> bool:
        view = self.runtime.demand_views.get(self.room.slug)
        return bool(self.runtime.entry.options.get(CONF_OUTDOOR_TEMPERATURE, "")) and (
            view is not None and view.recent_w_per_degree is not None
        )

    @property
    def native_value(self):
        view = self.runtime.demand_views.get(self.room.slug)
        if view is None or view.recent_w_per_degree is None:
            return None
        return round(view.recent_w_per_degree, 3)

    @property
    def extra_state_attributes(self):
        view = self.runtime.demand_views.get(self.room.slug)
        expected = None if view is None else view.baseline.expected
        return {"expected_w_per_degree": None if expected is None else round(expected, 3)}


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
        global_system_type = self.runtime.entry.options.get(CONF_SYSTEM_TYPE, SYSTEM_ONE_PIPE)
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
                    room_one_pipe(room, global_system_type),
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                value = None
            if value is not None:
                values.append(value)
        return round(sum(values)) if values else None
