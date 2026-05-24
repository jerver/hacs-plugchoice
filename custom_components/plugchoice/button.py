"""Button platform for PlugChoice — start and stop charging."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_CONNECTOR_ID, CONF_TOKEN_ID, DEFAULT_CONNECTOR_ID, DOMAIN
from . import PlugChoiceAPI, PlugChoiceDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="start_charging",
        name="Start Charging",
        icon="mdi:play-circle",
    ),
    ButtonEntityDescription(
        key="stop_charging",
        name="Stop Charging",
        icon="mdi:stop-circle",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice buttons from a config entry."""
    coordinator: PlugChoiceDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]
    api: PlugChoiceAPI = hass.data[DOMAIN][entry.entry_id]["api"]

    async_add_entities(
        PlugChoiceButton(coordinator, api, entry, description)
        for description in BUTTON_DESCRIPTIONS
    )


class PlugChoiceButton(ButtonEntity):
    """A button to start or stop EV charging."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PlugChoiceDataUpdateCoordinator,
        api: PlugChoiceAPI,
        entry: ConfigEntry,
        description: ButtonEntityDescription,
    ) -> None:
        """Initialize the button."""
        self.entity_description = description
        self._coordinator = coordinator
        self._api = api
        self._token_id: str = entry.data[CONF_TOKEN_ID]
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    async def async_press(self) -> None:
        """Handle button press."""
        if self.entity_description.key == "start_charging":
            connector_id = int(
                self._entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
            )
            result = await self._api.start_charging(
                token_id=self._token_id, connector_id=connector_id
            )
            _LOGGER.info("Start charging response: %s", result)
        else:
            # Attempt to stop the active transaction
            active_tx = None
            if self._coordinator.data:
                active_tx = self._coordinator.data.get("active_transaction")
            tx_id = active_tx.get("id") if active_tx else None
            result = await self._api.stop_charging(transaction_id=tx_id)
            _LOGGER.info("Stop charging response: %s", result)

        # Refresh data after action
        await self._coordinator.async_request_refresh()
