"""Classify each hour against the preferences. Pure functions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from surf.normalize import Hour

# Surf-height model, in Surfline's ft scale. Fitted 2026-10-27 to 59 Surfline forecasts for
# Pleasure Point (Oct 28-Nov 4); spot.size_factor is the overall gain. Log refits in DECISIONS.md.
FT_PER_M = 3.281
PERIOD_REF_S = 10.0
PERIOD_POWER = 0.8  # longer-period swell breaks bigger
WESTERLY_FROM_DEG = 245.0  # W/NW swells wrap into the point and lose size
WESTERLY_WEIGHT = 0.8

# Surfline-style ranges: (from ft, label). Size buckets in config use the same scale.
SURF_RANGES = (
    (0.0, "0–1 ft"), (1.0, "1–2 ft"), (1.6, "1–2 ft+"), (2.0, "2–3 ft"), (2.6, "2–3 ft+"), (3.0, "3–4 ft"),
    (3.6, "3–4 ft+"), (4.0, "4–5 ft"), (4.75, "4–6 ft"), (5.15, "4–6 ft+"), (5.5, "5–7 ft"), (6.5, "6–8 ft"),
    (8.0, "8–10 ft"), (10.0, "10–12 ft"), (12.0, "12–15 ft"), (15.0, "15–20 ft"),
)

# Wind classes.
OFFSHORE_HALF_ANGLE_DEG = 60.0
GLASSY_BELOW_MPH = 5.0
LIGHT_MAX_MPH = 12.0

# An hour starting this soon before civil dawn still counts as daylight. In autumn
# dawn lands a minute or two after 7:00, which would otherwise drop the 7am hour.
DAWN_GRACE = timedelta(minutes=15)

FLAT = "flat"  # surf height below the smallest bucket
UNKNOWN = "unknown"  # no wave data at all

# Checks in the order they are reported: hard filters first, then factors.
CHECKS = ("daylight", "free", "rain", "size", "wind", "tide", "tide_direction")
# Failure reason names where they differ from the check name.
REASONS = {"daylight": "dark", "free": "busy"}

SIZE_LABELS = {
    FLAT: "flat",
    UNKNOWN: "no swell data",
    "knee": "knee-high",
    "waist": "waist-high",
    "chest": "chest-high",
    "head": "head-high",
    "overhead": "overhead",
    "way_over": "way overhead",
}
COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


@dataclass(frozen=True)
class ScoredHour:
    hour: Hour
    surf_ft: float | None  # Surfline-scale surf height
    size: str  # size bucket name, FLAT or UNKNOWN
    wind: str  # glassy | light | windy
    wind_aspect: str  # offshore | onshore | cross-shore
    tide_level: str  # low | mid | high
    tide_direction: str  # rising | falling
    states: dict[str, str]  # check name -> skip | ok | fav
    failures: tuple[str, ...]  # every failed check as a reason name, in CHECKS order

    @property
    def passes(self) -> bool:
        return not self.failures

    @property
    def reason(self) -> str | None:
        return self.failures[0] if self.failures else None

    @property
    def favored(self) -> bool:
        s = self.states
        return self.passes and s["size"] == "fav" and (s["wind"] == "fav" or s["tide"] == "fav")


def swell_contribution(height_m: float, period_s: float, from_deg: float | None) -> float:
    """One swell's share of the surf height, before the spot's gain."""
    weight = WESTERLY_WEIGHT if from_deg is not None and from_deg >= WESTERLY_FROM_DEG else 1.0
    return height_m * FT_PER_M * (period_s / PERIOD_REF_S) ** PERIOD_POWER * weight


def _swell_parts(hour: Hour) -> list[tuple[float, float, float | None]]:
    """Swell partitions, falling back to the combined sea when none are reported."""
    if hour.swells:
        return hour.swells
    if hour.wave_height_m and hour.wave_period_s:
        return [(hour.wave_height_m, hour.wave_period_s, hour.wave_direction_deg)]
    return []


def surf_height_ft(hour: Hour, size_factor: float) -> float | None:
    """Surfline-scale surf height: the energy sum of every swell's contribution, times the spot's gain."""
    parts = _swell_parts(hour)
    if not parts:
        return None
    return size_factor * math.sqrt(sum(swell_contribution(*p) ** 2 for p in parts))


def surf_range(surf_ft: float) -> str:
    """Surfline-style label, e.g. 3–4 ft+."""
    return [label for start, label in SURF_RANGES if surf_ft >= start][-1]


def size_bucket(surf_ft: float | None, buckets: dict[str, list[float]]) -> str:
    """Bucket whose [min, max) contains surf_ft."""
    if surf_ft is None:
        return UNKNOWN
    for name, (low, high) in buckets.items():
        if low <= surf_ft < high:
            return name
    return FLAT


def angle_between(a_deg: float, b_deg: float) -> float:
    d = abs(a_deg - b_deg) % 360
    return min(d, 360 - d)


def wind_aspect(wind_from_deg: float, faces_deg: float) -> str:
    if angle_between(wind_from_deg, (faces_deg + 180) % 360) <= OFFSHORE_HALF_ANGLE_DEG:
        return "offshore"
    if angle_between(wind_from_deg, faces_deg) <= OFFSHORE_HALF_ANGLE_DEG:
        return "onshore"
    return "cross-shore"


def wind_class(speed_mph: float, aspect: str) -> str:
    if speed_mph < GLASSY_BELOW_MPH or aspect == "offshore":
        return "glassy"
    if speed_mph <= LIGHT_MAX_MPH:
        return "light"
    return "windy"


def tide_level(tide_ft: float, next_tide_ft: float, day_low_ft: float, day_high_ft: float, high_tide_ft: float) -> str:
    """`high` if the tide reaches the break's limit during the hour; otherwise `low` in the
    bottom third of the day's range, else `mid`."""
    if max(tide_ft, next_tide_ft) >= high_tide_ft:
        return "high"
    span = day_high_ft - day_low_ft
    if span > 0 and (tide_ft - day_low_ft) / span < 1 / 3:
        return "low"
    return "mid"


