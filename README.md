# Room Energy Optimizer

Room Energy Optimizer turns existing Home Assistant climate and temperature
data into understandable room-by-room heating estimates. It is designed for
hydronic radiator systems, including one-pipe installations where a shared
return temperature is not a reliable representation of an individual
radiator.

The integration is **read-only**. It never changes thermostat setpoints,
valves or heating equipment. It reads Better Thermostat's public
`calibration_balance` attribute when available, but contains no Better
Thermostat patch, learning override or copied Better Thermostat code.

**Current version: 1.3.0**

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
- an optional weather-normalised heat demand status (see below).

It also creates a total estimated heat-demand sensor and a data-health binary
sensor on a shared hub device. All calculations fail visibly when required
source data is missing.

## Heat demand status (optional)

Set an outdoor temperature sensor in the configuration to enable a per-room
"Heat demand status" sensor with three states:

- `learning` - not enough data yet to judge (default: 48 hours of valid
  samples);
- `normal` - the room's current heat output per degree of indoor/outdoor
  temperature difference is close to its own learned baseline;
- `deviating` - it has moved more than 40% away from that baseline.

The baseline is learned per room from its own history, not a fixed
house-wide number, and is weather-normalised so a cold day does not by
itself look like a deviation. A sustained `deviating` state can indicate a
stuck valve, an open window, air in the radiator, or a miscalibrated rated
power/area value.

## Installation with HACS

1. Open HACS → Integrations → three-dot menu → Custom repositories.
2. Add `https://github.com/MRDonnii/ha-room-energy-optimizer` as an Integration.
3. Download **Room Energy Optimizer** and restart Home Assistant.
4. Open Settings → Devices & services → Add integration → Room Energy Optimizer.

Until this repository is accepted into the default HACS catalog, the custom
repository step is required.

## Configuration

Choose the heating system type and a flow-temperature sensor. Add one room per
line using:

```text
Living room|climate.living_room|2000|30
Bedroom|climate.bedroom|1000|15
```

The fields are room name, climate entity, rated radiator output in watts and
room area in square metres. Decimal comma and decimal point are accepted.
During migration, a fifth field can seed already accumulated valve-hours:

```text
Living room|climate.living_room|2000|30|12.45
```

The seed is only used when no saved value exists for the current month.

An optional outdoor temperature sensor entity ID enables the heat demand
status sensor described above.

An optional monthly heating-cost sensor can be selected by entity ID. Its
value is allocated using monthly valve-hours multiplied by rated radiator
power, not valve-hours alone. An optional baseline entity can subtract costs
that predate installation during the first month.

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
