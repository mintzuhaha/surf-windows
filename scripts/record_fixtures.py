"""Fetch real API responses once into tests/fixtures/ so tests run offline.

Usage: python scripts/record_fixtures.py

Writes marine.json, forecast.json and tides.json, plus meta.json with the
local time of the recording (tests use it as "now").
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from surf.fetch import fetch_all  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
MARINE_FIELDS = ("wave_height", "wave_period", "swell_wave_height", "swell_wave_period")


def main() -> None:
    spot = yaml.safe_load((ROOT / "config.yaml").read_text())["spot"]
    now = datetime.now(ZoneInfo(spot["timezone"]))
    raw = fetch_all(spot, now.date())

    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, data in raw.items():
        (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n")
    meta = {"recorded_at": now.isoformat(timespec="seconds")}
    (FIXTURES / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")

    # If the spot's grid cell is land, Open-Meteo marine returns nulls; flag it loudly.
    hourly = raw["marine"]["hourly"]
    for field in MARINE_FIELDS:
        nulls = sum(v is None for v in hourly[field])
        print(f"marine {field}: {nulls}/{len(hourly[field])} null")
    print(f"tides: {len(raw['tides']['predictions'])} hourly predictions")
    print(f"recorded at {meta['recorded_at']} into {FIXTURES.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
