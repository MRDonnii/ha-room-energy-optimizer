"""Constants for Room Energy Optimizer."""

DOMAIN = "room_energy_optimizer"
PLATFORMS = ["sensor", "binary_sensor"]
VERSION = "1.5.2"

CONF_SYSTEM_TYPE = "system_type"
CONF_FLOW_TEMPERATURE = "flow_temperature_entity"
CONF_OUTDOOR_TEMPERATURE = "outdoor_temperature_entity"
CONF_MONTHLY_COST = "monthly_cost_entity"
CONF_MONTHLY_COST_BASELINE = "monthly_cost_baseline_entity"
CONF_ROOMS = "rooms"
CONF_EXTERNAL_HEAT_ENTITIES = "external_heat_entities"
CONF_STOVE_TEMPERATURE = "stove_temperature_entity"
CONF_STOVE_ON_TEMPERATURE = "stove_on_temperature"
CONF_STOVE_OFF_TEMPERATURE = "stove_off_temperature"

SYSTEM_ONE_PIPE = "one_pipe"
SYSTEM_TWO_PIPE = "two_pipe"
DEFAULT_SCAN_INTERVAL = 60

# Weather-normalised heat-demand baseline (see model.classify_heat_demand).
# A room's live W/°C-lift ratio is tracked as a fast (recent) and a slow
# (baseline) exponential moving average. The baseline needs this many hours
# of valid samples before a comparison is considered meaningful.
HEAT_DEMAND_RECENT_HALF_LIFE_HOURS = 0.5
HEAT_DEMAND_BASELINE_HALF_LIFE_HOURS = 120.0
HEAT_DEMAND_MIN_BASELINE_HOURS = 48.0
HEAT_DEMAND_DEVIATION_THRESHOLD = 0.4
HEAT_DEMAND_MIN_DELTA = 2.0
