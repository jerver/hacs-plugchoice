"""PlugChoice EV Charger integration for Home Assistant."""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
import async_timeout

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_API_KEY,
    CONF_CHARGER_UUID,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    API_BASE_URL,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.BINARY_SENSOR, Platform.SWITCH, Platform.TIME]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up PlugChoice from a config entry."""
    api_key = entry.data[CONF_API_KEY]
    charger_uuid = entry.data[CONF_CHARGER_UUID]

    session = async_get_clientsession(hass)
    api = PlugChoiceAPI(session, api_key, charger_uuid)

    # Validate credentials
    try:
        await api.get_charger()
    except PlugChoiceAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except PlugChoiceError as err:
        raise ConfigEntryNotReady(err) from err

    coordinator = PlugChoiceDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class PlugChoiceDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data from the PlugChoice API."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: "PlugChoiceAPI"
    ) -> None:
        """Initialize."""
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict:
        """Fetch data from the API."""
        try:
            charger = await self.api.get_charger()
            active_transaction = await self.api.get_active_transaction()
            meter_value = await self.api.get_latest_meter_value()
            power_usage = await self.api.get_power_usage()
            last_session = await self.api.get_last_session()
            return {
                "charger": charger,
                "active_transaction": active_transaction,
                "meter_value": meter_value,
                "power_usage": power_usage,
                "last_session": last_session,
            }
        except PlugChoiceAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except PlugChoiceError as err:
            raise UpdateFailed(f"Error communicating with PlugChoice API: {err}") from err


class PlugChoiceError(Exception):
    """Generic PlugChoice API error."""


class PlugChoiceAuthError(PlugChoiceError):
    """Authentication error."""


class PlugChoiceAPI:
    """Client for the PlugChoice REST API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        charger_uuid: str,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._api_key = api_key
        self._charger_uuid = charger_uuid
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self, method: str, path: str, **kwargs
    ) -> dict | list:
        """Make an authenticated API request."""
        url = f"{API_BASE_URL}{path}"
        try:
            async with async_timeout.timeout(15):
                response = await self._session.request(
                    method, url, headers=self._headers, **kwargs
                )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise PlugChoiceError(f"Request failed: {err}") from err

        if response.status == 401:
            raise PlugChoiceAuthError("Invalid API key")
        if not response.ok:
            text = await response.text()
            raise PlugChoiceError(
                f"API error {response.status}: {text[:200]}"
            )

        return await response.json()

    async def get_charger(self) -> dict:
        """Fetch charger details."""
        result = await self._request("GET", f"/chargers/{self._charger_uuid}")
        return result.get("data", result) if isinstance(result, dict) else result

    async def get_active_transaction(self) -> dict | None:
        """Fetch the current active transaction, if any."""
        result = await self._request(
            "GET",
            f"/chargers/{self._charger_uuid}/transactions",
            params={"filter[status]": "active", "limit": 1},
        )
        transactions = result if isinstance(result, list) else result.get("data", [])
        return transactions[0] if transactions else None

    async def get_latest_meter_value(self) -> dict | None:
        """Fetch the latest meter value from connector 1."""
        try:
            return await self._request(
                "GET",
                f"/chargers/{self._charger_uuid}/connectors/1/latest-metervalue",
            )
        except PlugChoiceError:
            return None

    async def get_power_usage(self) -> dict | None:
        """Fetch real-time power usage for connector 1."""
        try:
            return await self._request(
                "GET",
                f"/chargers/{self._charger_uuid}/connectors/1/power-usage",
            )
        except PlugChoiceError:
            return None

    async def list_chargers(self) -> list[dict]:
        """List all chargers accessible with the current API key."""
        result = await self._request("GET", "/chargers")
        return result if isinstance(result, list) else result.get("data", [])

    async def start_charging(self, token_id: str, connector_id: int | None = None) -> dict:
        """Send a remote start transaction command."""
        payload: dict = {"id_token": token_id}
        if connector_id is not None:
            payload["connector_id"] = connector_id
        return await self._request(
            "POST",
            f"/chargers/{self._charger_uuid}/actions/start",
            json=payload,
        )

    async def get_last_session(self) -> dict | None:
        """Fetch the most recent transaction (active or finished)."""
        result = await self._request(
            "GET",
            f"/chargers/{self._charger_uuid}/transactions",
            params={"limit": 1, "sort": "-started_at"},
        )
        transactions = result if isinstance(result, list) else result.get("data", [])
        return transactions[0] if transactions else None

    async def stop_charging(self, transaction_id: int | None = None) -> dict:
        """Send a remote stop transaction command."""
        payload: dict = {}
        if transaction_id is not None:
            payload["transaction_id"] = transaction_id
        return await self._request(
            "POST",
            f"/chargers/{self._charger_uuid}/actions/stop",
            json=payload,
        )
