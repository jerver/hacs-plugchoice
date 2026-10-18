"""Persistent charging plan lifecycle and automatic execution."""
from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import PlugChoiceAPI, PlugChoiceDataUpdateCoordinator
from .const import (
    CONF_DEADLINE,
    CONF_DIRECT_CHARGING,
    CONF_DISTANCE_KM,
    CONF_EFFICIENCY_KM_PER_KWH,
    CONF_MIN_SOLAR_KWH,
    CONF_CONNECTOR_ID,
    CONF_DIRECT_CHARGING_AMP,
    CONF_TOKEN_ID,
    DEFAULT_CONNECTOR_ID,
    DEFAULT_DIRECT_CHARGING_AMP,
    DOMAIN,
    SOLCAST_FORECAST_ENTITIES,
)
from .schedule import build_schedule
from .schedule import PLAN_TIMEZONE

TX_DEFAULT_PROFILE_ID = 1
TX_PROFILE_ID = 2

class ChargingScheduleManager:
    """Create, persist, expose, and execute a charging schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: PlugChoiceAPI,
        coordinator: PlugChoiceDataUpdateCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.api = api
        self.coordinator = coordinator
        self.plan: dict[str, Any] | None = None
        self.composite_schedule: dict[str, Any] | None = None
        self.test_mode_message: dict[str, Any] | None = None
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_charging_plan")

    async def async_load(self) -> None:
        """Restore the latest calculated plan."""
        self.plan = await self._store.async_load()

    async def async_create_plan(self) -> dict[str, Any]:
        """Read options and Solcast entities, then persist the calculated plan."""
        options = self.entry.options
        try:
            distance_km = float(options[CONF_DISTANCE_KM])
            efficiency = float(options[CONF_EFFICIENCY_KM_PER_KWH])
            deadline = dt_util.parse_datetime(options[CONF_DEADLINE])
        except (KeyError, TypeError, ValueError) as err:
            raise HomeAssistantError("Configure distance, efficiency, and deadline first") from err
        if deadline is None:
            raise HomeAssistantError("The charging deadline is invalid")
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=PLAN_TIMEZONE)
        else:
            deadline = deadline.astimezone(PLAN_TIMEZONE)

        forecasts = []
        for entity_id in SOLCAST_FORECAST_ENTITIES:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            detailed_hourly = state.attributes.get("detailedHourly", [])
            if isinstance(detailed_hourly, list):
                forecasts.extend(detailed_hourly)

        if not forecasts:
            raise HomeAssistantError("No Solcast detailedHourly forecast data is available")

        now = dt_util.now().astimezone(PLAN_TIMEZONE)
        plan = build_schedule(
            distance_km=distance_km,
            km_per_kwh=efficiency,
            deadline=deadline,
            forecasts=forecasts,
            now=now,
            direct=bool(options.get(CONF_DIRECT_CHARGING, False)),
            min_solar_kwh=float(options.get(CONF_MIN_SOLAR_KWH, 0.3)),
        )
        plan["created_at"] = now.isoformat()
        plan["deadline"] = deadline.isoformat()
        plan["direct_charging"] = bool(options.get(CONF_DIRECT_CHARGING, False))
        self.test_mode_message = None
        self.plan = plan
        await self._store.async_save(plan)
        return plan

    async def async_start_optimal_charge(self) -> None:
        """Start a session, then apply the saved schedule to its transaction."""
        if self.plan is None:
            raise HomeAssistantError("Calculate a charging plan before starting optimal charging")
        if not self.plan.get("feasible"):
            raise HomeAssistantError("The calculated charging plan is not feasible")

        connector_id = int(
            self.entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
        )
        start_request = self.api.build_start_charging_request(
            self.entry.data[CONF_TOKEN_ID], connector_id
        )
        if self.api.test_mode:
            profile = _build_charging_profile(
                self.plan,
                TX_PROFILE_ID,
                dt_util.now(),
                "<transaction_id returned by start>",
            )
            profile_request = self.api.build_set_charging_profile_request(
                connector_id, profile
            )
            self.test_mode_message = {
                "actions": [
                    {"action": "start_charging", "request": start_request},
                    {"action": "set_charging_profile", "request": profile_request},
                ]
            }
            return

        self.test_mode_message = None
        start_response = await self.api.start_charging(
            token_id=self.entry.data[CONF_TOKEN_ID], connector_id=connector_id
        )
        transaction_id = _extract_transaction_id(start_response)
        profile = _build_charging_profile(
            self.plan, TX_PROFILE_ID, dt_util.now(), transaction_id
        )
        await self.api.set_charging_profile(connector_id, profile)

    async def async_start_direct_charge(self) -> None:
        """Start charging with the charger's default charging profile."""
        connector_id = int(
            self.entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
        )
        self.plan = None
        await self._store.async_remove()

        start_request = self.api.build_start_charging_request(
            self.entry.data[CONF_TOKEN_ID], connector_id
        )
        profile = _build_default_charging_profile(
            TX_DEFAULT_PROFILE_ID,
            dt_util.now(),
            float(
                self.entry.options.get(
                    CONF_DIRECT_CHARGING_AMP, DEFAULT_DIRECT_CHARGING_AMP
                )
            ),
        )
        profile_request = self.api.build_set_charging_profile_request(
            connector_id, profile
        )
        if self.api.test_mode:
            self.test_mode_message = {
                "actions": [
                    {"action": "set_charging_profile", "request": profile_request},
                    {"action": "start_charging", "request": start_request},
                ]
            }
            return

        self.test_mode_message = None
        await self.api.set_charging_profile(connector_id, profile)
        await self.api.start_charging(
            token_id=self.entry.data[CONF_TOKEN_ID], connector_id=connector_id
        )

    async def async_set_direct_charging_amp(self, ampere: float) -> None:
        """Apply a new default charging current immediately."""
        connector_id = int(
            self.entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
        )
        profile = _build_default_charging_profile(
            TX_DEFAULT_PROFILE_ID, dt_util.now(), ampere
        )
        request = self.api.build_set_charging_profile_request(connector_id, profile)
        if self.api.test_mode:
            self.test_mode_message = request
        else:
            self.test_mode_message = None
            await self.api.set_charging_profile(connector_id, profile)

    async def async_stop_charging(self) -> None:
        """Stop charging and remove the saved plan without deleting profiles."""
        active_tx = (self.coordinator.data or {}).get("active_transaction")
        transaction_id = active_tx.get("id") if active_tx else None
        self.plan = None
        await self._store.async_remove()

        stop_request = self.api.build_stop_charging_request(transaction_id)
        if self.api.test_mode:
            self.test_mode_message = {
                "actions": [{"action": "stop_charging", "request": stop_request}]
            }
            return

        self.test_mode_message = None
        await self.api.stop_charging(transaction_id=transaction_id)

    async def async_cancel_plan(self) -> None:
        """Remove the saved plan without deleting charger profiles."""
        self.test_mode_message = None
        self.plan = None
        await self._store.async_remove()

    async def async_request_composite_schedule(self) -> dict[str, Any]:
        """Fetch the charger schedule through the configured deadline."""
        now = dt_util.now()
        duration = 24 * 60 * 60
        deadline = dt_util.parse_datetime(
            str(self.entry.options.get(CONF_DEADLINE, ""))
        )
        if deadline is not None:
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=PLAN_TIMEZONE)
            seconds_to_deadline = int((deadline - now).total_seconds())
            if seconds_to_deadline > 0:
                duration = seconds_to_deadline

        connector_id = int(
            self.entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
        )
        request = self.api.build_composite_schedule_request(
            connector_id, duration, "A"
        )
        if self.api.test_mode:
            self.test_mode_message = request
            return request
        self.test_mode_message = None
        self.composite_schedule = await self.api.get_composite_schedule(
            connector_id=connector_id,
            duration=duration,
            charging_rate_unit="A",
        )
        return self.composite_schedule

