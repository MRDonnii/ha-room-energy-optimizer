# Changelog

## 1.12.0

A heat demand deviation now has to be both real and meaningful before it is
reported (the user: "Det skal altså bygges så det er brugbart og tager højde
for alt ellers bliver det en funktion jeg aldrig tør regne med"). Backtested on
30 days of a real house: 9 false "deviating" room-days before, 0 after.

- **Practical significance.** The spread is never below 5 % of the room's
  rated radiator power, at least 30 W (was 5 W). 20–60 W more in a room whose
  radiator normally idles showed as +170–400 % and "deviating"; it is now
  normal. A radiator suddenly running hundreds of watts more is still caught.
- **Similar conditions, not only similar weather.** Days are compared only
  when the share of time kept out for other heat (heat pump, stove) or an open
  window/door is within 15 percentage points of the recent window's. A stove
  keeps a room warm for hours after its excluded period, so a day without a
  fire (e.g. during a holiday) looked like high demand against fire days. When
  no learned day had such conditions the status is `learning` with the new
  reason `unusual_conditions`.
- **Confirmation.** "deviating" is only shown after it has held for 12 hours
  (meanwhile `normal` with `deviation_confirming_since`), and clears after 3
  hours back within the normal band. The pending state survives a restart.
- New attributes in watts: `recent_average_w`, `expected_average_w`,
  `difference_w`, `min_meaningful_difference_w`, plus
  `recent_other_heat_share_percent`, `compared_other_heat_share_percent` and
  `deviation_confirming_since`.
- Includes 1.11.0 (setpoint changes are learning). (Change by Claude AI.)

## 1.11.0

- A setpoint change is learning, not a deviation. Raising the setpoint made
  the heat-up (the radiator also warming walls and furniture) count as high
  demand, and lowering it made the cool-down count as low demand, so a room
  could show "deviating" right after the temperature was changed. Now a change
  of at least 0.5 °C starts a transition: until the room is within 0.3 °C of
  its new target (at most 12 h) and two hours after that, its samples are left
  out of the energy balance and the status is `learning` with the reason
  `setpoint_changed` (attributes `setpoint_transition`,
  `setpoint_transition_since`). Afterwards the room is judged afresh.
- Recorder history is replayed with the same rule (the climate's `temperature`
  attribute is now part of the replay), and a running transition survives a
  restart. (Change by Claude AI; the user: "hvis temperatur setpoint ændres så
  skal den også justere og se det som en indlæring".)

## 1.10.0

- Built-in Better Thermostat learning guard. Rooms with the Better Thermostat
  extension enabled now pause Better Thermostat's thermal learning while
  external heat (heat pump, stove, …) is active, and publish
  `thermal_learning_paused` / `external_heat_entity_id` on the climate.
  Previously this needed a separate guard that was never published, so Data
  problem reported `better_thermostat_guard_unsupported` for everyone else.
- Supports Better Thermostat 1.x and 2.x (2.0 renamed the trackers'
  `start_temp`/`end_temp` to `start_temperature`/`end_temperature`).
- A climate that is already guarded (e.g. by a stand-alone guard) is left
  alone. (Change by Claude AI.)

## 1.9.4

- Radiator alerts sent to a phone (a mobile app notify entity) carry their own
  icon: they go through the phone's `notify.mobile_app_*` service with
  `notification_icon: mdi:radiator` and a red colour, so iOS shows them as a
  communication notification with a radiator avatar instead of the Home
  Assistant icon. Other notify entities still get `notify.send_message`.
  (Change by Claude AI.)

## 1.9.3

- Remove entities that this configuration no longer creates. Older versions
  created the Better Thermostat sensors (external heat, opening contact) and
  the experimental cascade sensor for every room, and nothing removed them
  once they were created only where used, so they stayed behind as permanently
  unavailable entities. The integration now removes such leftovers when it
  starts, and the entities of a room that is removed in the options. Entities
  the user has disabled are kept, and nothing is removed if one of the
  platforms failed to set up. (Fix by Claude AI.)

## 1.9.2

- Include the English runtime translation so the notification switch has a
  clear name in Home Assistant installations using English as the core language.
- Expose the radiator-alert observation time as a persistent number entity, so
  it can be changed directly from dashboards and automations.
- Allow the notification language to follow Home Assistant or be set to Danish
  or English for the chosen recipient.

## 1.9.1

- Add optional radiator-stress notifications with a configurable notify entity
  and observation time.
- Add a persistent switch on the integration device to turn these messages on
  and off without disabling radiator monitoring. Notifications default to off.
- Limit each continuous stress period to one message and require insufficient
  temperature progress after the observation interval.

## 1.9.0

- Replace the heat-demand model. Its learned baseline started from the very
  first sample and, with a 120-hour half-life, kept most of that sample's
  weight for weeks, so steady rooms were reported as `deviating` as soon as
  learning finished.
- Heat demand is now an energy balance: estimated radiator energy over the
  last 48 hours divided by the room/outdoor degree-hours (W/°C). Closed
  radiators count as zero output and the actual room temperature is used
  instead of the target.
- The status compares that value with the room's own completed days that had
  similar weather (room/outdoor difference within 3 °C, then similar wind):
  their median and robust spread, with hysteresis. It says why it is still
  learning, including weather it has not seen yet, and a radiator that
  normally idles is now normal instead of a division problem.
- Add an optional wind speed sensor, used to prefer days with similar wind.
- Leave external-heat and open window/door periods out for one extra hour, and
  honour Better Thermostat's window/door state for every room.
- Rebuild the energy balance from recorder history on the first start and for
  new rooms.
- Add a per-room "Heat demand per degree" sensor.
- Report unavailable outdoor temperature and wind sensors as a data problem.
- Register the hub device before the room devices that point at it (Home
  Assistant rejects the reverse order from 2025.12), and link them by
  registry id on Home Assistant 2026.8 and later, where the identifier form
  is deprecated.
- Run the Home Assistant integration tests in CI.

## 1.8.2

- Expose the climate entity, valve opening, room temperature, target,
  temperature deficit and flow temperature on each radiator-stressed binary
  sensor so downstream automations can evaluate progress over an observation
  period.

## 1.8.1

- Fix Home Assistant translation validation for the per-room system inheritance option.
- Fix the Python 3.12/ruff type-annotation check and add inheritance normalisation coverage.

## 1.8.0

- Stabilise heat-demand diagnostics with a six-hour recent EMA instead of 30 minutes.
- Ignore closed/idle radiator samples so zero output is not reported as poor consumption.
- Require six active observation hours and use 50%/30% hysteresis before changing status.
- Migrate away from the old idle-polluted derived baseline without resetting room setup or valve-hours.

## 1.7.0

- Add per-room one-pipe/two-pipe overrides for mixed heating installations.
- Add experimental one-pipe loop-order and cascade-output diagnostics.

## 1.6.0

- Made the Better Thermostat extension an explicit per-room opt-in switch.
- New rooms default to the standalone energy features only.
- Existing rooms with external-heat sources are migrated as enabled.
- Guard and opening-contact entities are only created for opted-in rooms.

## 1.5.3

- Fixed the optional stove entity selector so rooms without a stove can be
  edited and saved through Home Assistant's options flow.

## 1.5.2

- Save immediately after editing one room. This makes each edit atomic and
  gives API clients the same reliable flow as the Home Assistant GUI.

## 1.5.1

- Added in-place room editing to the options GUI, including all external-heat
  and stove settings, without deleting the room or resetting its stored data.

## 1.5.0

- Added optional heat-pump, binary external-heat and stove-temperature
  configuration per room, including stove hysteresis.
- Added external-heat and opening-contact binary sensors per room.
- Better Thermostat's debounced window/door state is consumed automatically.
- External-heat and open-contact periods no longer feed the learned demand baseline.
- Data health now detects missing external inputs and missing BT guard support.
- Fixed two Ruff formatting failures introduced with the 1.4.0 setup wizard.

## 1.4.0

- Setup and editing now add rooms one at a time through a proper wizard step
  (name, a climate entity picker, rated radiator output, room area and
  number of radiators) instead of one free-text field with pipe-delimited
  lines.
- Added a "Number of radiators" field and matching per-room sensor. It is
  informational only for now; the power estimate still uses the room's
  combined rated output, not a per-radiator split.
- The options flow can now add or remove rooms after setup without retyping
  the ones you already have.
- Existing installs are migrated automatically on first load of this
  version: the old pipe-delimited rooms string is parsed once and saved back
  in the new format. Valve-hours and the heat-demand baseline are keyed by
  room slug and are unaffected.

## 1.3.1

- Renamed the shared hub device from the entry title alone (identical to the
  integration's own name) to "<title> (Totals)", so it no longer looks like
  an eighth, unnamed room in the device list next to the per-room devices.

## 1.3.0

- Each room now gets its own device, so it shows as its own entry (its own
  "tab") under Settings -> Devices & services instead of one shared device
  holding every room's entities.
- Added an optional outdoor temperature sensor setting and a new per-room
  "Heat demand status" sensor (`learning` / `normal` / `deviating`). It
  compares a room's live watt-per-degree-of-lift ratio against that same
  room's own learned baseline, so the comparison is normalised for how cold
  it is outside rather than a fixed threshold.
- The status sensor reports `learning` until a room has collected enough
  hours of valid samples (default 48h) to have a meaningful baseline.
- Existing installs are unaffected until the optional outdoor sensor is set;
  without it the new sensor stays unavailable and nothing else changes.

## 1.2.0

- Added a rated radiator output sensor for every room.
- Added a learned heat-loss sensor sourced read-only from Better Thermostat.
- Added a radiator-stressed binary sensor when the valve is at least 99% open
  and the room remains more than 0.3 °C below target.
- These additions complete migration of the room-energy dashboard away from
  YAML template sensors. Better Thermostat control and learning are unchanged.

## 1.1.1 — 2026-09-08

- Accept Better Thermostat `calibration_balance` as either JSON text or an object.

## 1.1.0 — 2026-09-08

- Added optional migration seeds for existing month-to-date valve-hours.
- Added an optional monthly-cost baseline entity for mid-month migration.

## 1.0.1 — 2026-09-08

- Added HACS-required repository metadata, issue tracker and brand asset layout.

## 1.0.0 — 2026-09-08

- First HACS-installable release.
- Added UI configuration for one-pipe and two-pipe radiator systems.
- Added per-room valve, valve-hour, power, capacity, share, cost and area sensors.
- Added persistent month-to-date valve-hour storage with month rollover.
- Added total heat-demand and data-health entities.
- Added Danish and English UI text, diagnostics and safe migration guidance.
- Added branded logo and icon.
- Explicitly excluded Better Thermostat patches and control of heating equipment.
