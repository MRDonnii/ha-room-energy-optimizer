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
        return (
            flow is None
            or flow.state in ("unknown", "unavailable")
            or any(value is None for value in self.runtime.valves.values())
        )

    @property
    def extra_state_attributes(self):
        return {
            "missing_valve_data": [
                room.climate_entity
                for room in self.runtime.rooms
                if self.runtime.valves[room.slug] is None
            ]
        }


class RadiatorStressedSensor(OptimizerEntity, BinarySensorEntity):
    """Report a fully open radiator that is still behind its target."""

    _attr_name = None
    _attr_icon = "mdi:radiator-off"

    def __init__(self, runtime, room) -> None:
        super().__init__(runtime, f"{room.slug}_radiator_stressed")
        self.room = room
        self._attr_name = f"{room.name} Radiator stressed"

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
