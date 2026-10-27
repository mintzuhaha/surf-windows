from __future__ import annotations

from datetime import date

from icalendar import Calendar

from conftest import local, make_hour
from surf.ics import build_feed, summary
from surf.score import score_hours
from surf.windows import find_windows

TODAY = date(2026, 10, 27)
NOW = local(2026, 10, 27, 15, 5)
WAIST = {"swell_height_m": 1.0}


def windows_for(config, day: int, hours=(7, 8), **overrides):
    hs = [make_hour(start=local(2026, 10, day, h), **overrides) for h in hours]
    return find_windows(score_hours(hs, config), config, TODAY)


def test_calendar_headers(config):
    text = build_feed([], config, NOW)
    assert "X-WR-CALNAME:Surf windows" in text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT3H" in text
    assert "X-PUBLISHED-TTL:PT3H" in text
    assert "BEGIN:VEVENT" not in text


def test_one_event_per_window_with_stable_uid_and_local_times(config):
    windows = windows_for(config, 28) + windows_for(config, 29)
    text = build_feed(windows, config, NOW)
    events = Calendar.from_ical(text).walk("VEVENT")
    assert [str(e["uid"]) for e in events] == [
        "pleasure-point-20261028-07@surf-windows",
        "pleasure-point-20261029-07@surf-windows",
    ]
    assert "DTSTART;TZID=America/Los_Angeles:20261028T070000" in text
    assert "DTEND;TZID=America/Los_Angeles:20261028T090000" in text
    assert "DTSTAMP:20261027T220500Z" in text
    assert "BEGIN:VTIMEZONE" in text and "TZID:America/Los_Angeles" in text


def test_summaries(config):
    [favored] = windows_for(config, 28)
    [plain] = windows_for(config, 28, **WAIST)
    [tentative] = windows_for(config, 30, **WAIST)
    [favored_tentative] = windows_for(config, 30)
    assert summary(favored, config) == "★ Surf: Pleasure Point · chest-high · glassy"
    assert summary(plain, config) == "Surf: Pleasure Point · waist-high"
    assert summary(tentative, config) == "Surf (tentative): Pleasure Point · waist-high"
    assert summary(favored_tentative, config) == "★ Surf (tentative): Pleasure Point · chest-high · glassy"


def test_favored_by_tide_names_the_tide(config):
    [window] = windows_for(config, 28, wind_speed_mph=8, wind_direction_deg=180)
    assert summary(window, config) == "★ Surf: Pleasure Point · chest-high · low tide"


def test_description_has_one_line_per_factor_and_updated(config):
    [window] = windows_for(config, 28)
    event = Calendar.from_ical(build_feed([window], config, NOW)).walk("VEVENT")[0]
    assert str(event["description"]).split("\n") == [
        "Size: Chest-high, 3 ft faces (1.5 m at 12 s from W) ★",
        "Wind: Glassy, 3 mph offshore ★",
        "Tide: Low, rising (1.0 → 1.5 ft) ★",
        "Rain: No rain in the prior 72 hours",
        "Daylight: Sunrise 7:25am, sunset 6:12pm",
        "Updated Tue Oct 27, 3:05pm",
    ]
    assert str(event["status"]) == "CONFIRMED"
