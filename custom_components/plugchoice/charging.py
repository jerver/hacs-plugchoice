"""Persistent charging plan lifecycle and automatic execution."""
from __future__ import annotations

import logging
from datetime import timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_point_in_time
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
    CONF_TOKEN_ID,
    DEFAULT_CONNECTOR_ID,
    DOMAIN,
    SOLCAST_FORECAST_ENTITIES,
)
from .schedule import build_schedule
from .schedule import PLAN_TIMEZONE

_LOGGER = logging.getLogger(__name__)


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
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}_charging_plan")
        self._cancel_callbacks: list[Any] = []

    async def async_load(self) -> None:
        """Restore the latest plan and re-arm future actions."""
        self.plan = await self._store.async_load()
        if self.plan and self.plan.get("feasible"):
            self._arm_plan()

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
        self.plan = plan
        await self._store.async_save(plan)
        self._cancel_timers()
        if plan["feasible"]:
            self._arm_plan()
        return plan

    async def async_cancel_plan(self) -> None:
        """Cancel scheduled actions and remove the saved plan."""
        self._cancel_timers()
        self.plan = None
        await self._store.async_remove()

    def async_unload(self) -> None:
        """Cancel in-memory timers when the config entry unloads."""
        self._cancel_timers()

    def _arm_plan(self) -> None:
        """Schedule remote start/stop calls for all contiguous charging periods."""
        if not self.plan or self.api.test_mode:
            return
        intervals = []
        for slot in self.plan.get("schedule", []):
            start = dt_util.parse_datetime(slot["recommended_start"])
            if start is None:
                continue
            start = start.astimezone(timezone.utc)
            end = start + timedelta(minutes=float(slot["duration_min"]))
            if intervals and start <= intervals[-1][1] + timedelta(seconds=1):
                intervals[-1] = (intervals[-1][0], max(intervals[-1][1], end))
            else:
                intervals.append((start, end))

        now = dt_util.now().astimezone(timezone.utc)
        for start, end in intervals:
            if end <= now:
                continue
            start_at = max(start, now)
            self._cancel_callbacks.append(
                async_track_point_in_time(
                    self.hass,
                    lambda _when: self.hass.async_create_task(self._async_start()),
                    start_at,
                )
            )
            self._cancel_callbacks.append(
                async_track_point_in_time(
                    self.hass,
                    lambda _when: self.hass.async_create_task(self._async_stop()),
                    end,
                )
            )

    async def _async_start(self) -> None:
        """Start a charging transaction at the scheduled time."""
        if self.api.test_mode:
            return
        try:
            await self.api.start_charging(
                token_id=self.entry.data[CONF_TOKEN_ID],
                connector_id=int(
                    self.entry.options.get(CONF_CONNECTOR_ID, DEFAULT_CONNECTOR_ID)
                ),
            )
            await self.coordinator.async_request_refresh()
        except Exception:
            _LOGGER.exception("Failed to start PlugChoice charging schedule")

    async def _async_stop(self) -> None:
        """Stop the active transaction at the scheduled end time."""
        if self.api.test_mode:
            return
        active_tx = (self.coordinator.data or {}).get("active_transaction")
        transaction_id = active_tx.get("id") if active_tx else None
        try:
            await self.api.stop_charging(transaction_id=transaction_id)
            await self.coordinator.async_request_refresh()
        except Exception:
            _LOGGER.exception("Failed to stop PlugChoice charging schedule")

    def _cancel_timers(self) -> None:
        for cancel in self._cancel_callbacks:
            cancel()
        self._cancel_callbacks.clear()