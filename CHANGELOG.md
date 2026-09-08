# Changelog

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
