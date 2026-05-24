"""Time platform for PlugChoice — starttijd uitgesteld laden."""
from __future__ import annotations

import datetime
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DEFAULT_START_TIME = datetime.time(22, 0, 0)  # 22:00


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice time entities from a config entry."""
    async_add_entities([PlugChoiceDelayedChargingTime(entry)])


class PlugChoiceDelayedChargingTime(RestoreEntity, TimeEntity):
    """Time entity for the delayed charging start time."""

    _attr_has_entity_name = True
    _attr_name = "Starttijd uitgesteld laden"
    _attr_icon = "mdi:clock-time-eight"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the time entity."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_starttijd_uitgesteld_laden"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )
        self._value: datetime.time = DEFAULT_START_TIME

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in ("unknown", "unavailable"):
            try:
                self._value = datetime.time.fromisoformat(last_state.state)
            except ValueError:
                pass

    @property
    def native_value(self) -> datetime.time:
        """Return the current start time."""
        return self._value

    async def async_set_value(self, value: datetime.time) -> None:
        """Set the start time."""
        self._value = value
        self.async_write_ha_state()
