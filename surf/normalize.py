"""Merge the raw sources into one record per local forecast hour."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun


@dataclass(frozen=True)
class Hour:
    """One local forecast hour, covering [start, start + 1h)."""

    start: datetime  # tz-aware, local
    swell_height_m: float | None
    swell_period_s: float | None
    swell_direction_deg: float | None
    wave_height_m: float | None
    wave_period_s: float | None
    wave_direction_deg: float | None
    wind_speed_mph: float
    wind_direction_deg: float
    wind_gust_mph: float | None
    rain_prior_in: float  # total over the prior rain.skip_after_hours hours
    tide_ft: float
    tide_next_ft: float  # prediction for the next hour, for rising/falling
    tide_day_low_ft: float
    tide_day_high_ft: float
    dawn: datetime  # civil dawn
    sunrise: datetime
    sunset: datetime

    @property
    def end(self) -> datetime:
        return self.start + timedelta(hours=1)


def normalize(raw: dict[str, dict[str, Any]], config: dict[str, Any], now: datetime) -> list[Hour]:
    """Hourly records from the current local hour to the end of the marine forecast.

    All sources are keyed by local wall-clock time (none repeats the DST
    fall-back hour), so they join on naive local datetimes. Hours missing
    any source are dropped.
    """
    spot = config["spot"]
    tz = ZoneInfo(spot["timezone"])
    rain_hours: int = config["preferences"]["rain"]["skip_after_hours"]
    current_hour = now.astimezone(tz).replace(minute=0, second=0, microsecond=0, tzinfo=None)

    marine = raw["marine"]["hourly"]
    forecast = raw["forecast"]["hourly"]
    forecast_index = {datetime.fromisoformat(t): i for i, t in enumerate(forecast["time"])}
    precipitation = [p or 0.0 for p in forecast["precipitation"]]
    tides = {datetime.fromisoformat(p["t"]): float(p["v"]) for p in raw["tides"]["predictions"]}
    tide_ranges = _tide_day_ranges(tides)
    observer = Observer(latitude=spot["lat"], longitude=spot["lon"])
    daylight: dict[date, dict[str, datetime]] = {}

    hours: list[Hour] = []
    for i, t in enumerate(marine["time"]):
        local = datetime.fromisoformat(t)
        if local < current_hour:
            continue
        fi = forecast_index.get(local)
        next_local = local + timedelta(hours=1)
        if fi is None or fi + 1 < rain_hours or local not in tides or next_local not in tides:
            continue
        wind_speed = forecast["wind_speed_10m"][fi]
        wind_direction = forecast["wind_direction_10m"][fi]
        if wind_speed is None or wind_direction is None:
            continue
        if local.date() not in daylight:
            daylight[local.date()] = sun(observer, date=local.date(), tzinfo=tz)
        day = daylight[local.date()]
        low, high = tide_ranges[local.date()]
        hours.append(
            Hour(
                start=local.replace(tzinfo=tz),
                swell_height_m=marine["swell_wave_height"][i],
                swell_period_s=marine["swell_wave_period"][i],
                swell_direction_deg=marine["swell_wave_direction"][i],
                wave_height_m=marine["wave_height"][i],
                wave_period_s=marine["wave_period"][i],
                wave_direction_deg=marine["wave_direction"][i],
                wind_speed_mph=wind_speed,
                wind_direction_deg=wind_direction,
                wind_gust_mph=forecast["wind_gusts_10m"][fi],
                # Open-Meteo precipitation at T covers [T-1h, T), so the hours
                # before `local` are the values labeled local-(N-1)h .. local.
                rain_prior_in=round(sum(precipitation[fi - rain_hours + 1 : fi + 1]), 3),
                tide_ft=tides[local],
                tide_next_ft=tides[next_local],
                tide_day_low_ft=low,
                tide_day_high_ft=high,
                dawn=day["dawn"],
                sunrise=day["sunrise"],
                sunset=day["sunset"],
            )
        )
    return hours


def _tide_day_ranges(tides: dict[datetime, float]) -> dict[date, tuple[float, float]]:
    by_day: dict[date, list[float]] = {}
    for t, v in tides.items():
        by_day.setdefault(t.date(), []).append(v)
    return {d: (min(vs), max(vs)) for d, vs in by_day.items()}
