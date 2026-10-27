"""API clients. The only module in surf/ that does network I/O.

Each function returns the raw JSON response as a plain dict; normalize.py
turns them into hourly records.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIDES_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
TIMEOUT_S = 10.0
FORECAST_DAYS = 7


def fetch_marine(spot: dict[str, Any]) -> dict[str, Any]:
    params = {
        "latitude": spot["lat"],
        "longitude": spot["lon"],
        "hourly": "wave_height,wave_period,wave_direction,"
        "swell_wave_height,swell_wave_period,swell_wave_direction",
        "timezone": spot["timezone"],
        "forecast_days": FORECAST_DAYS,
    }
    return _get_json(MARINE_URL, params)


def fetch_forecast(spot: dict[str, Any]) -> dict[str, Any]:
    params = {
        "latitude": spot["lat"],
        "longitude": spot["lon"],
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": spot["timezone"],
        "forecast_days": FORECAST_DAYS,
        "past_days": 3,  # needed for the 72-hour rain rule
    }
    return _get_json(FORECAST_URL, params)


def fetch_tides(spot: dict[str, Any], today: date) -> dict[str, Any]:
    # Through today+7 so the last forecast hour still has a next hour for rising/falling.
    params = {
        "product": "predictions",
        "station": spot["noaa_station"],
        "datum": "MLLW",
        "interval": "h",
        "units": "english",
        "time_zone": "lst_ldt",
        "format": "json",
        "begin_date": today.strftime("%Y%m%d"),
        "end_date": (today + timedelta(days=FORECAST_DAYS)).strftime("%Y%m%d"),
        "application": "surf-windows",
    }
    data = _get_json(TIDES_URL, params)
    if "predictions" not in data:
        # NOAA reports bad requests as HTTP 200 with an "error" object.
        raise RuntimeError(f"NOAA tides error: {data.get('error', data)}")
    return data


def fetch_all(spot: dict[str, Any], today: date) -> dict[str, dict[str, Any]]:
    """Fetch all three sources in parallel. Keys: marine, forecast, tides."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        marine = pool.submit(fetch_marine, spot)
        forecast = pool.submit(fetch_forecast, spot)
        tides = pool.submit(fetch_tides, spot, today)
        return {"marine": marine.result(), "forecast": forecast.result(), "tides": tides.result()}


def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = httpx.get(url, params=params, timeout=TIMEOUT_S)
    response.raise_for_status()
    return response.json()
