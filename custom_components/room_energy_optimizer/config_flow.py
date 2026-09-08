"""Config flow for Room Energy Optimizer."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import (
    CONF_FLOW_TEMPERATURE,
    CONF_MONTHLY_COST,
    CONF_ROOMS,
    CONF_SYSTEM_TYPE,
    DOMAIN,
    SYSTEM_ONE_PIPE,
    SYSTEM_TWO_PIPE,
)
from .model import parse_rooms


def _schema(defaults: dict[str, Any]) -> vol.Schema:
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
            vol.Optional(CONF_MONTHLY_COST, default=defaults.get(CONF_MONTHLY_COST, "")): str,
            vol.Required(
                CONF_ROOMS,
                default=defaults.get(
                    CONF_ROOMS,
                    "Living room|climate.living_room|2000|30\nBedroom|climate.bedroom|1000|15",
                ),
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True, type=selector.TextSelectorType.TEXT)
            ),
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        parse_rooms(user_input.get(CONF_ROOMS, ""))
    except ValueError:
        errors[CONF_ROOMS] = "invalid_rooms"
    monthly = user_input.get(CONF_MONTHLY_COST, "").strip()
    if monthly and not monthly.startswith("sensor."):
        errors[CONF_MONTHLY_COST] = "invalid_sensor"
    return errors


class RoomEnergyOptimizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up the integration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                await self.async_set_unique_id("main")
                self._abort_if_unique_id_configured()
                title = user_input.pop(CONF_NAME)
                return self.async_create_entry(title=title, data={}, options=user_input)
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Edit the full configuration safely through the UI."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate(user_input)
            if not errors:
                user_input.pop(CONF_NAME, None)
                return self.async_create_entry(title="", data=user_input)
        defaults = {CONF_NAME: self._entry.title, **self._entry.options}
        return self.async_show_form(
            step_id="init", data_schema=_schema(user_input or defaults), errors=errors
        )
