"""Health sensor for Room Energy Optimizer."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .const import CONF_FLOW_TEMPERATURE, DOMAIN
from .entity import OptimizerEntity


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    async_add_entities([DataHealthSensor(hass.data[DOMAIN][entry.entry_id])])


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
