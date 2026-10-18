"""Number entities for charging plan inputs."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DIRECT_CHARGING_AMP,
    CONF_DISTANCE_KM,
    CONF_EFFICIENCY_KM_PER_KWH,
    DEFAULT_DIRECT_CHARGING_AMP,
    DOMAIN,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the editable charging plan numbers."""
    async_add_entities(
        [
            PlugChoicePlanNumber(
                entry,
                CONF_DISTANCE_KM,
                "Gewenste afstand",
                0.1,
                2000,
                0.1,
                "km",
                "mdi:map-marker-distance",
            ),
            PlugChoicePlanNumber(
                entry,
                CONF_EFFICIENCY_KM_PER_KWH,
                "Verbruik auto",
                0.1,
                20,
                0.1,
                "km/kWh",
                "mdi:car-electric",
            ),
            PlugChoicePlanNumber(
                entry,
                CONF_DIRECT_CHARGING_AMP,
                "Maximale laadstroom direct laden",
                6,
                16,
                1,
                "A",
                "mdi:current-ac",
                mode=NumberMode.SLIDER,
                default_value=DEFAULT_DIRECT_CHARGING_AMP,
            ),
        ]
    )


class PlugChoicePlanNumber(NumberEntity):
    """An editable numeric charging plan option."""

    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        option_key: str,
        name: str,
        minimum: float,
        maximum: float,
        step: float,
        unit: str,
        icon: str,
        mode: NumberMode = NumberMode.BOX,
        default_value: float | None = None,
    ) -> None:
        self._entry = entry
        self._option_key = option_key
        self._attr_name = name
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_mode = mode
        self._default_value = default_value
        self._attr_unique_id = f"{entry.entry_id}_{option_key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["charger_uuid"])},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def native_value(self) -> float | None:
        """Return the configured value, if one has been set."""
        value = self._entry.options.get(self._option_key)
        return float(value) if value is not None else self._default_value

    async def async_set_native_value(self, value: float) -> None:
        """Persist a new value and apply charging-current changes immediately."""
        options = {**self._entry.options, self._option_key: float(value)}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        if self._option_key == CONF_DIRECT_CHARGING_AMP:
            manager = self.hass.data[DOMAIN][self._entry.entry_id]["schedule_manager"]
            await manager.async_set_direct_charging_amp(float(value))
            manager.coordinator.async_set_updated_data(manager.coordinator.data)
        self.async_write_ha_state()