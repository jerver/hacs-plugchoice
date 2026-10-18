"""Sensor platform for PlugChoice."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
from .charging import ChargingScheduleManager


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
            PlugChoiceChargingScheduleSensor(coordinator, entry, hass.data[DOMAIN][entry.entry_id]["schedule_manager"]),
            *[
                PlugChoicePlannedEnergySensor(
                    coordinator,
                    entry,
                    hass.data[DOMAIN][entry.entry_id]["schedule_manager"],
                    key,
                    name,
                    icon,
                )
                for key, name, icon in (
                    ("planned_charge_kwh", "Geplande laadenergie", "mdi:ev-station"),
                    ("planned_solar_kwh", "Geplande zonne-energie", "mdi:solar-power"),
                    ("planned_grid_kwh", "Geplande netenergie", "mdi:transmission-tower-import"),
                )
            ],
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


class PlugChoiceChargingScheduleSensor(
    CoordinatorEntity[PlugChoiceDataUpdateCoordinator], SensorEntity
):
    """Expose the saved plan and its hourly energy split."""

    _attr_has_entity_name = True
    _attr_name = "Charging Schedule"
    _attr_icon = "mdi:chart-bar"

    def __init__(
        self,
        coordinator: PlugChoiceDataUpdateCoordinator,
        entry: ConfigEntry,
        manager: ChargingScheduleManager,
    ) -> None:
        super().__init__(coordinator)
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_charging_schedule"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["charger_uuid"])},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def suggested_object_id(self) -> str:
        return "charging_schedule"

    @property
    def native_value(self) -> str:
        plan = self._manager.plan
        if plan is None:
            return "not_created"
        return "feasible" if plan.get("feasible") else "infeasible"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self._manager.plan
        attributes: dict[str, Any] = {
            "composite_schedule_text": _format_composite_schedule(
                self._manager.composite_schedule
            ),
            "test_mode_message_text": (
                json.dumps(
                    self._manager.test_mode_message,
                    indent=2,
                    ensure_ascii=False,
                )
                if self._manager.test_mode_message is not None
                else "Nog geen testbericht. Zet Test Mode aan en druk op een actieknop."
            ),
        }
        if self._manager.test_mode_message is not None:
            attributes["test_mode_message"] = self._manager.test_mode_message
        if plan is not None:
            attributes.update(
                {
                    "required_kwh": plan.get("required_kwh"),
                    "max_available_kwh": plan.get("max_available_kwh"),
                    "solar_kwh": plan.get("solar_kwh"),
                    "grid_kwh": plan.get("grid_kwh"),
                    "deadline": plan.get("deadline"),
                    "direct_charging": plan.get("direct_charging"),
                    "error": plan.get("error"),
                    "schedule": plan.get("schedule", []),
                    "hourly_energy": plan.get("hourly_energy", []),
                    "schedule_text": _format_schedule_text(plan),
                }
            )
        return attributes


class PlugChoicePlannedEnergySensor(
    CoordinatorEntity[PlugChoiceDataUpdateCoordinator], SensorEntity
):
    """Expose one planned energy total as a standalone sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: PlugChoiceDataUpdateCoordinator,
        entry: ConfigEntry,
        manager: ChargingScheduleManager,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._manager = manager
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.data["charger_uuid"])},
            name=entry.title,
            manufacturer="PlugChoice",
            model="EV Charger",
        )

    @property
    def native_value(self) -> float | None:
        """Return the plan's total scheduled, solar, or grid energy."""
        plan = self._manager.plan
        if not plan or not plan.get("feasible"):
            return None
        if self._key == "planned_charge_kwh":
            return round(
                sum(slot.get("charge_kwh", 0) for slot in plan.get("schedule", [])),
                3,
            )
        if self._key == "planned_solar_kwh":
            return plan.get("solar_kwh")
        return plan.get("grid_kwh")


def _format_schedule_text(plan: dict[str, Any]) -> str:
    """Format scheduled slots as a concise, dashboard-friendly list."""
    if not plan.get("feasible"):
        return (
            f"Niet haalbaar: {plan.get('error')}. "
            f"Benodigd {plan.get('required_kwh', 0):.2f} kWh; "
            f"maximaal beschikbaar {plan.get('max_available_kwh', 0):.2f} kWh."
        )
    slots = plan.get("schedule", [])
    if not slots:
        return "Er zijn geen laadmomenten gepland."
    return "\n".join(
        "- {time}: {energy:.2f} kWh, {amps} A, zon {solar:.2f} kWh, "
        "net {grid:.2f} kWh, {duration:.0f} min".format(
            time=datetime.fromisoformat(slot["recommended_start"]).strftime(
                "%d-%m %H:%M"
            ),
            energy=slot["charge_kwh"],
            amps=slot["ampere"],
            solar=slot["solar_kwh"],
            grid=slot["grid_kwh"],
            duration=slot["duration_min"],
        )
        for slot in slots
    )


def _format_composite_schedule(schedule: dict[str, Any] | None) -> str:
    """Format the charger-computed schedule as readable time periods."""
    if not schedule:
        return "Nog geen laadschema van de laadpaal opgevraagd."

    response = schedule.get("data", schedule)
    charging_schedule = response.get("chargingSchedule") or response.get(
        "charging_schedule", {}
    )
    if not isinstance(charging_schedule, dict):
        return "De laadpaal gaf geen geldig laadschema terug."

    status = response.get("status")
    if status and status != "Accepted":
        return f"Laadschema niet geaccepteerd: {status}."

    raw_periods = charging_schedule.get("chargingSchedulePeriod") or charging_schedule.get(
        "charging_schedule_period", []
    )
    periods = []
    for period in raw_periods:
        try:
            offset = int(period.get("startPeriod", period.get("start_period")))
            limit = float(period["limit"])
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        phases = period.get("numberPhases", period.get("number_phases"))
        periods.append((offset, limit, phases))

    if not periods:
        return "De laadpaal heeft geen laadperioden teruggegeven."
    periods.sort(key=lambda period: period[0])

    base_time = _parse_timestamp(
        response.get("scheduleStart")
        or response.get("schedule_start")
        or charging_schedule.get("startSchedule")
        or charging_schedule.get("start_schedule")
    )
    try:
        duration = int(charging_schedule.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    unit = charging_schedule.get("chargingRateUnit") or charging_schedule.get(
        "charging_rate_unit", "A"
    )

    lines = [f"Status: {status}"] if status else []
    for index, (offset, limit, phases) in enumerate(periods):
        end_offset = (
            periods[index + 1][0]
            if index + 1 < len(periods)
            else duration
        )
        if base_time is not None and end_offset > offset:
            start_text = (base_time + timedelta(seconds=offset)).strftime("%d-%m %H:%M")
            end_text = (base_time + timedelta(seconds=end_offset)).strftime("%d-%m %H:%M")
            interval = f"{start_text} - {end_text}"
        else:
            interval = f"vanaf +{offset // 60} min"
        limit_text = "geen laden" if limit == 0 else f"{limit:g} {unit}"
        if phases:
            limit_text += f", {phases} fasen"
        lines.append(f"- {interval}: {limit_text}")

    return "\n".join(lines)


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



    def _cancel_pending_refresh(self) -> None:
        if self._cancel_refresh is not None:
            self._cancel_refresh()
            self._cancel_refresh = None

    @property
    def native_value(self) -> datetime | None:
        return self._next_occurrence
