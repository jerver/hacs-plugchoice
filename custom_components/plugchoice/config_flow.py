"""Config flow for PlugChoice integration."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    DateTimeSelector,
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
    CONF_CONNECTOR_ID,
    CONF_DEADLINE,
    CONF_DIRECT_CHARGING,
    CONF_DISTANCE_KM,
    CONF_EFFICIENCY_KM_PER_KWH,
    CONF_MIN_SOLAR_KWH,
    CONF_TEST_MODE,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_ID,
    DEFAULT_CONNECTOR_ID,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from . import PlugChoiceAPI, PlugChoiceAuthError, PlugChoiceError
from homeassistant.util import dt as dt_util

PLAN_TIMEZONE = ZoneInfo("Europe/Amsterdam")

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
        errors: dict[str, str] = {}
        if user_input is not None:
            distance_km = float(user_input[CONF_DISTANCE_KM])
            efficiency = float(user_input[CONF_EFFICIENCY_KM_PER_KWH])
            raw_deadline = user_input[CONF_DEADLINE]
            deadline = (
                raw_deadline
                if isinstance(raw_deadline, datetime)
                else dt_util.parse_datetime(raw_deadline)
            )
            if deadline is not None:
                deadline = (
                    deadline.replace(tzinfo=PLAN_TIMEZONE)
                    if deadline.tzinfo is None
                    else deadline.astimezone(PLAN_TIMEZONE)
                )
            if distance_km <= 0:
                errors[CONF_DISTANCE_KM] = "invalid_input"
            if efficiency <= 0:
                errors[CONF_EFFICIENCY_KM_PER_KWH] = "invalid_input"
            if deadline is None or deadline <= dt_util.now().astimezone(PLAN_TIMEZONE):
                errors[CONF_DEADLINE] = "invalid_input"
            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(),
                    errors=errors,
                )
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
        )

    def _options_schema(self) -> vol.Schema:
        current = self._config_entry.options
        distance_key = (
            vol.Required(CONF_DISTANCE_KM, default=current[CONF_DISTANCE_KM])
            if CONF_DISTANCE_KM in current
            else vol.Required(CONF_DISTANCE_KM)
        )
        deadline_key = (
            vol.Required(CONF_DEADLINE, default=current[CONF_DEADLINE])
            if CONF_DEADLINE in current
            else vol.Required(CONF_DEADLINE)
        )
        schema: dict[Any, Any] = {
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=1,
                    unit_of_measurement="seconds",
                    mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_CONNECTOR_ID,
                default=current.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=8, step=1, mode=NumberSelectorMode.BOX)
            ),
            distance_key: NumberSelector(
                NumberSelectorConfig(min=0.1, max=2000, step=0.1, mode=NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_EFFICIENCY_KM_PER_KWH,
                default=current.get(CONF_EFFICIENCY_KM_PER_KWH, 6.6),
            ): NumberSelector(
                NumberSelectorConfig(min=0.1, max=20, step=0.1, mode=NumberSelectorMode.BOX)
            ),
            deadline_key: DateTimeSelector(),
            vol.Optional(
                CONF_DIRECT_CHARGING,
                default=current.get(CONF_DIRECT_CHARGING, False),
            ): BooleanSelector(),
            vol.Optional(
                CONF_MIN_SOLAR_KWH, default=current.get(CONF_MIN_SOLAR_KWH, 0.3)
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=20, step=0.1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_TEST_MODE, default=current.get(CONF_TEST_MODE, False)
            ): BooleanSelector(),
        }
        return vol.Schema(schema)