def _build_charging_profile(
    plan: dict[str, Any],
    profile_id: int,
    uploaded_at: datetime,
    transaction_id: int | str,
) -> dict[str, Any]:
    """Convert planned periods into an OCPP transaction profile."""
    deadline = dt_util.parse_datetime(str(plan.get("deadline", "")))
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=PLAN_TIMEZONE)
    schedule_start = _round_to_second(uploaded_at.astimezone(timezone.utc))

    segments = []
    for slot in plan.get("schedule", []):
        start = dt_util.parse_datetime(str(slot.get("recommended_start", "")))
        try:
            duration = float(slot["duration_min"])
            limit = float(slot["ampere"])
        except (KeyError, TypeError, ValueError):
            continue
        if start is None or duration <= 0 or limit <= 0:
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=PLAN_TIMEZONE)
        start = _round_to_second(start.astimezone(timezone.utc))
        end = _round_to_second(start + timedelta(minutes=duration))
        if end > schedule_start:
            segments.append((start, end, limit))

    segments.sort(key=lambda segment: segment[0])
    if deadline is None or not segments:
        raise HomeAssistantError("The charging plan has no valid schedule periods")
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=PLAN_TIMEZONE)
    deadline = _round_to_second(deadline.astimezone(timezone.utc))

    duration_seconds = int((deadline - schedule_start).total_seconds())
    if duration_seconds <= 0:
        raise HomeAssistantError("The charging plan ends before it starts")

    active_segment = next(
        (
            segment
            for segment in segments
            if segment[0] <= schedule_start < segment[1]
        ),
        None,
    )
    periods = [
        {"start_period": 0, "limit": active_segment[2] if active_segment else 0}
    ]

    def add_period(start_period: int, limit: float) -> None:
        if periods[-1]["limit"] != limit:
            periods.append({"start_period": start_period, "limit": limit})

    previous_end = active_segment[1] if active_segment else schedule_start
    for segment in segments:
        start, end, limit = segment
        if segment == active_segment or end <= schedule_start:
            continue
        start = max(start, schedule_start)
        start_offset = round((start - schedule_start).total_seconds())
        previous_end_offset = round((previous_end - schedule_start).total_seconds())
        if start_offset > previous_end_offset and previous_end_offset > 0:
            add_period(previous_end_offset, 0)
        add_period(start_offset, limit)
        previous_end = max(previous_end, end)

    final_end_offset = round((previous_end - schedule_start).total_seconds())
    if final_end_offset < duration_seconds:
        add_period(final_end_offset, 0)

    return {
        "charging_profile_id": profile_id,
        "stack_level": 1,
        "charging_profile_purpose": "TxProfile",
        "charging_profile_kind": "Absolute",
        "transaction_id": transaction_id,
        "valid_from": _format_utc_timestamp(schedule_start),
        "valid_to": _format_utc_timestamp(deadline),
        "charging_schedule": {
            "duration": duration_seconds,
            "start_schedule": _format_utc_timestamp(schedule_start),
            "charging_rate_unit": "A",
            "charging_schedule_period": periods,
        },
    }


