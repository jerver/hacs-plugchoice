"""Sensor platform for PlugChoice."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_point_in_time, async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID, DOMAIN
from . import PlugChoiceDataUpdateCoordinator


@dataclass(frozen=True)
class PlugChoiceSensorEntityDescription(SensorEntityDescription):
    """Describe a PlugChoice sensor."""


SENSOR_DESCRIPTIONS: tuple[PlugChoiceSensorEntityDescription, ...] = (
    PlugChoiceSensorEntityDescription(
        key="connection_status",
        name="Connection Status",
        icon="mdi:connection",
    ),
    PlugChoiceSensorEntityDescription(
        key="charger_error",
        name="Charger Error",
        icon="mdi:alert-circle-outline",
    ),
    PlugChoiceSensorEntityDescription(
        key="status",
        name="Status",
        icon="mdi:ev-station",
    ),
    PlugChoiceSensorEntityDescription(
        key="connector_error",
        name="Connector Error",
        icon="mdi:alert-outline",
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
    PlugChoiceSensorEntityDescription(
        key="last_session_starttime",
        name="Last Session Start Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
    ),
    PlugChoiceSensorEntityDescription(
        key="last_session_endtime",
        name="Last Session End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-end",
    ),
    PlugChoiceSensorEntityDescription(
        key="last_session_stop_reason",
        name="Last Session Stop Reason",
        icon="mdi:information-outline",
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
        [
            *[
                PlugChoiceSensor(coordinator, entry, description)
                for description in SENSOR_DESCRIPTIONS
            ],
            PlugChoiceDelayedChargingTimestampSensor(entry),
        ]
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
        charger = data.get("charger", {})

        if key == "connection_status":
            return charger.get("connection_status")

        if key == "charger_error":
            return charger.get("error")

        if key in ("status", "connector_error"):
            connectors = charger.get("connectors") or []
            target_id = int(
                self._entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
            )
            # Match by OCPP connector_id; fall back to first connector, then charger
            matched = next(
                (c for c in connectors if c.get("connector_id") == target_id),
                connectors[0] if connectors else None,
            )
            if key == "status":
                raw = (
                    matched["status"]
                    if matched is not None and matched.get("status") is not None
                    else charger.get("status")
                )
                return _map_status(raw)
            if key == "connector_error":
                if matched is not None:
                    return matched.get("error")
                return None

        if key == "total_kwh":
            meter_value = data.get("meter_value")
            wh = _extract_energy_wh(meter_value)
            return round(wh / 1000, 3) if wh is not None else None

        if key == "session_kwh":
            tx = data.get("active_transaction")
            if tx is None:
                return 0.0
            return round(float(tx.get("total_kwh") or 0), 3)

        if key == "charging_kwh":
            power_usage = data.get("power_usage")
            if power_usage:
                try:
                    return round(float(power_usage["kW"]), 3)
                except (KeyError, ValueError, TypeError):
                    pass
            meter_value = data.get("meter_value")
            watts = _extract_power_w(meter_value)
            if watts is not None:
                return round(watts / 1000, 3)
            return 0.0

        last_session = data.get("last_session")

        if key == "last_session_starttime":
            return _parse_timestamp(last_session.get("started_at") if last_session else None)

        if key == "last_session_endtime":
            return _parse_timestamp(last_session.get("stopped_at") if last_session else None)

        if key == "last_session_stop_reason":
            return last_session.get("stop_reason") if last_session else None

        return None


def _map_status(status: str | None) -> str | None:
    """Map raw OCPP status values to human-friendly labels."""
    if status == "SuspendedEV":
        return "Waiting for car"
    if status == "SuspendedEVSE":
        return "Waiting for power"
    return status


def _extract_energy_wh(meter_value: dict | None) -> float | None:
    """Extract Energy.Active.Import.Register value in Wh from a meter value response."""
    if not meter_value:
        return None
    for entry in meter_value.get("meterValue", []):
        for sv in entry.get("sampledValue", []):
            measurand = sv.get("measurand") or "Energy.Active.Import.Register"
            if measurand == "Energy.Active.Import.Register":
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


def _parse_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO8601 timestamp string into a timezone-aware datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


class PlugChoiceDelayedChargingTimestampSensor(SensorEntity):
    """Sensor exposing the next occurrence of the delayed charging start time as a timestamp.

    This sensor has device_class TIMESTAMP so it can be used directly in an
    automation time trigger via ``at: sensor.plugchoice_starttijd_uitgesteld_laden``.
    After each occurrence fires it automatically rolls over to the following day.
    """

    _attr_has_entity_name = True
    _attr_name = "Starttijd uitgesteld laden"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-time-eight"
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_starttijd_uitgesteld_laden_ts"
        charger_uuid = entry.data["charger_uuid"]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, charger_uuid)},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )
        self._next_occurrence: datetime | None = None
        self._cancel_refresh: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_pending_refresh)
        time_entity_id = self._get_time_entity_id()
        if time_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, [time_entity_id], self._handle_time_entity_change
                )
            )
            state = self.hass.states.get(time_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                self._compute_and_schedule(state.state)

    def _get_time_entity_id(self) -> str | None:
        """Look up the companion time entity via the entity registry."""
        registry = er.async_get(self.hass)
        return registry.async_get_entity_id(
            "time", DOMAIN, f"{self._entry.entry_id}_starttijd_uitgesteld_laden"
        )

    @callback
    def _handle_time_entity_change(self, event: Any) -> None:
        new_state = event.data.get("new_state")
        if new_state and new_state.state not in ("unknown", "unavailable"):
            self._compute_and_schedule(new_state.state)
            self.async_write_ha_state()

    def _compute_and_schedule(self, time_state: str) -> None:
        """Compute the next occurrence datetime and schedule a roll-over refresh."""
        try:
            t = dt_time.fromisoformat(time_state)
        except ValueError:
            return
        now = dt_util.now()
        candidate = datetime.combine(now.date(), t, tzinfo=now.tzinfo)
        if candidate <= now:
            candidate += timedelta(days=1)
        self._next_occurrence = candidate
        self._schedule_refresh(candidate)

    def _schedule_refresh(self, occurrence: datetime) -> None:
        """Schedule a state update 2 s after the occurrence so the trigger rolls over."""
        if self._cancel_refresh is not None:
            self._cancel_refresh()
        refresh_at = occurrence + timedelta(seconds=2)

        @callback
        def _do_refresh(_now: datetime) -> None:
            self._cancel_refresh = None
            time_entity_id = self._get_time_entity_id()
            if time_entity_id:
                state = self.hass.states.get(time_entity_id)
                if state and state.state not in ("unknown", "unavailable"):
                    self._compute_and_schedule(state.state)
            self.async_write_ha_state()

        self._cancel_refresh = async_track_point_in_time(
            self.hass, _do_refresh, refresh_at
        )

    def _cancel_pending_refresh(self) -> None:
        if self._cancel_refresh is not None:
            self._cancel_refresh()
            self._cancel_refresh = None

    @property
    def native_value(self) -> datetime | None:
        return self._next_occurrence