def tide_direction(tide_ft: float, next_tide_ft: float) -> str:
    return "rising" if next_tide_ft > tide_ft else "falling"


def is_daylight(hour: Hour) -> bool:
    return hour.start + DAWN_GRACE >= hour.dawn and hour.end <= hour.sunset


def is_free(start: datetime, free_hours: dict[str, list[list[int]]]) -> bool:
    slots = free_hours["weekends" if start.weekday() >= 5 else "weekdays"]
    return any(slot_start <= start.hour and start.hour + 1 <= slot_end for slot_start, slot_end in slots)


def score_hour(hour: Hour, config: dict[str, Any]) -> ScoredHour:
    spot, prefs = config["spot"], config["preferences"]
    surf = surf_height_ft(hour, spot["size_factor"])
    size = size_bucket(surf, config["size_buckets"])
    aspect = wind_aspect(hour.wind_direction_deg, spot["faces_deg"])
    wind = wind_class(hour.wind_speed_mph, aspect)
    level = tide_level(hour.tide_ft, hour.tide_next_ft, hour.tide_day_low_ft, hour.tide_day_high_ft, spot["high_tide_ft"])
    direction = tide_direction(hour.tide_ft, hour.tide_next_ft)
    states = {
        "daylight": "ok" if is_daylight(hour) else "skip",
        "free": "ok" if is_free(hour.start, prefs["free_hours"]) else "skip",
        "rain": "skip" if hour.rain_prior_in >= prefs["rain"]["threshold_in"] else "ok",
        "size": prefs["size"].get(size, "skip"),
        "wind": prefs["wind"].get(wind, "skip"),
        "tide": _tide_state(hour, level, prefs["tide"], spot["ideal_tide_ft"]),
        "tide_direction": "ok" if prefs["tide_direction"].get(direction, False) else "skip",
    }
    failures = tuple(REASONS.get(c, c) for c in CHECKS if states[c] == "skip")
    return ScoredHour(hour, surf, size, wind, aspect, level, direction, states, failures)


def _tide_state(hour: Hour, level: str, tide_prefs: dict[str, str], ideal_tide_ft: float) -> str:
    """The level's preference, upgraded to fav while the tide stays below the break's ideal."""
    state = tide_prefs.get(level, "skip")
    if state != "skip" and max(hour.tide_ft, hour.tide_next_ft) < ideal_tide_ft:
        return "fav"
    return state


def score_hours(hours: list[Hour], config: dict[str, Any]) -> list[ScoredHour]:
    return [score_hour(h, config) for h in hours]


# --- Explanations ---------------------------------------------------------


def format_time(dt: datetime, minutes: bool = True) -> str:
    """7:24am, or 7am with minutes=False."""
    hour12 = dt.hour % 12 or 12
    suffix = "am" if dt.hour < 12 else "pm"
    return f"{hour12}:{dt.minute:02d}{suffix}" if minutes else f"{hour12}{suffix}"


def compass(deg: float | None) -> str:
    return "?" if deg is None else COMPASS[round(deg / 22.5) % 16]


def size_label(size: str) -> str:
    return SIZE_LABELS.get(size, size.replace("_", " "))


def explain(sh: ScoredHour, config: dict[str, Any]) -> dict[str, str]:
    """One line per factor: size, wind, tide, rain, daylight."""
    h = sh.hour
    if sh.surf_ft is None:
        size = "No swell data"
    else:
        size = f"{surf_range(sh.surf_ft)}, {size_label(sh.size)} ({swell_detail(h)})"
    return {
        "size": size,
        "wind": f"{sh.wind.capitalize()}, {h.wind_speed_mph:.0f} mph {sh.wind_aspect}",
        "tide": f"{sh.tide_level.capitalize()}, {sh.tide_direction} ({h.tide_ft:.1f} → {h.tide_next_ft:.1f} ft)",
        "rain": rain_text(h.rain_prior_in, config),
        "daylight": daylight_text(h),
    }


def swell_detail(h: Hour) -> str:
    """The swells behind the surf height, biggest first, e.g. "2.6 ft at 13 s from SSW + 1.2 ft at 10 s from WNW".

    Shows at most two, skipping any under a quarter of the biggest one's contribution."""
    parts = sorted(_swell_parts(h), key=lambda p: -swell_contribution(*p))
    if not parts:
        return "no swell data"
    top = swell_contribution(*parts[0])
    shown = [p for p in parts[:2] if swell_contribution(*p) >= top / 4]
    return " + ".join(f"{m * FT_PER_M:.1f} ft at {t:.0f} s from {compass(d)}" for m, t, d in shown)


def rain_text(rain_in: float, config: dict[str, Any]) -> str:
    hours = config["preferences"]["rain"]["skip_after_hours"]
    if rain_in == 0:
        return f"No rain in the prior {hours} hours"
    return f'{rain_in:.2f}" of rain in the prior {hours} hours'


def daylight_text(h: Hour) -> str:
    return f"Sunrise {format_time(h.sunrise)}, sunset {format_time(h.sunset)}"
