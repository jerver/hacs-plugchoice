"""Charging schedule calculation for PlugChoice."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.util import dt as dt_util

PLAN_TIMEZONE = ZoneInfo("Europe/Amsterdam")
KW_PER_AMP = 230 / 1000
MAX_CHARGING_KW = 16 * KW_PER_AMP


def build_schedule(
    *,
    distance_km: float,
    km_per_kwh: float,
    deadline: datetime,
    forecasts: list[dict[str, Any]],
    now: datetime,
    direct: bool = False,
    min_solar_kwh: float = 0.3,
) -> dict[str, Any]:
    """Build a feasible charging plan from hourly Solcast forecasts."""
    if distance_km <= 0 or km_per_kwh <= 0:
        raise ValueError("Distance and vehicle efficiency must be positive")
    now = (
        now.replace(tzinfo=PLAN_TIMEZONE)
        if now.tzinfo is None
        else now.astimezone(PLAN_TIMEZONE)
    ).astimezone(timezone.utc)
    deadline = (
        deadline.replace(tzinfo=PLAN_TIMEZONE)
        if deadline.tzinfo is None
        else deadline.astimezone(PLAN_TIMEZONE)
    ).astimezone(timezone.utc)
    if deadline <= now:
        raise ValueError("Deadline must be in the future")

    required_kwh = distance_km / km_per_kwh
    solar_by_hour = _solar_by_hour(forecasts)
    windows = _make_windows(now, deadline, solar_by_hour)
    max_available_kwh = sum(
        MAX_CHARGING_KW * _window_hours(window) for window in windows
    )

    if required_kwh > max_available_kwh + 0.1:
        hourly_energy = _hourly_energy(windows, [])
        return {
            "feasible": False,
            "error": "Insufficient charging time before the deadline",
            "required_kwh": round(required_kwh, 3),
            "max_available_kwh": round(max_available_kwh, 3),
            "solar_kwh": 0.0,
            "grid_kwh": 0.0,
            "schedule": [],
            "hourly_energy": hourly_energy,
        }

    remaining = required_kwh
    selected: dict[datetime, dict[str, Any]] = {}

    if direct:
        ordered_windows = windows
    else:
        ordered_windows = sorted(
            (window for window in windows if window["solar_kwh"] >= min_solar_kwh),
            key=lambda window: (-window["solar_kwh"], window["start"]),
        )

    for window in ordered_windows:
        if remaining <= 0:
            break
        amps = 16 if direct else _amps_for_solar(window["solar_kwh"])
        capacity = amps * KW_PER_AMP * _window_hours(window)
        energy = min(remaining, capacity)
        if energy <= 0:
            continue
        selected[window["period_start"]] = {
            "window": window,
            "amps": amps,
            "energy": energy,
            "phase": 3 if direct else 1,
        }
        remaining -= energy

    if not direct and remaining > 0:
        for slot in sorted(selected.values(), key=lambda item: -item["window"]["solar_kwh"]):
            if remaining <= 0 or slot["amps"] >= 16:
                continue
            window = slot["window"]
            extra_capacity = (16 - slot["amps"]) * KW_PER_AMP * _window_hours(window)
            extra = min(remaining, extra_capacity)
            slot["energy"] += extra
            slot["amps"] = 16
            remaining -= extra

    if remaining > 0:
        for window in windows:
            if remaining <= 0 or window["period_start"] in selected:
                continue
            energy = min(remaining, MAX_CHARGING_KW * _window_hours(window))
            if energy <= 0:
                continue
            selected[window["period_start"]] = {
                "window": window,
                "amps": 16,
                "energy": energy,
                "phase": 3,
            }
            remaining -= energy

    schedule = [
        _make_slot(
            slot["window"],
            slot["amps"],
            slot["energy"],
            align_partial=slot["phase"] == 1,
        )
        for slot in sorted(selected.values(), key=lambda item: item["window"]["start"])
    ]
    solar_total = sum(slot["solar_kwh"] for slot in schedule)
    grid_total = sum(slot["grid_kwh"] for slot in schedule)
    return {
        "feasible": True,
        "error": None,
        "required_kwh": round(required_kwh, 3),
        "max_available_kwh": round(max_available_kwh, 3),
        "solar_kwh": round(solar_total, 3),
        "grid_kwh": round(grid_total, 3),
        "schedule": schedule,
        "hourly_energy": _hourly_energy(windows, schedule),
    }


def _hourly_energy(
    windows: list[dict[str, Any]], schedule: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return forecast and scheduled energy values for every available hour."""
    scheduled_by_start = {
        datetime.fromisoformat(slot["period_start"]): slot for slot in schedule
    }
    hourly = []
    for window in windows:
        period_start = window["period_start"].astimezone(PLAN_TIMEZONE)
        slot = scheduled_by_start.get(period_start)
        hourly.append(
            {
                "period_start": period_start.isoformat(),
                "pv_forecast_kwh": window["solar_kwh"],
                "solar_kwh": slot["solar_kwh"] if slot else 0.0,
                "grid_kwh": slot["grid_kwh"] if slot else 0.0,
                "charge_kwh": slot["charge_kwh"] if slot else 0.0,
            }
        )
    return hourly


