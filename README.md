# Room Energy Optimizer

Heat-demand status is deliberately slow and diagnostic. Since 1.9.0 it is an
energy balance: the estimated radiator energy of the last 48 hours divided by
the degree-hours between room and outdoor temperature (W/°C), compared with the
room's own completed days. Closed radiators count as zero output, periods with
external heat or an open window/door are left out, and the status only changes
when the room leaves its own normal day-to-day spread. On the first start of
1.9.0 the history is rebuilt from the recorder, so no new learning period is
needed.

Room Energy Optimizer turns existing Home Assistant climate and temperature
data into understandable room-by-room heating estimates. It is designed for
hydronic radiator systems, including one-pipe installations where a shared
return temperature is not a reliable representation of an individual
radiator.

The integration never changes thermostat setpoints, valves or heating
equipment. It reads Better Thermostat's public attributes and can optionally
publish an external-heat learning guard. A cold room can therefore keep
receiving radiator heat while unreliable learning samples are discarded.

**Current version: 1.9.2**

## What it provides

Each configured room gets its own device (its own page under Settings ->
Devices & services), with:

- calculated valve opening;
- persistent valve-hours for the current month;
- estimated radiator output in watts;
- capacity utilisation;
- weighted monthly heating share;
- optional estimated monthly cost;
- configured room area;
- rated radiator output and learned heat loss (read from Better Thermostat);
- a radiator-stressed binary sensor;
- an optional weather-normalised heat demand status and heat demand per
  degree sensor (see below).

It also creates a total estimated heat-demand sensor and a data-health binary
sensor on a shared hub device. All calculations fail visibly when required
source data is missing.

### Radiator-stressed diagnostic

The per-room radiator-stressed binary sensor is a raw diagnostic signal. It is
active while the calculated valve opening is at least 99% and the room remains
more than 0.3 °C below its target. Its attributes include the climate entity,
valve opening, current and target temperatures, temperature deficit and the
configured flow temperature. Automations can use the values captured on the
state transition to compare temperature progress over their own observation
period.

### Optional radiator notifications

Select a `notify` entity in the integration's Configure screen. The **Radiator
stress notifications** switch and **Radiator alert observation time** number
appear on the integration's shared device. Set the number from 1 to 1440
minutes. Notifications default to off until the switch is turned on. Both
settings survive a restart.

The integration sends at most one message per continuous stress period after
the selected observation time. It requires the valve to remain at least 99%
open, the room to remain more than 0.3 °C below target, and the temperature
to have risen less than 0.2 °C. Monitoring continues when messages are off.
An alert from an older user-created automation is independent of this switch;
disable or remove that automation when moving its notifications into the
integration.

## Heat demand status (optional)

Set an outdoor temperature sensor in the configuration to enable two per-room
sensors:

- **Heat demand per degree** (W/°C): the estimated radiator energy over the
  last 48 hours divided by the degree-hours between room and outdoor
  temperature in the same period. Minutes with a closed radiator count as zero
  output, so a room that heats longer or shorter than usual changes the value.
- **Heat demand status** with three states:
  - `learning` - not enough data yet (the `reason` attribute says why:
    fewer than seven valid days, an incomplete 48-hour window, or weather too
    mild for a meaningful ratio);
  - `normal` - the recent value lies within the room's own normal spread;
  - `deviating` - it lies more than three robust standard deviations from the
    room's normal, and stays so until it is back within two.

The normal is learned per room from its own completed days (up to 28 days,
each with at least 12 clean hours and a mean room/outdoor difference of at
least 3 °C). Only days with weather like the recent window's are compared:
their mean room/outdoor difference must be within 3 °C, and the closest ones
are chosen, with wind as a tie-breaker when a wind speed sensor is configured.
At least five such days are needed; otherwise the status stays `learning`
with the reason `outside_learned_weather` rather than guessing. This matters
because a room's W/°C naturally rises in colder weather, when free heat from
people, appliances and sun covers less of the loss. The normal is the median
of the compared days and the spread their median absolute deviation, never
below 10 % of the normal or 5 W of average output. Samples taken while
external heat is active or a window/door is open - and for one hour
afterwards - are left out.

