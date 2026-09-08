"""Constants for Room Energy Optimizer."""

DOMAIN = "room_energy_optimizer"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_SYSTEM_TYPE = "system_type"
CONF_FLOW_TEMPERATURE = "flow_temperature_entity"
CONF_MONTHLY_COST = "monthly_cost_entity"
CONF_ROOMS = "rooms"

SYSTEM_ONE_PIPE = "one_pipe"
SYSTEM_TWO_PIPE = "two_pipe"
DEFAULT_SCAN_INTERVAL = 60
