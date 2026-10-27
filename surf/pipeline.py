"""Fetch once, then run the pure stages. Both endpoints call run()."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from surf.fetch import fetch_all
from surf.normalize import normalize
from surf.score import ScoredHour, score_hours
from surf.windows import NearMiss, Window, find_near_misses, find_windows

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


@dataclass(frozen=True)
class Forecast:
    config: dict[str, Any]
    now: datetime  # local
    hours: list[ScoredHour]
    windows: list[Window]
    near_misses: list[NearMiss]


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def build(raw: dict[str, dict[str, Any]], config: dict[str, Any], now: datetime) -> Forecast:
    """Pure: raw API responses -> scored hours, windows and near misses."""
    now = now.astimezone(ZoneInfo(config["spot"]["timezone"]))
    hours = score_hours(normalize(raw, config, now), config)
    windows = find_windows(hours, config, now.date())
    return Forecast(config, now, hours, windows, find_near_misses(hours, windows, config))


def run(now: datetime | None = None) -> Forecast:
    config = load_config()
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(config["spot"]["timezone"]))
    return build(fetch_all(config["spot"], now.date()), config, now)
