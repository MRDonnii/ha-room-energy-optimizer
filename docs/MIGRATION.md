# Migration guide

This migration is intentionally non-destructive.

1. Back up the existing YAML, helper configuration and dashboard view.
2. Install the integration through HACS and restart Home Assistant.
3. Configure the same rooms, radiator ratings, areas and source sensors.
4. Leave the old solution enabled while the new entities collect data.
5. Compare valve percentage and estimated power during idle and heating.
6. Compare the weighted room shares after meaningful valve-hours exist.
7. Point a copied dashboard view at the new entities.
8. Validate the copied view and Home Assistant configuration.
9. Disable, but do not delete, the old YAML/template entities.
10. Keep the rollback files until a full month boundary and restart have passed.

Better Thermostat remains an independent integration. Room Energy Optimizer
only reads its exposed state and attributes and never changes its learning.
