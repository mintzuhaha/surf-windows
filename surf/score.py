"""Classify each hour against the preferences. Pure functions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from surf.normalize import Hour

# Face-height model. Starting guesses: log any change in DECISIONS.md.
FT_PER_M = 3.281
PERIOD_BASE_S = 10.0
PERIOD_GAIN_PER_S = 0.05
PERIOD_FACTOR_MAX = 1.4

# Wind classes.
OFFSHORE_HALF_ANGLE_DEG = 60.0
GLASSY_BELOW_MPH = 5.0
LIGHT_MAX_MPH = 12.0

FLAT = "flat"  # face height below the smallest bucket
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
    face_ft: float | None
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


def period_factor(period_s: float) -> float:
    return min(PERIOD_FACTOR_MAX, 1 + PERIOD_GAIN_PER_S * max(0.0, period_s - PERIOD_BASE_S))


def face_height_ft(hour: Hour, size_factor: float) -> float | None:
    height, period = hour.swell_height_m, hour.swell_period_s
    if height is None or period is None:
        height, period = hour.wave_height_m, hour.wave_period_s
    if height is None or period is None:
        return None
    return height * FT_PER_M * period_factor(period) * size_factor


def size_bucket(face_ft: float | None, buckets: dict[str, list[float]]) -> str:
    """Bucket whose [min, max) contains face_ft."""
    if face_ft is None:
        return UNKNOWN
    for name, (low, high) in buckets.items():
        if low <= face_ft < high:
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


def tide_level(tide_ft: float, day_low_ft: float, day_high_ft: float) -> str:
    span = day_high_ft - day_low_ft
    if span <= 0:
        return "mid"
    position = (tide_ft - day_low_ft) / span
    if position < 1 / 3:
        return "low"
    if position > 2 / 3:
        return "high"
    return "mid"


def tide_direction(tide_ft: float, next_tide_ft: float) -> str:
    return "rising" if next_tide_ft > tide_ft else "falling"


def is_daylight(hour: Hour) -> bool:
    return hour.start >= hour.dawn and hour.end <= hour.sunset


def is_free(start: datetime, free_hours: dict[str, list[list[int]]]) -> bool:
    slots = free_hours["weekends" if start.weekday() >= 5 else "weekdays"]
    return any(slot_start <= start.hour and start.hour + 1 <= slot_end for slot_start, slot_end in slots)


def score_hour(hour: Hour, config: dict[str, Any]) -> ScoredHour:
    spot, prefs = config["spot"], config["preferences"]
    face = face_height_ft(hour, spot["size_factor"])
    size = size_bucket(face, config["size_buckets"])
    aspect = wind_aspect(hour.wind_direction_deg, spot["faces_deg"])
    wind = wind_class(hour.wind_speed_mph, aspect)
    level = tide_level(hour.tide_ft, hour.tide_day_low_ft, hour.tide_day_high_ft)
    direction = tide_direction(hour.tide_ft, hour.tide_next_ft)
    states = {
        "daylight": "ok" if is_daylight(hour) else "skip",
        "free": "ok" if is_free(hour.start, prefs["free_hours"]) else "skip",
        "rain": "skip" if hour.rain_prior_in >= prefs["rain"]["threshold_in"] else "ok",
        "size": prefs["size"].get(size, "skip"),
        "wind": prefs["wind"].get(wind, "skip"),
        "tide": prefs["tide"].get(level, "skip"),
        "tide_direction": "ok" if prefs["tide_direction"].get(direction, False) else "skip",
    }
    failures = tuple(REASONS.get(c, c) for c in CHECKS if states[c] == "skip")
    return ScoredHour(hour, face, size, wind, aspect, level, direction, states, failures)


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
    if sh.face_ft is None:
        size = "No swell data"
    else:
        use_swell = h.swell_height_m is not None and h.swell_period_s is not None
        height = h.swell_height_m if use_swell else h.wave_height_m
        period = h.swell_period_s if use_swell else h.wave_period_s
        direction = h.swell_direction_deg if use_swell else h.wave_direction_deg
        size = (f"{size_label(sh.size).capitalize()}, {sh.face_ft:.1f} ft faces "
                f"({height:.1f} m at {period:.0f} s from {compass(direction)})")
    rain_hours = config["preferences"]["rain"]["skip_after_hours"]
    if h.rain_prior_in == 0:
        rain = f"No rain in the prior {rain_hours} hours"
    else:
        rain = f'{h.rain_prior_in:.2f}" of rain in the prior {rain_hours} hours'
    return {
        "size": size,
        "wind": f"{sh.wind.capitalize()}, {h.wind_speed_mph:.0f} mph {sh.wind_aspect}",
        "tide": f"{sh.tide_level.capitalize()}, {sh.tide_direction} ({h.tide_ft:.1f} → {h.tide_next_ft:.1f} ft)",
        "rain": rain,
        "daylight": f"Sunrise {format_time(h.sunrise)}, sunset {format_time(h.sunset)}",
    }
