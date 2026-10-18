"""Date-time entity for the charging plan deadline."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_DEADLINE, DOMAIN

PLAN_TIMEZONE = ZoneInfo("Europe/Amsterdam")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the editable charging deadline."""
    async_add_entities([PlugChoiceChargingDeadline(entry)])


class PlugChoiceChargingDeadline(DateTimeEntity):
    """An editable date-time charging deadline."""

    _attr_has_entity_name = True
    _attr_name = "Uiterste laadtijd"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{CONF_DEADLINE}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["charger_uuid"])},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def native_value(self) -> datetime | None:
        """Return the configured deadline."""
        value = self._entry.options.get(CONF_DEADLINE)
        if isinstance(value, datetime):
            deadline = value
        elif value:
            deadline = dt_util.parse_datetime(str(value))
        else:
            return None
        if deadline is None:
            return None
        if deadline.tzinfo is None:
            return deadline.replace(tzinfo=PLAN_TIMEZONE)
        return deadline.astimezone(PLAN_TIMEZONE)

    async def async_set_value(self, value: datetime) -> None:
        """Persist a future deadline in the plan timezone."""
        deadline = (
            value.replace(tzinfo=PLAN_TIMEZONE)
            if value.tzinfo is None
            else value.astimezone(PLAN_TIMEZONE)
        )
        if deadline <= dt_util.now().astimezone(PLAN_TIMEZONE):
            raise HomeAssistantError("The charging deadline must be in the future")
        options = {**self._entry.options, CONF_DEADLINE: deadline.isoformat()}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()