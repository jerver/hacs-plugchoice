"""Button platform for PlugChoice — start and stop charging."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from . import PlugChoiceAPI, PlugChoiceDataUpdateCoordinator

BUTTON_DESCRIPTIONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="start_charging",
        name="Direct laden",
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
        [
            *(
                PlugChoiceButton(coordinator, api, entry, description)
                for description in BUTTON_DESCRIPTIONS
            ),
            PlugChoiceCreatePlanButton(entry),
            PlugChoiceStartOptimalButton(entry),
            PlugChoiceCancelPlanButton(entry),
            PlugChoiceGetCompositeScheduleButton(entry, api),
        ]
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
        manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
        if self.entity_description.key == "start_charging":
            await manager.async_start_direct_charge()
        else:
            await manager.async_stop_charging()
        if self._api.test_mode:
            self._coordinator.async_set_updated_data(self._coordinator.data)
        else:
            await self._coordinator.async_request_refresh()


class PlugChoiceCreatePlanButton(ButtonEntity):
    """Button to calculate and save a charging plan."""

    _attr_has_entity_name = True
    _attr_name = "Bereken laadschema"
    _attr_icon = "mdi:calculator"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_create_charging_plan"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
        await manager.async_create_plan()
        manager.coordinator.async_set_updated_data(manager.coordinator.data)


class PlugChoiceStartOptimalButton(ButtonEntity):
    """Button to start charging with the saved optimal schedule."""

    _attr_has_entity_name = True
    _attr_name = "Optimaal laden"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_start_optimal_charging"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
        await manager.async_start_optimal_charge()
        manager.coordinator.async_set_updated_data(manager.coordinator.data)


class PlugChoiceCancelPlanButton(ButtonEntity):
    """Button to remove a saved plan without deleting charger profiles."""

    _attr_has_entity_name = True
    _attr_name = "Verwijder laadplan"
    _attr_icon = "mdi:calendar-remove"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_cancel_charging_plan"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
        await manager.async_cancel_plan()
        manager.coordinator.async_set_updated_data(manager.coordinator.data)


class PlugChoiceGetCompositeScheduleButton(ButtonEntity):
    """Fetch the charger-computed schedule for display on the schedule sensor."""

    _attr_has_entity_name = True
    _attr_name = "Laadschema opvragen"
    _attr_icon = "mdi:calendar-search"

    def __init__(self, entry: ConfigEntry, api: PlugChoiceAPI) -> None:
        self._entry = entry
        self._api = api
        self._attr_unique_id = f"{entry.entry_id}_get_composite_schedule"
        self._attr_device_info = _device_info(entry)

    async def async_press(self) -> None:
        manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
        await manager.async_request_composite_schedule()
        manager.coordinator.async_set_updated_data(manager.coordinator.data)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data["charger_uuid"])},
        name=entry.title,
        manufacturer="PlugChoice",
        model="EV Charger",
    )
