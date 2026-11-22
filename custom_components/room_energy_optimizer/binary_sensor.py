"""Health sensor for Room Energy Optimizer."""

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_FLOW_TEMPERATURE, CONF_OUTDOOR_TEMPERATURE, CONF_WIND_SPEED, DOMAIN
from .entity import OptimizerEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    runtime = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DataHealthSensor(runtime),
            *(RadiatorStressedSensor(runtime, room) for room in runtime.rooms),
            *(
                ExternalHeatSensor(runtime, room)
                for room in runtime.rooms
                if room.better_thermostat_extension_enabled
            ),
            *(
                OpeningContactSensor(runtime, room)
                for room in runtime.rooms
                if room.better_thermostat_extension_enabled
            ),
        ]
    )


# A problem must last this long before the sensor reports it. Reloading Better
# Thermostat (an options change, enabling an entity) or restarting Home Assistant
# leaves the climate, valve and weather entities unavailable for under a minute,
# which must not raise a data problem or its notification.
DATA_PROBLEM_GRACE = timedelta(minutes=5)


def _now():
    return dt_util.utcnow()


class DataHealthSensor(OptimizerEntity, BinarySensorEntity):
    _attr_name = "Data problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "data_problem")
        self._problem_since = None

    @property
    def is_on(self) -> bool:
        if not self._raw_problem():
            self._problem_since = None
            return False
        now = _now()
        if self._problem_since is None:
            self._problem_since = now
        return now - self._problem_since >= DATA_PROBLEM_GRACE

    def _raw_problem(self) -> bool:
        flow = self.hass.states.get(self.runtime.entry.options[CONF_FLOW_TEMPERATURE])
        unsupported_guards = [
            room
            for room in self.runtime.rooms
            if room.better_thermostat_extension_enabled and not self._bt_guard_supported(room)
        ]
        return (
            flow is None
            or flow.state in ("unknown", "unavailable")
            or any(value is None for value in self.runtime.valves.values())
            or any(value is None for value in self.runtime.external_heat_active.values())
            or bool(unsupported_guards)
            or bool(self._unavailable_weather_inputs())
        )

    def _unavailable_weather_inputs(self) -> list[str]:
        """Configured outdoor/wind sensors that currently give no reading."""
        missing = []
        for key in (CONF_OUTDOOR_TEMPERATURE, CONF_WIND_SPEED):
            entity_id = self.runtime.entry.options.get(key, "")
            state = self.hass.states.get(entity_id) if entity_id else None
            if entity_id and (state is None or state.state in ("unknown", "unavailable")):
                missing.append(entity_id)
        return missing

    def _bt_guard_supported(self, room) -> bool:
        climate = self.hass.states.get(room.climate_entity)
        return bool(climate and "thermal_learning_paused" in climate.attributes)

    @property
    def extra_state_attributes(self):
        return {
            "missing_valve_data": [
                room.climate_entity
                for room in self.runtime.rooms
                if self.runtime.valves[room.slug] is None
            ],
            "unavailable_external_heat_data": [
                room.name
                for room in self.runtime.rooms
                if self.runtime.external_heat_active[room.slug] is None
            ],
            "better_thermostat_guard_unsupported": [
                room.climate_entity
                for room in self.runtime.rooms
                if room.better_thermostat_extension_enabled and not self._bt_guard_supported(room)
            ],
            "unavailable_weather_inputs": self._unavailable_weather_inputs(),
            "problem_since": self._problem_since.isoformat() if self._problem_since else None,
        }


class RadiatorStressedSensor(OptimizerEntity, BinarySensorEntity):
    """Report a fully open radiator that is still behind its target."""

    _attr_name = "Radiator stressed"
    _attr_icon = "mdi:radiator-off"

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_radiator_stressed", room=room)
        self.room = room

    @property
    def available(self) -> bool:
        climate = self.hass.states.get(self.room.climate_entity)
        return self.runtime.valves[self.room.slug] is not None and climate is not None

    @property
    def is_on(self) -> bool:
        climate = self.hass.states.get(self.room.climate_entity)
        valve = self.runtime.valves[self.room.slug]
        try:
            target = float(climate.attributes["temperature"])
            current = float(climate.attributes["current_temperature"])
        except (AttributeError, KeyError, TypeError, ValueError):
            return False
        return valve is not None and valve >= 99 and target - current > 0.3

    @property
    def extra_state_attributes(self):
        """Expose the measurements captured with each stressed-state transition.

        Home Assistant keeps the attributes from the original ``off`` to ``on``
        transition while a state trigger is waiting.  Consumers can therefore
        compare the room temperature at the beginning and end of an observation
        period without duplicating the optimizer's room/entity mapping.
        """
        climate = self.hass.states.get(self.room.climate_entity)
        flow_temperature = self.runtime._flow_temperature()
        try:
            target = float(climate.attributes["temperature"])
            current = float(climate.attributes["current_temperature"])
        except (AttributeError, KeyError, TypeError, ValueError):
            target = None
            current = None
        return {
            "climate_entity": self.room.climate_entity,
            "valve_opening": self.runtime.valves[self.room.slug],
            "current_temperature": current,
            "target_temperature": target,
            "temperature_deficit": (
                round(target - current, 2) if target is not None and current is not None else None
            ),
            "flow_temperature": flow_temperature,
        }


class ExternalHeatSensor(OptimizerEntity, BinarySensorEntity):
    """Expose the guard consumed by the Better Thermostat compatibility hook."""

    _attr_name = "External heat active"
    _attr_icon = "mdi:heat-wave"

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_external_heat", room=room)
        self.room = room
        bt_object_id = room.climate_entity.split(".", 1)[1]
        self._attr_suggested_object_id = f"{bt_object_id}_ekstern_varme_aktiv"

    @property
    def available(self) -> bool:
        return self.runtime.external_heat_active[self.room.slug] is not None

    @property
    def is_on(self) -> bool:
        return self.runtime.external_heat_active[self.room.slug] is True

    @property
    def extra_state_attributes(self):
        return {
            "active_sources": self.runtime.external_heat_sources[self.room.slug],
            "better_thermostat": self.room.climate_entity,
            "learning_guard": True,
            "better_thermostat_learning_supported": bool(
                (climate := self.hass.states.get(self.room.climate_entity))
                and "thermal_learning_paused" in climate.attributes
            ),
        }


class OpeningContactSensor(OptimizerEntity, BinarySensorEntity):
    """Mirror Better Thermostat's debounced window and door state."""

    _attr_name = "Opening contact active"
    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_opening_contact", room=room)
        self.room = room

    @property
    def available(self) -> bool:
        return self.hass.states.get(self.room.climate_entity) is not None

    @property
    def is_on(self) -> bool:
        return self.runtime.contact_open[self.room.slug]

    @property
    def extra_state_attributes(self):
        climate = self.hass.states.get(self.room.climate_entity)
        attributes = climate.attributes if climate else {}
        return {
            "better_thermostat": self.room.climate_entity,
            "window_open": bool(attributes.get("window_open", False)),
            "door_open": bool(attributes.get("door_open", False)),
            "window_contact_entity": attributes.get("window_sensor_entity_id"),
            "door_contact_entity": attributes.get("door_sensor_entity_id"),
        }
