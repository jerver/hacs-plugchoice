"""Sensor platform for PlugChoice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID, DOMAIN
from . import PlugChoiceDataUpdateCoordinator


@dataclass(frozen=True)
class PlugChoiceSensorEntityDescription(SensorEntityDescription):
    """Describe a PlugChoice sensor."""


SENSOR_DESCRIPTIONS: tuple[PlugChoiceSensorEntityDescription, ...] = (
    PlugChoiceSensorEntityDescription(
        key="status",
        name="Status",
        icon="mdi:ev-station",
    ),
    PlugChoiceSensorEntityDescription(
        key="total_kwh",
        name="Total Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:lightning-bolt",
    ),
    PlugChoiceSensorEntityDescription(
        key="session_kwh",
        name="Session Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:battery-charging",
    ),
    PlugChoiceSensorEntityDescription(
        key="charging_kwh",
        name="Charging Power",
        native_unit_of_measurement="kW",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PlugChoice sensors from a config entry."""
    coordinator: PlugChoiceDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id][
        "coordinator"
    ]

    async_add_entities(
        PlugChoiceSensor(coordinator, entry, description)
        for description in SENSOR_DESCRIPTIONS
    )


class PlugChoiceSensor(CoordinatorEntity[PlugChoiceDataUpdateCoordinator], SensorEntity):
    """Representation of a PlugChoice sensor."""

    entity_description: PlugChoiceSensorEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PlugChoiceDataUpdateCoordinator,
        entry: ConfigEntry,
        description: PlugChoiceSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        data = self.coordinator.data
        if data is None:
            return None

        key = self.entity_description.key

        if key == "status":
            charger = data.get("charger", {})
            connectors = charger.get("connectors") or []
            target_id = int(
                self._entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
            )
            # Match by OCPP connector_id; fall back to first connector, then charger
            matched = next(
                (c for c in connectors if c.get("connector_id") == target_id),
                connectors[0] if connectors else None,
            )
            if matched is not None and matched.get("status") is not None:
                return matched["status"]
            return charger.get("status")

        if key == "total_kwh":
            return data.get("total_kwh")

        if key == "session_kwh":
            tx = data.get("active_transaction")
            if tx is None:
                return 0.0
            meter_start = tx.get("meter_start") or 0
            meter_stop = tx.get("meter_stop")
            if meter_stop is not None:
                return round((meter_stop - meter_start) / 1000, 3)
            # Active session — estimate from latest meter value
            meter_value = data.get("meter_value")
            live_wh = _extract_energy_wh(meter_value)
            if live_wh is not None:
                return round((live_wh - meter_start) / 1000, 3)
            return round(float(tx.get("total_kwh") or 0), 3)

        if key == "charging_kwh":
            meter_value = data.get("meter_value")
            watts = _extract_power_w(meter_value)
            if watts is not None:
                return round(watts / 1000, 3)
            return 0.0

        return None


def _extract_energy_wh(meter_value: dict | None) -> float | None:
    """Extract Energy.Active.Import.Register value in Wh from a meter value response."""
    if not meter_value:
        return None
    for entry in meter_value.get("meterValue", []):
        for sv in entry.get("sampledValue", []):
            if sv.get("measurand") == "Energy.Active.Import.Register":
                try:
                    raw = float(sv["value"])
                    unit = sv.get("unit", "Wh")
                    return raw * 1000 if unit == "kWh" else raw
                except (KeyError, ValueError):
                    pass
    return None


def _extract_power_w(meter_value: dict | None) -> float | None:
    """Extract Power.Active.Import value in W from a meter value response."""
    if not meter_value:
        return None
    for entry in meter_value.get("meterValue", []):
        for sv in entry.get("sampledValue", []):
            if sv.get("measurand") == "Power.Active.Import":
                try:
                    raw = float(sv["value"])
                    unit = sv.get("unit", "W")
                    return raw * 1000 if unit == "kW" else raw
                except (KeyError, ValueError):
                    pass
    return None