def _extract_transaction_id(response: dict[str, Any]) -> int:
    """Read the transaction ID from common start-response payload shapes."""
    payload = response.get("data", response)
    if isinstance(payload, dict):
        transaction_id = payload.get("transaction_id", payload.get("transactionId"))
        if transaction_id is None and isinstance(payload.get("transaction"), dict):
            transaction_id = payload["transaction"].get("id")
        if transaction_id is not None:
            try:
                return int(transaction_id)
            except (TypeError, ValueError) as err:
                raise HomeAssistantError(
                    "The start response contains an invalid transaction ID"
                ) from err
    raise HomeAssistantError("The start response did not contain a transaction ID")


def _build_default_charging_profile(
    profile_id: int, uploaded_at: datetime, ampere: float
) -> dict[str, Any]:
    """Build a default profile with the selected direct-charging current."""
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=PLAN_TIMEZONE)
    schedule_start = _round_to_second(uploaded_at.astimezone(timezone.utc))
    return {
        "charging_profile_id": profile_id,
        "stack_level": 1,
        "charging_profile_purpose": "TxDefaultProfile",
        "charging_profile_kind": "Absolute",
        "valid_from": _format_utc_timestamp(schedule_start),
        "charging_schedule": {
            "start_schedule": _format_utc_timestamp(schedule_start),
            "charging_rate_unit": "A",
            "charging_schedule_period": [{"start_period": 0, "limit": ampere}],
        },
    }


def _round_to_second(value: datetime) -> datetime:
    """Round a datetime to the nearest whole second."""
    return (value + timedelta(microseconds=500_000)).replace(microsecond=0)


def _format_utc_timestamp(value: datetime) -> str:
    """Format a UTC timestamp with whole-second precision and a Z suffix."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )