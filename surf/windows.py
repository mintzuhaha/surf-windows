"""Merge passing hours into windows and find near misses. Pure functions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from surf.score import (
    FLAT, UNKNOWN, ScoredHour, daylight_text, format_time, rain_text, size_label, swell_detail,
)

NEAR_MISS_LIMIT = 5
NEAR_MISSES_BELOW = 2  # near misses are returned when there are fewer windows than this
FAV_FACTORS = ("size", "wind", "tide")


@dataclass(frozen=True)
class Window:
    id: str
    hours: tuple[ScoredHour, ...]
    favored: bool
    tentative: bool
    days_out: int  # calendar days after today

    @property
    def start(self) -> datetime:
        return self.hours[0].hour.start

    @property
    def end(self) -> datetime:
        return self.hours[-1].hour.end

    @property
    def size(self) -> str:
        return _most_common([h.size for h in self.hours])

    @property
    def wind(self) -> str:
        return _most_common([h.wind for h in self.hours])

    @property
    def tide_level(self) -> str:
        return _most_common([h.tide_level for h in self.hours])


@dataclass(frozen=True)
class NearMiss:
    hour: ScoredHour
    text: str  # e.g. "Thu 8am: chest-high, but 14 mph onshore"


def find_windows(scored: list[ScoredHour], config: dict[str, Any], today: date) -> list[Window]:
    """Runs of consecutive passing hours within one day, at least min_window_hours long."""
    prefs = config["preferences"]
    runs: list[list[ScoredHour]] = []
    for sh in scored:
        if not sh.passes:
            continue
        if runs and _continues(runs[-1][-1], sh):
            runs[-1].append(sh)
        else:
            runs.append([sh])

    windows = []
    for run in runs:
        if len(run) < prefs["min_window_hours"]:
            continue
        start = run[0].hour.start
        days_out = (start.date() - today).days
        windows.append(
            Window(
                id=f"{config['spot']['id']}-{start:%Y%m%d}-{start.hour:02d}",
                hours=tuple(run),
                favored=2 * sum(h.favored for h in run) >= len(run),
                tentative=days_out >= prefs["tentative_after_days"],
                days_out=days_out,
            )
        )
    return windows


def describe_window(w: Window, config: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(factor, text, state) for size, wind, tide, rain and daylight. State is fav or ok."""
    first, last = w.hours[0].hour, w.hours[-1].hour
    peak = max(w.hours, key=lambda h: h.face_ft or 0.0)
    faces = [h.face_ft for h in w.hours if h.face_ft is not None]
    speeds = [h.hour.wind_speed_mph for h in w.hours]
    aspect = _most_common([h.wind_aspect for h in w.hours])
    levels = " to ".join(_unique([h.tide_level for h in w.hours]))
    directions = " then ".join(_unique([h.tide_direction for h in w.hours]))
    def state(factor: str) -> str:
        return _most_common([h.states[factor] for h in w.hours])

    return [
        ("size", f"{size_label(w.size).capitalize()}, {_span(faces)} ft faces ({swell_detail(peak.hour)})", state("size")),
        ("wind", f"{w.wind.capitalize()}, {_span(speeds)} mph {aspect}", state("wind")),
        ("tide", f"{levels.capitalize()}, {directions} ({first.tide_ft:.1f} → {last.tide_next_ft:.1f} ft)", state("tide")),
        ("rain", rain_text(max(h.hour.rain_prior_in for h in w.hours), config), "ok"),
        ("daylight", daylight_text(first), "ok"),
    ]


def find_near_misses(
    scored: list[ScoredHour], windows: list[Window], config: dict[str, Any]
) -> list[NearMiss]:
    """Daylight, free hours that failed exactly one factor, best first, in time order.

    Keeps only the best hour per (day, reason) so one windy morning doesn't
    fill the list.
    """
    if len(windows) >= NEAR_MISSES_BELOW:
        return []
    candidates = [sh for sh in scored if len(sh.failures) == 1 and sh.reason not in ("dark", "busy")]
    candidates.sort(key=lambda sh: (-_fav_count(sh), sh.hour.start))
    picked: dict[tuple[date, str], ScoredHour] = {}
    for sh in candidates:
        picked.setdefault((sh.hour.start.date(), sh.reason or ""), sh)
    best = list(picked.values())[:NEAR_MISS_LIMIT]
    best.sort(key=lambda sh: sh.hour.start)
    return [NearMiss(sh, near_miss_text(sh, config)) for sh in best]


def near_miss_text(sh: ScoredHour, config: dict[str, Any]) -> str:
    start = sh.hour.start
    when = f"{start:%a} {format_time(start, minutes=False)}"
    lead = sh.wind if sh.reason == "size" else size_label(sh.size)
    return f"{when}: {lead}, but {_miss_phrase(sh, config)}"


def _miss_phrase(sh: ScoredHour, config: dict[str, Any]) -> str:
    h = sh.hour
    if sh.reason == "rain":
        return rain_text(h.rain_prior_in, config)
    if sh.reason == "size":
        if sh.size in (FLAT, UNKNOWN):
            return size_label(sh.size)
        names = list(config["size_buckets"])
        wanted = [n for n in names if config["preferences"]["size"].get(n, "skip") != "skip"]
        if wanted and names.index(sh.size) < names.index(wanted[0]):
            return f"only {size_label(sh.size)}"
        return f"too big ({size_label(sh.size)})"
    if sh.reason == "wind":
        return f"{h.wind_speed_mph:.0f} mph {sh.wind_aspect}"
    if sh.reason == "tide":
        return f"{sh.tide_level} tide ({h.tide_ft:.1f} ft)"
    return f"tide {sh.tide_direction}"


def _continues(prev: ScoredHour, sh: ScoredHour) -> bool:
    # Same tzinfo, so this compares wall-clock times.
    return sh.hour.start == prev.hour.end and sh.hour.start.date() == prev.hour.start.date()


def _fav_count(sh: ScoredHour) -> int:
    return sum(sh.states[f] == "fav" for f in FAV_FACTORS)


def _most_common(values: list[str]) -> str:
    return Counter(values).most_common(1)[0][0]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _span(values: list[float]) -> str:
    """"3" or "3–4", rounded to whole numbers."""
    low, high = round(min(values)), round(max(values))
    return f"{low}" if low == high else f"{low}–{high}"
