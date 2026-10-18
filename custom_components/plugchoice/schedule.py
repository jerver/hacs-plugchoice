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

    if remaining > 0:
        for window in sorted(
            windows, key=lambda item: (item["solar_kwh"], item["start"])
        ):
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

    if not direct and remaining > 0:
        for slot in sorted(
            selected.values(),
            key=lambda item: (item["window"]["solar_kwh"], item["window"]["start"]),
        ):
            if remaining <= 0 or slot["amps"] >= 16:
                continue
            window = slot["window"]
            extra_capacity = (16 - slot["amps"]) * KW_PER_AMP * _window_hours(window)
            extra = min(remaining, extra_capacity)
            slot["energy"] += extra
            slot["amps"] = 16
            remaining -= extra

    schedule = [
        _make_slot(
            slot["window"],
            slot["amps"],
            slot["energy"],
            align_partial=slot["phase"] == 1,
        )
        for slot in sorted(selected.values(), key=lambda item: item["window"]["start"])
    ]
    hourly_energy = _hourly_energy(windows, schedule)
    schedule = _merge_adjacent_slots(schedule)
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
        "hourly_energy": hourly_energy,
    }


def _merge_adjacent_slots(schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Combine contiguous schedule slots with the same charging current."""
    slots = sorted(
        schedule,
        key=lambda slot: datetime.fromisoformat(slot["recommended_start"]),
    )
    merged: list[dict[str, Any]] = []
    previous_end: datetime | None = None
    for slot in slots:
        next_start = datetime.fromisoformat(slot["recommended_start"])
        slot_end = next_start + timedelta(minutes=slot["duration_min"])
        if merged and merged[-1]["ampere"] == slot["ampere"]:
            previous = merged[-1]
            if previous_end is not None and abs(
                (next_start - previous_end).total_seconds()
            ) <= 3:
                previous["duration_min"] = round(
                    previous["duration_min"] + slot["duration_min"], 1
                )
                for energy_key in ("charge_kwh", "solar_kwh", "grid_kwh"):
                    previous[energy_key] = round(
                        previous[energy_key] + slot[energy_key], 3
                    )
                previous["solar_pct"] = round(
                    previous["solar_kwh"] / previous["charge_kwh"] * 100, 1
                )
                previous["full_hour"] = previous["duration_min"] >= 59
                previous_end = slot_end
                continue
        merged.append(dict(slot))
        previous_end = slot_end
    return merged


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
        charge_kwh = slot["charge_kwh"] if slot else 0.0
        ampere = slot["ampere"] if slot else 0
        solar_kwh = slot["solar_kwh"] if slot else 0.0
        solar_ampere = ampere * solar_kwh / charge_kwh if charge_kwh else 0.0
        hourly.append(
            {
                "period_start": period_start.isoformat(),
                "pv_forecast_kwh": window["solar_kwh"],
                "solar_kwh": solar_kwh,
                "grid_kwh": slot["grid_kwh"] if slot else 0.0,
                "charge_kwh": charge_kwh,
                "solar_ampere": solar_ampere,
                "grid_ampere": ampere - solar_ampere,
                "ampere": ampere,
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
    estimated_amps = max(6, min(16, solar_kwh / KW_PER_AMP))
    return min((6, 8, 10, 13, 16), key=lambda amps: abs(amps - estimated_amps))


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