"""Config flow for Room Energy Optimizer.

Rooms are configured one at a time through a small repeating wizard step
(`async_step_add_room`) instead of one free-text field, so each room gets
proper entity/number pickers and inline validation. `RoomWizardSteps` holds
that shared step so both the initial setup flow and the later options flow
use the same one-room-at-a-time form.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_FLOW_TEMPERATURE,
    CONF_MONTHLY_COST,
    CONF_MONTHLY_COST_BASELINE,
    CONF_OUTDOOR_TEMPERATURE,
    CONF_ROOMS,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_ONE_PIPE,
    SYSTEM_TWO_PIPE,
)
from .model import room_from_dict, room_to_dict, rooms_from_options, slugify


def _settings_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Room Energy Optimizer")): str,
            vol.Required(
                CONF_SYSTEM_TYPE, default=defaults.get(CONF_SYSTEM_TYPE, SYSTEM_ONE_PIPE)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[SYSTEM_ONE_PIPE, SYSTEM_TWO_PIPE],
                    translation_key=CONF_SYSTEM_TYPE,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_FLOW_TEMPERATURE, default=defaults.get(CONF_FLOW_TEMPERATURE)
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Optional(
                CONF_OUTDOOR_TEMPERATURE, default=defaults.get(CONF_OUTDOOR_TEMPERATURE, "")
            ): str,
            vol.Optional(CONF_MONTHLY_COST, default=defaults.get(CONF_MONTHLY_COST, "")): str,
            vol.Optional(
                CONF_MONTHLY_COST_BASELINE,
                default=defaults.get(CONF_MONTHLY_COST_BASELINE, ""),
            ): str,
        }
    )


def _validate_settings(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    for key in (CONF_OUTDOOR_TEMPERATURE, CONF_MONTHLY_COST, CONF_MONTHLY_COST_BASELINE):
        entity_id = user_input.get(key, "").strip()
        if entity_id and not entity_id.startswith(("sensor.", "input_number.")):
            errors[key] = "invalid_sensor"
    return errors


def _room_schema(defaults: dict[str, Any] | None = None, *, adding: bool = True) -> vol.Schema:
    defaults = defaults or {}

    def required(key: str, fallback=vol.UNDEFINED):
        value = defaults.get(key, fallback)
        return vol.Required(key) if value is vol.UNDEFINED else vol.Required(key, default=value)

    fields: dict[Any, Any] = {
            required("name"): str,
            required("climate_entity"): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            required("rated_power_w"): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=20000,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="W",
                )
            ),
            required("area_m2"): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=500,
                    step=0.1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="m²",
                )
            ),
            required("radiator_count", 1): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1, max=20, step=1, mode=selector.NumberSelectorMode.BOX
                )
            ),
            vol.Optional(
                "initial_valve_hours", default=defaults.get("initial_valve_hours", 0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    step=0.01,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="h",
                )
            ),
            vol.Optional(
                "external_heat_entities", default=defaults.get("external_heat_entities", [])
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["binary_sensor", "climate"], multiple=True
                )
            ),
            (
                vol.Optional(
                    "stove_temperature_entity",
                    default=defaults["stove_temperature_entity"],
                )
                if defaults.get("stove_temperature_entity")
                else vol.Optional("stove_temperature_entity")
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                "stove_on_temperature", default=defaults.get("stove_on_temperature", 25)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=0.1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
            vol.Optional(
                "stove_off_temperature", default=defaults.get("stove_off_temperature", 24)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=0.1,
                    mode=selector.NumberSelectorMode.BOX,
                    unit_of_measurement="°C",
                )
            ),
    }
    if adding:
        fields[vol.Required("add_another_room", default=True)] = selector.BooleanSelector()
    return vol.Schema(fields)


class RoomWizardSteps:
    """Shared one-room-at-a-time step for config and options flows.

    A subclass sets `self._rooms` (list of room dicts already configured in
    this flow session) and `self._after_rooms_step` (the step name to return
    to once the user stops adding rooms) before entering `async_step_add_room`.
    """

    _rooms: list[dict[str, Any]]
    _after_rooms_step: str

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            add_another = bool(user_input.pop("add_another_room", True))
            existing_slugs = {slugify(room["name"]) for room in self._rooms}
            try:
                room = room_from_dict(user_input, existing_slugs)
            except ValueError:
                errors["base"] = "invalid_room"
            else:
                self._rooms.append(room_to_dict(room))
                if add_another:
                    return await self.async_step_add_room()
                return await getattr(self, f"async_step_{self._after_rooms_step}")()
        return self.async_show_form(
            step_id="add_room",
            data_schema=_room_schema(),
            errors=errors,
            description_placeholders={
                "room_number": str(len(self._rooms) + 1),
                "rooms_so_far": ", ".join(room["name"] for room in self._rooms) or "–",
            },
        )


class RoomEnergyOptimizerConfigFlow(
    config_entries.ConfigFlow, RoomWizardSteps, domain=DOMAIN
):
    """Set up the integration: settings once, then rooms one at a time."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._rooms: list[dict[str, Any]] = []
        self._after_rooms_step = "finish"

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_settings(user_input)
            if not errors:
                await self.async_set_unique_id("main")
                self._abort_if_unique_id_configured()
                self._data = user_input
                return await self.async_step_add_room()
        return self.async_show_form(
            step_id="user", data_schema=_settings_schema(user_input or {}), errors=errors
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        title = self._data.pop(CONF_NAME)
        options = {**self._data, CONF_ROOMS: self._rooms}
        return self.async_create_entry(title=title, data={}, options=options)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow, RoomWizardSteps):
    """Edit settings, then add or remove rooms one at a time."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._data: dict[str, Any] = {}
        # `rooms_from_options` + `room_to_dict` also tolerates a still-legacy
        # string here (defensive only - `_async_migrate_room_storage` in
        # __init__.py normally converts it before this flow can be opened).
        self._rooms: list[dict[str, Any]] = [
            room_to_dict(room)
            for room in rooms_from_options(config_entry.options.get(CONF_ROOMS, []))
        ]
        self._after_rooms_step = "manage_rooms"

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_settings(user_input)
            if not errors:
                user_input.pop(CONF_NAME, None)
                self._data = user_input
                return await self.async_step_manage_rooms()
        defaults = {CONF_NAME: self._entry.title, **self._entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_settings_schema(user_input or defaults), errors=errors
        )

    async def async_step_manage_rooms(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            action = user_input["action"]
            if action == "add":
                return await self.async_step_add_room()
            if action == "edit":
                return await self.async_step_select_room_to_edit()
            if action == "remove":
                return await self.async_step_remove_room()
            options = {**self._data, CONF_ROOMS: self._rooms}
            return self.async_create_entry(title="", data=options)
        room_names = ", ".join(room["name"] for room in self._rooms) or "–"
        return self.async_show_form(
            step_id="manage_rooms",
            data_schema=vol.Schema(
                {
                    vol.Required("action", default="done"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=["add", "edit", "remove", "done"],
                            translation_key="manage_rooms_action",
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"rooms_so_far": room_names},
        )

    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None):
        if not self._rooms:
            return await self.async_step_manage_rooms()
        if user_input is not None:
            self._rooms = [room for room in self._rooms if room["name"] != user_input["room"]]
            return await self.async_step_manage_rooms()
        return self.async_show_form(
            step_id="remove_room",
            data_schema=vol.Schema(
                {
                    vol.Required("room"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[room["name"] for room in self._rooms],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_select_room_to_edit(self, user_input=None):
        if user_input is not None:
            self._editing_room_name = user_input["room"]
            return await self.async_step_edit_room()
        return self.async_show_form(
            step_id="select_room_to_edit",
            data_schema=vol.Schema(
                {
                    vol.Required("room"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[room["name"] for room in self._rooms],
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_edit_room(self, user_input=None):
        current = next(room for room in self._rooms if room["name"] == self._editing_room_name)
        errors: dict[str, str] = {}
        if user_input is not None:
            existing_slugs = {
                slugify(room["name"])
                for room in self._rooms
                if room["name"] != self._editing_room_name
            }
            try:
                updated = room_from_dict(user_input, existing_slugs)
            except ValueError:
                errors["base"] = "invalid_room"
            else:
                self._rooms = [
                    room_to_dict(updated) if room["name"] == self._editing_room_name else room
                    for room in self._rooms
                ]
                options = {**self._data, CONF_ROOMS: self._rooms}
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="edit_room",
            data_schema=_room_schema(current, adding=False),
            errors=errors,
        )
