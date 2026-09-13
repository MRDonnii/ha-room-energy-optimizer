"""Constants for Room Energy Optimizer."""

DOMAIN = "room_energy_optimizer"
PLATFORMS = ["sensor", "binary_sensor"]
VERSION = "1.8.0"

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
# Per-room override of the house-wide system_type, for a mixed installation
# (e.g. most rooms share a one-pipe loop, but a couple of rooms are on their
# own dedicated two-pipe branch). Empty string means "inherit system_type".
CONF_ROOM_SYSTEM_TYPE = "system_type_override"
# Free-text, one entry per line ("label" or "label|room_slug"): the physical
# flow order of a one-pipe loop. Feeds the EXPERIMENTAL cascade sensors only
# (see model.cascade_flow_temperature) - the main estimate for each room
# still uses system_type/system_type_override, not this.
CONF_LOOP_ORDER = "loop_order"
# Assumed °C the flow temperature drops at each stop along the one-pipe loop.
# Unvalidated default - nothing in this integration measures it.
CONF_LOOP_DROP_PER_STATION = "loop_drop_per_station_c"
DEFAULT_LOOP_DROP_PER_STATION = 2.0

SYSTEM_ONE_PIPE = "one_pipe"
SYSTEM_TWO_PIPE = "two_pipe"
DEFAULT_SCAN_INTERVAL = 60

# Weather-normalised heat-demand baseline (see model.classify_heat_demand).
# A room's live W/°C-lift ratio is tracked as a fast (recent) and a slow
# (baseline) exponential moving average. The baseline needs this many hours
# of valid samples before a comparison is considered meaningful.
HEAT_DEMAND_RECENT_HALF_LIFE_HOURS = 6.0
HEAT_DEMAND_BASELINE_HALF_LIFE_HOURS = 120.0
HEAT_DEMAND_MIN_BASELINE_HOURS = 48.0
HEAT_DEMAND_MIN_RECENT_HOURS = 6.0
HEAT_DEMAND_DEVIATION_ENTER_THRESHOLD = 0.5
HEAT_DEMAND_DEVIATION_EXIT_THRESHOLD = 0.3
HEAT_DEMAND_MIN_DELTA = 2.0
# Idle radiators are not evidence of unusually low heat demand. Only samples
# with a genuinely open valve and measurable estimated output feed the model.
HEAT_DEMAND_MIN_VALVE_PERCENT = 10.0
HEAT_DEMAND_MIN_POWER_W = 20.0
HEAT_DEMAND_MODEL_VERSION = 2
