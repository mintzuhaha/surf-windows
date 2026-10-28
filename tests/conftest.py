"""Shared test helpers: a fixed config (independent of config.yaml) and an hour factory."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from surf.normalize import Hour

TZ = ZoneInfo("America/Los_Angeles")
FIXTURES = Path(__file__).parent / "fixtures"

CONFIG: dict[str, Any] = {
    "spot": {
        "id": "pleasure-point", "name": "Pleasure Point", "lat": 36.95469, "lon": -121.97253,
        "timezone": "America/Los_Angeles", "noaa_station": "9413450", "faces_deg": 180, "size_factor": 1.4,
        "high_tide_ft": 4.2, "ideal_tide_ft": 3.7,
    },
    "size_buckets": {
        "knee": [1.0, 2.0], "waist": [2.0, 3.0], "chest": [3.0, 4.0],
        "head": [4.0, 5.5], "overhead": [5.5, 6.5], "way_over": [6.5, 99.0],
    },
    "preferences": {
        "size": {"knee": "skip", "waist": "ok", "chest": "fav", "head": "fav", "overhead": "ok", "way_over": "skip"},
        "tide": {"low": "ok", "mid": "ok", "high": "skip"},
        "tide_direction": {"rising": True, "falling": True},
        "wind": {"glassy": "fav", "light": "ok", "windy": "skip"},
        "rain": {"skip_after_hours": 72, "threshold_in": 0.1},
        "warn_sizes": ["overhead"],
        "min_window_hours": 2,
        "tentative_after_days": 3,
        "daylight": {"before_sunrise_min": 60, "after_sunset_min": 60},
    },
}


def local(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def make_hour(start: datetime | None = None, **overrides: Any) -> Hour:
    """A good hour by default: Wed Oct 28 8am, 3-4 ft+ (chest), glassy offshore, low rising, dry."""
    start = start or local(2026, 10, 28, 8)
    day = start.replace(hour=0, minute=0)
    hour = Hour(
        start=start,
        swell_height_m=0.7, swell_period_s=12.0, swell_direction_deg=205.0,
        wave_height_m=0.8, wave_period_s=11.0, wave_direction_deg=205.0,
        wind_speed_mph=3.0, wind_direction_deg=0.0, wind_gust_mph=5.0,
        rain_prior_in=0.0,
        tide_ft=1.0, tide_next_ft=1.5, tide_day_low_ft=0.0, tide_day_high_ft=6.0,
        sunrise=day.replace(hour=7, minute=25), sunset=day.replace(hour=18, minute=12),
    )
    return replace(hour, **overrides)


@pytest.fixture
def config() -> dict[str, Any]:
    return copy.deepcopy(CONFIG)


@pytest.fixture
def raw() -> dict[str, dict[str, Any]]:
    return {name: json.loads((FIXTURES / f"{name}.json").read_text()) for name in ("marine", "forecast", "tides")}


@pytest.fixture
def recorded_at() -> datetime:
    return datetime.fromisoformat(json.loads((FIXTURES / "meta.json").read_text())["recorded_at"])
