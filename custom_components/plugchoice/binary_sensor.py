"""Binary sensor platform for PlugChoice."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import PlugChoiceDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice binary sensors from a config entry."""
    coordinator: PlugChoiceDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    async_add_entities([PlugChoiceActiveSensor(coordinator, entry)])


class PlugChoiceActiveSensor(
    CoordinatorEntity[PlugChoiceDataUpdateCoordinator], BinarySensorEntity
):
    """Binary sensor that is ON when a charging session is active."""

    _attr_has_entity_name = True
    _attr_name = "Active"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_icon = "mdi:ev-plug-type2"

    def __init__(
        self,
        coordinator: PlugChoiceDataUpdateCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_active"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True when the last session has no end time (i.e. still active)."""
        data = self.coordinator.data
        if data is None:
            return None
        last_session = data.get("last_session")
        if last_session is None:
            return False
        return last_session.get("stopped_at") is None
