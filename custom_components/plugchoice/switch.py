"""Switch platform for PlugChoice."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TEST_MODE, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice switches from a config entry."""
    async_add_entities(
        [
            PlugChoiceTestModeSwitch(entry),
        ]
    )


class PlugChoiceTestModeSwitch(SwitchEntity):
    """Switch that disables all PlugChoice API traffic when enabled."""

    _attr_has_entity_name = True
    _attr_name = "Test Mode"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_test_mode"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def is_on(self) -> bool:
        return bool(self._entry.options.get(CONF_TEST_MODE, False))

    async def async_turn_on(self, **kwargs) -> None:
        await self._async_set_test_mode(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._async_set_test_mode(False)

    async def _async_set_test_mode(self, enabled: bool) -> None:
        options = {**self._entry.options, CONF_TEST_MODE: enabled}
        self.hass.config_entries.async_update_entry(self._entry, options=options)



