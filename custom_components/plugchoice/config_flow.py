"""Config flow for PlugChoice integration."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_API_KEY,
    CONF_CHARGER_UUID,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from . import PlugChoiceAPI, PlugChoiceAuthError, PlugChoiceError

_LOGGER = logging.getLogger(__name__)


class PlugChoiceConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PlugChoice."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> "PlugChoiceOptionsFlowHandler":
        """Return the options flow handler."""
        return PlugChoiceOptionsFlowHandler(config_entry)

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._api_key: str = ""
        self._chargers: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — enter API key."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            session = async_get_clientsession(self.hass)
            # Use a placeholder UUID just for auth check; list chargers instead
            api = PlugChoiceAPI(session, api_key, "")
            try:
                chargers = await api.list_chargers()
            except PlugChoiceAuthError:
                errors["base"] = "invalid_auth"
            except PlugChoiceError:
                errors["base"] = "cannot_connect"
            else:
                if not chargers:
                    errors["base"] = "no_chargers"
                else:
                    self._api_key = api_key
                    self._chargers = chargers
                    return await self.async_step_charger()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_charger(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a charger and set the default token ID."""
        errors: dict[str, str] = {}

        charger_options = [
            SelectOptionDict(
                value=c["uuid"],
                label=f"{c.get('identity', c['uuid'])} ({c.get('status', 'unknown')})",
            )
            for c in self._chargers
        ]

        if user_input is not None:
            charger_uuid = user_input[CONF_CHARGER_UUID]
            token_id = user_input[CONF_TOKEN_ID].strip()

            # Ensure we don't create a duplicate entry for the same charger
            await self.async_set_unique_id(charger_uuid)
            self._abort_if_unique_id_configured()

            # Find a friendly name for the title
            charger_name = next(
                (
                    c.get("identity", charger_uuid)
                    for c in self._chargers
                    if c["uuid"] == charger_uuid
                ),
                charger_uuid,
            )

            return self.async_create_entry(
                title=f"PlugChoice – {charger_name}",
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_CHARGER_UUID: charger_uuid,
                    CONF_TOKEN_ID: token_id,
                },
            )

        return self.async_show_form(
            step_id="charger",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CHARGER_UUID): SelectSelector(
                        SelectSelectorConfig(
                            options=charger_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(CONF_TOKEN_ID): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                }
            ),
            errors=errors,
            description_placeholders={
                "token_help": "Enter the RFID token/card ID used to authorize charging sessions."
            },
        )


class PlugChoiceOptionsFlowHandler(OptionsFlow):
    """Handle PlugChoice options (settings that can be changed after setup)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize."""
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            max=MAX_SCAN_INTERVAL,
                            step=1,
                            unit_of_measurement="seconds",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )
