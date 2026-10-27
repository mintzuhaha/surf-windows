from __future__ import annotations

import pytest

from conftest import local, make_hour
from surf.normalize import normalize
from surf.score import (
    explain, face_height_ft, period_factor, score_hour, size_bucket, tide_direction,
    tide_level, wind_aspect, wind_class,
)


@pytest.mark.parametrize("period_s, expected", [(8, 1.0), (10, 1.0), (12, 1.1), (30, 1.4)])
def test_period_factor_grows_past_10s_and_caps(period_s, expected):
    assert period_factor(period_s) == pytest.approx(expected)


def test_face_height_uses_swell():
    # 1.5 m * 3.281 * 1.1 (12 s) * 0.6
    assert face_height_ft(make_hour(), 0.6) == pytest.approx(3.248, abs=0.001)


def test_face_height_falls_back_to_wave_when_swell_is_null():
    hour = make_hour(swell_height_m=None, swell_period_s=None)
    # 1.6 m * 3.281 * 1.05 (11 s) * 0.6
    assert face_height_ft(hour, 0.6) == pytest.approx(3.307, abs=0.001)


def test_face_height_none_without_any_wave_data():
    hour = make_hour(swell_height_m=None, wave_height_m=None)
    assert face_height_ft(hour, 0.6) is None


def test_size_buckets_are_half_open(config):
    buckets = config["size_buckets"]
    assert size_bucket(2.0, buckets) == "waist"
    assert size_bucket(2.999, buckets) == "waist"
    assert size_bucket(3.0, buckets) == "chest"
    assert size_bucket(0.5, buckets) == "flat"
    assert size_bucket(None, buckets) == "unknown"


@pytest.mark.parametrize("wind_from, aspect", [
    (0, "offshore"), (60, "offshore"), (300, "offshore"), (61, "cross-shore"),
    (180, "onshore"), (120, "onshore"), (250, "cross-shore"),
])
def test_wind_aspect_for_south_facing_break(wind_from, aspect):
    assert wind_aspect(wind_from, faces_deg=180) == aspect


@pytest.mark.parametrize("speed, aspect, expected", [
    (4.9, "onshore", "glassy"), (25, "offshore", "glassy"), (5, "onshore", "light"),
    (12, "cross-shore", "light"), (12.1, "onshore", "windy"),
])
def test_wind_class(speed, aspect, expected):
    assert wind_class(speed, aspect) == expected


def test_tide_level_thirds_of_day_range():
    assert tide_level(1.9, 0.0, 6.0) == "low"
    assert tide_level(2.0, 0.0, 6.0) == "mid"
    assert tide_level(4.0, 0.0, 6.0) == "mid"
    assert tide_level(4.1, 0.0, 6.0) == "high"
    assert tide_level(1.0, 1.0, 1.0) == "mid"


def test_tide_direction_from_next_hour():
    assert tide_direction(1.0, 1.2) == "rising"
    assert tide_direction(1.0, 0.8) == "falling"


def test_good_hour_passes_and_is_favored(config):
    sh = score_hour(make_hour(), config)
    assert (sh.size, sh.wind, sh.tide_level, sh.tide_direction) == ("chest", "glassy", "low", "rising")
    assert sh.passes and sh.favored and sh.reason is None


def test_hard_filters_report_in_order(config):
    # 5am Wednesday: before dawn, outside free hours, and after rain.
    sh = score_hour(make_hour(start=local(2026, 10, 28, 5), rain_prior_in=0.5), config)
    assert sh.failures == ("dark", "busy", "rain")
    assert sh.reason == "dark"


def test_daylight_boundaries_are_inclusive(config):
    at_dawn = make_hour(start=local(2026, 10, 28, 7))
    assert score_hour(at_dawn, config).passes
    before_dawn = make_hour(start=local(2026, 10, 28, 7), dawn=local(2026, 10, 28, 7, 1))
    assert score_hour(before_dawn, config).reason == "dark"
    ends_at_sunset = make_hour(start=local(2026, 10, 28, 17), sunset=local(2026, 10, 28, 18))
    assert "dark" not in score_hour(ends_at_sunset, config).failures
    ends_after_sunset = make_hour(start=local(2026, 10, 28, 17), sunset=local(2026, 10, 28, 17, 59))
    assert score_hour(ends_after_sunset, config).reason == "dark"


def test_free_hours_weekday_vs_weekend(config):
    assert score_hour(make_hour(start=local(2026, 10, 28, 9)), config).reason == "busy"  # Wed, slot is [6, 9)
    assert score_hour(make_hour(start=local(2026, 10, 31, 14)), config).passes  # Sat, slot is [6, 15)
    assert score_hour(make_hour(start=local(2026, 10, 31, 15)), config).reason == "busy"


def test_rain_threshold_is_inclusive(config):
    assert score_hour(make_hour(rain_prior_in=0.1), config).reason == "rain"
    assert score_hour(make_hour(rain_prior_in=0.09), config).passes


def test_ok_size_passes_without_favor(config):
    sh = score_hour(make_hour(swell_height_m=1.0), config)  # 2.17 ft -> waist
    assert sh.size == "waist" and sh.passes and not sh.favored


def test_favored_by_tide_when_wind_is_only_ok(config):
    config["preferences"]["tide"]["low"] = "fav"
    sh = score_hour(make_hour(wind_speed_mph=8, wind_direction_deg=180), config)
    assert sh.wind == "light" and sh.favored


def test_skip_factor_and_disabled_direction_fail(config):
    assert score_hour(make_hour(tide_ft=5.0), config).failures == ("tide",)
    config["preferences"]["tide_direction"]["rising"] = False
    assert score_hour(make_hour(), config).failures == ("tide_direction",)


def test_every_failure_is_recorded(config):
    sh = score_hour(make_hour(wind_speed_mph=15, wind_direction_deg=180, tide_ft=5.5), config)
    assert sh.failures == ("wind", "tide")
    assert sh.states["size"] == "fav" and sh.states["wind"] == "skip"


def test_explanation_has_every_factor(config):
    lines = explain(score_hour(make_hour(), config), config)
    assert lines == {
        "size": "Chest-high, 3.2 ft faces (1.5 m at 12 s from W)",
        "wind": "Glassy, 3 mph offshore",
        "tide": "Low, rising (1.0 → 1.5 ft)",
        "rain": "No rain in the prior 72 hours",
        "daylight": "Sunrise 7:25am, sunset 6:12pm",
    }


def test_fixture_hours_start_at_current_hour(raw, config, recorded_at):
    hours = normalize(raw, config, recorded_at)
    assert hours[0].start == recorded_at.replace(minute=0, second=0)
    assert all(h.start >= hours[0].start for h in hours)
    assert len(hours) > 140  # rest of today plus six more days
    scored = [score_hour(h, config) for h in hours]
    assert all(s.reason == "dark" for s in scored if s.hour.start.hour in (0, 3, 22))