On the first start of 1.9.0, and for rooms added later, the energy balance is
rebuilt from up to 10 days of recorder history, so the status is available
immediately when enough history exists.

A sustained `deviating` state can indicate a stuck valve, a window or door left
open, air in the radiator, a changed setpoint, or a miscalibrated rated
power/area value. The numbers are estimates from valve opening, flow
temperature and rated radiator output, not heat-meter readings; they are best
used to compare a room with itself over time.

## Better Thermostat, external heat and opening contacts

The Better Thermostat extension is explicitly optional and disabled by default
for new rooms. The energy, valve-hours and cost features work without it.
When enabled for a room, you can optionally select heat-pump climate entities, external-
heat binary sensors, and a stove temperature sensor with separate on/off
thresholds. Climate sources count only while `hvac_action` is `heating`; the
stove thresholds use hysteresis.

External-heat periods are excluded from the integration's learned demand
baseline and publish a Better Thermostat learning guard. Radiator control and
target temperatures are left untouched. Better Thermostat's debounced
`window_open` and `door_open` attributes are mirrored automatically, and
open-contact periods are excluded from baseline learning too.

Pausing Better Thermostat's internal learner requires a compatible Better
Thermostat build exposing `thermal_learning_paused`. Data problem reports a
missing hook explicitly instead of silently claiming that learning is paused.

## Installation with HACS

1. Open HACS → Integrations → three-dot menu → Custom repositories.
2. Add `https://github.com/MRDonnii/ha-room-energy-optimizer` as an Integration.
3. Download **Room Energy Optimizer** and restart Home Assistant.
4. Open Settings → Devices & services → Add integration → Room Energy Optimizer.

Until this repository is accepted into the default HACS catalog, the custom
repository step is required.

## Configuration

Setup is a short wizard:

1. Choose the heating system type, a flow-temperature sensor, and optionally
   an outdoor temperature sensor and monthly-cost sensors.
2. Add rooms one at a time: name, a climate entity picker, rated radiator
   output (W), room area (m²), and number of radiators. Tick "Add another
   room" to keep going, or leave it unticked to finish.

A room's "Existing valve-hours this month" field is only for migrating an
older setup mid-month; leave it at 0 for a normal new room. It is only used
when no saved value exists yet for the current month.

An optional outdoor temperature sensor enables the heat demand sensors
described above, and an optional wind speed sensor (m/s, km/h, mph, kn or
Beaufort) lets them prefer days with similar wind.

An optional monthly heating-cost sensor can be selected by entity ID. Its
value is allocated using monthly valve-hours multiplied by rated radiator
power, not valve-hours alone. An optional baseline entity can subtract costs
that predate installation during the first month.

### Editing rooms later

Settings → Devices & services → Room Energy Optimizer → Configure opens the
same settings screen, followed by a "Manage rooms" screen where you can add
a room (same one-at-a-time wizard) or remove one by name. There is currently
no in-place edit for a single room's numbers - remove it and add it again
with the corrected values; its accumulated valve-hours and heat-demand
baseline are keyed by room name and survive that.

### Upgrading from 1.3.x or earlier

The old `Name|climate.entity|watts|area` text field is migrated
automatically the first time this version loads - nothing to do by hand.

## Calculation limits

The watt values are engineering estimates, not heat-meter measurements. For a
one-pipe system, the integration deliberately ignores a shared return sensor
and estimates radiator return from the 70/40/20 reference relationship. Exact
room-level energy requires flow and temperature measurement at each radiator.

## Safe migration from an existing YAML solution

Install and configure this integration in parallel. Compare its entities with
the existing solution through at least one heating cycle. Move dashboard cards
only after values agree. Disable the old YAML only after validation; keep a
rollback copy. Do not delete history or helpers during the initial migration.

See [Migration guide](docs/MIGRATION.md) for a detailed checklist.

## Privacy

The repository contains no private entity IDs, network addresses, credentials
or household-specific values. Diagnostics omit source entity IDs and current
sensor values.

## License

MIT
