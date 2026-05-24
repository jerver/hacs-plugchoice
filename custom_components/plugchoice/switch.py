"""Switch platform for PlugChoice — uitgesteld laden actief."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice switches from a config entry."""
    async_add_entities([PlugChoiceDelayedChargingSwitch(entry)])


class PlugChoiceDelayedChargingSwitch(RestoreEntity, SwitchEntity):
    """Switch to enable or disable delayed charging."""

    _attr_has_entity_name = True
    _attr_name = "Uitgesteld laden actief"
    _attr_icon = "mdi:clock-start"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_uitgesteld_laden_actief"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._is_on = last_state.state == "on"

    @property
    def is_on(self) -> bool:
        """Return True if delayed charging is enabled."""
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Enable delayed charging."""
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable delayed charging."""
        self._is_on = False
        self.async_write_ha_state()
