# Changelog

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
