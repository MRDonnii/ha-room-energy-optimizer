"""Health sensor for Room Energy Optimizer."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .const import CONF_FLOW_TEMPERATURE, DOMAIN
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


class DataHealthSensor(OptimizerEntity, BinarySensorEntity):
    _attr_name = "Data problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, runtime) -> None:
        super().__init__(runtime, "data_problem")

    @property
    def is_on(self) -> bool:
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
        )

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
