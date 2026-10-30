"""Constants for Room Energy Optimizer."""

DOMAIN = "room_energy_optimizer"
PLATFORMS = ["sensor", "binary_sensor", "switch", "number"]
VERSION = "1.12.0"

CONF_SYSTEM_TYPE = "system_type"
CONF_FLOW_TEMPERATURE = "flow_temperature_entity"
CONF_OUTDOOR_TEMPERATURE = "outdoor_temperature_entity"
CONF_WIND_SPEED = "wind_speed_entity"
CONF_MONTHLY_COST = "monthly_cost_entity"
CONF_MONTHLY_COST_BASELINE = "monthly_cost_baseline_entity"
CONF_ROOMS = "rooms"
CONF_ALERT_NOTIFY_ENTITY = "alert_notify_entity"
ALERT_NOTIFY_ICON = "mdi:radiator"
ALERT_NOTIFY_COLOR = "#ef4444"
CONF_ALERT_LANGUAGE = "alert_language"
CONF_ALERT_OBSERVATION_MINUTES = "alert_observation_minutes"
DEFAULT_ALERT_OBSERVATION_MINUTES = 60
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
SYSTEM_INHERIT = "inherit"
DEFAULT_SCAN_INTERVAL = 60

# Weather-normalised heat demand (model v3, see model.DemandModel).
# A room's demand is the estimated radiator energy divided by the degree-hours
# between room and outdoor temperature (W/°C, an energy signature). Closed
# radiators count as zero output, so a longer or shorter heating duty cycle
# shows up; periods with external heat or an open window/door are left out,
# including a short settling tail after they end.
HEAT_DEMAND_MODEL_VERSION = 3
HEAT_DEMAND_RECENT_WINDOW_HOURS = 48
HEAT_DEMAND_MIN_RECENT_CLEAN_HOURS = 24.0
HEAT_DEMAND_MIN_MEAN_LIFT = 3.0
HEAT_DEMAND_HISTORY_DAYS = 28
HEAT_DEMAND_KEEP_DAYS = 45
HEAT_DEMAND_MIN_VALID_DAYS = 7
HEAT_DEMAND_MIN_DAY_CLEAN_HOURS = 12.0
HEAT_DEMAND_EXCLUSION_TAIL_HOURS = 1.0
# A setpoint change of at least this much starts a transition: until the room is within the
# tolerance of its new target (at most the max hours) and a tail after that, its samples are
# kept out of the balance and the room shows "learning" (reason "setpoint_changed"). Heating
# up to a higher setpoint also warms walls and furniture, and after a lower one the radiator
# stays closed while the room cools; neither is the room's normal demand. Claude AI, 2026-10-30.
HEAT_DEMAND_SETPOINT_MIN_CHANGE_C = 0.5
HEAT_DEMAND_SETPOINT_TOLERANCE_C = 0.3
HEAT_DEMAND_SETPOINT_MAX_HOURS = 12.0
HEAT_DEMAND_SETPOINT_TAIL_HOURS = 2.0
# The recent window is compared with the learned days whose weather was most
# like it: room/outdoor difference within a few degrees, then similar wind.
# That keeps the seasonal rise in W/°C (free heat from people, appliances and
# sun matters less when it is colder) from looking like a fault.
HEAT_DEMAND_SIMILAR_MAX_LIFT_DIFF = 3.0
HEAT_DEMAND_SIMILAR_WIND_SCALE_MS = 2.0
# Only days where other heat (heat pump, stove) or open windows/doors kept out a similar share
# of the time are compared. A stove keeps a room warm for hours after its excluded period, so
# days with a fire need less radiator heat than days without; comparing a day without a fire
# with fire days made a normal day look like high demand. 0.1 share weighs like 1 °C.
HEAT_DEMAND_SIMILAR_MAX_SHARE_DIFF = 0.15
HEAT_DEMAND_SIMILAR_SHARE_SCALE = 0.1
HEAT_DEMAND_MIN_SIMILAR_DAYS = 5
HEAT_DEMAND_MAX_SIMILAR_DAYS = 10
# Status changes when the recent value leaves the room's own day-to-day spread
# (robust z-score); hysteresis keeps it from flapping around the boundary.
HEAT_DEMAND_Z_ENTER = 3.0
HEAT_DEMAND_Z_EXIT = 2.0
HEAT_DEMAND_MIN_RELATIVE_SPREAD = 0.1
# A radiator that normally idles may vary by this much average output (was 5 W, which let
# 30–40 W of extra output in a room with a near-zero normal count as a deviation).
HEAT_DEMAND_MIN_SPREAD_W = 30.0
# On the first start of model v3 the recorder history is replayed once.
HEAT_DEMAND_BACKFILL_DAYS = 10
# Practical significance (Claude AI, 2026-10-30; the user: "Det skal altså bygges så det er
# brugbart og tager højde for alt"): a radiator that normally idles can easily vary by tens of
# watts, which is nothing, but against a normal near zero it looked like +400 %. The spread is
# never below this share of the room's rated radiator power (nor HEAT_DEMAND_MIN_SPREAD_W).
HEAT_DEMAND_MIN_SPREAD_RATED_FRACTION = 0.05
# A deviation must last this long before the status says "deviating" (and be back within the
# exit band this long before it clears), so a single odd day or evening never raises it.
HEAT_DEMAND_CONFIRM_DEVIATING_HOURS = 12.0
HEAT_DEMAND_CONFIRM_NORMAL_HOURS = 3.0