def _solar_by_hour(forecasts: list[dict[str, Any]]) -> dict[datetime, float]:
    solar_by_period: dict[datetime, float] = {}
    for item in forecasts:
        period_start = dt_util.parse_datetime(str(item.get("period_start", "")))
        if period_start is None:
            continue
        if period_start.tzinfo is None:
            period_start = period_start.replace(tzinfo=PLAN_TIMEZONE)
        period_start = period_start.astimezone(timezone.utc)
        try:
            solar_by_period[period_start] = max(
                0.0, float(item.get("pv_estimate", 0))
            )
        except (TypeError, ValueError):
            continue

    solar: dict[datetime, float] = {}
    for period_start, estimate in solar_by_period.items():
        hour_start = period_start.replace(minute=0, second=0, microsecond=0)
        solar[hour_start] = solar.get(hour_start, 0.0) + estimate
    return solar


def _make_windows(
    now: datetime, deadline: datetime, solar_by_hour: dict[datetime, float]
) -> list[dict[str, Any]]:
    windows = []
    hour_start = now.replace(minute=0, second=0, microsecond=0)
    while hour_start < deadline:
        hour_end = hour_start + timedelta(hours=1)
        start = max(now, hour_start)
        end = min(deadline, hour_end)
        if start < end:
            windows.append(
                {
                    "period_start": hour_start,
                    "start": start,
                    "end": end,
                    "solar_kwh": solar_by_hour.get(hour_start, 0.0),
                }
            )
        hour_start = hour_end
    return windows


def _window_hours(window: dict[str, Any]) -> float:
    return (window["end"] - window["start"]).total_seconds() / 3600


def _amps_for_solar(solar_kwh: float) -> int:
    return max(6, min(16, round(solar_kwh / KW_PER_AMP)))


def _make_slot(
    window: dict[str, Any], amps: int, energy: float, *, align_partial: bool
) -> dict[str, Any]:
    duration_min = energy / (amps * KW_PER_AMP) * 60
    period_start = window["period_start"]
    if (
        align_partial
        and duration_min < 59
        and period_start.astimezone(PLAN_TIMEZONE).hour < 12
    ):
        recommended_start = window["end"] - timedelta(minutes=duration_min)
    else:
        recommended_start = window["start"]
    solar_kwh = min(window["solar_kwh"] * duration_min / 60, energy)
    grid_kwh = max(0.0, energy - solar_kwh)
    return {
        "period_start": period_start.astimezone(PLAN_TIMEZONE).isoformat(),
        "recommended_start": recommended_start.astimezone(PLAN_TIMEZONE).isoformat(),
        "ampere": amps,
        "charge_kwh": round(energy, 3),
        "solar_kwh": round(solar_kwh, 3),
        "grid_kwh": round(grid_kwh, 3),
        "solar_pct": round(solar_kwh / energy * 100, 1) if energy else 0.0,
        "duration_min": round(duration_min, 1),
        "full_hour": duration_min >= 59,
    }