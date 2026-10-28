from __future__ import annotations

import pytest

from conftest import local, make_hour
from surf.normalize import normalize
from surf.score import (
    explain, score_hour, size_bucket, surf_height_ft, surf_range, swell_contribution, tide_direction,
    tide_level, wind_aspect, wind_class,
)


def test_swell_contribution_grows_with_period_and_drops_for_westerly_swell():
    # 0.7 m = 2.297 ft; (12 s / 10 s) ** 0.8 = 1.157
    assert swell_contribution(0.7, 12, 205) == pytest.approx(2.657, abs=0.001)
    assert swell_contribution(0.7, 16, 205) == pytest.approx(2.297 * 1.6 ** 0.8, abs=0.001)
    assert swell_contribution(0.7, 12, 270) == pytest.approx(2.657 * 0.8, abs=0.001)


def test_surf_height_is_energy_sum_of_swells_times_gain():
    assert surf_height_ft(make_hour(), 1.4) == pytest.approx(1.4 * 2.657, abs=0.002)
    two = make_hour(secondary_swell_height_m=0.7, secondary_swell_period_s=12.0, secondary_swell_direction_deg=205.0)
    assert surf_height_ft(two, 1.4) == pytest.approx(1.4 * 2.657 * 2 ** 0.5, abs=0.002)


def test_surf_height_falls_back_to_combined_sea_without_partitions():
    hour = make_hour(swell_height_m=None, swell_period_s=None)
    assert surf_height_ft(hour, 1.4) == pytest.approx(1.4 * 0.8 * 3.281 * 1.1 ** 0.8, abs=0.002)


def test_surf_height_none_without_any_wave_data():
    assert surf_height_ft(make_hour(swell_height_m=None, wave_height_m=None), 1.4) is None


@pytest.mark.parametrize("ft, label", [
    (0.5, "0–1 ft"), (2.7, "2–3 ft+"), (3.5, "3–4 ft"), (3.7, "3–4 ft+"), (4.2, "4–5 ft"),
    (5.0, "4–6 ft"), (6.0, "5–7 ft"), (7.0, "6–8 ft"),
])
def test_surfline_style_ranges(ft, label):
    assert surf_range(ft) == label


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


def test_tide_is_high_when_the_hour_reaches_the_break_limit():
    assert tide_level(4.2, 4.0, 0.0, 6.0, high_tide_ft=4.2) == "high"
    assert tide_level(4.0, 4.3, 0.0, 6.0, high_tide_ft=4.2) == "high"  # rises past it within the hour
    assert tide_level(4.1, 4.19, 0.0, 6.0, high_tide_ft=4.2) == "mid"
    # Sun Nov 1: top third of that day's range (-0.2 to 5.1 ft), but under the limit.
    assert tide_level(3.6, 3.4, -0.2, 5.1, high_tide_ft=4.2) == "mid"


def test_tide_level_low_is_bottom_third_of_day_range():
    assert tide_level(1.9, 1.8, 0.0, 6.0, high_tide_ft=4.2) == "low"
    assert tide_level(2.0, 2.1, 0.0, 6.0, high_tide_ft=4.2) == "mid"
    assert tide_level(1.0, 1.0, 1.0, 1.0, high_tide_ft=4.2) == "mid"


def test_tide_below_ideal_for_the_whole_hour_is_favored(config):
    def tide_state(start, end):
        return score_hour(make_hour(tide_ft=start, tide_next_ft=end), config).states["tide"]
    assert tide_state(3.5, 3.6) == "fav"
    assert tide_state(3.5, 3.8) == "ok"  # rises past 3.7 within the hour
    assert tide_state(4.0, 4.1) == "ok"
    assert tide_state(4.0, 4.3) == "skip"


def test_tide_direction_from_next_hour():
    assert tide_direction(1.0, 1.2) == "rising"
    assert tide_direction(1.0, 0.8) == "falling"


def test_good_hour_passes_and_is_favored(config):
    sh = score_hour(make_hour(), config)
    assert (sh.size, sh.wind, sh.tide_level, sh.tide_direction) == ("chest", "glassy", "low", "rising")
    assert sh.passes and sh.favored and sh.reason is None


def test_hard_filters_report_in_order(config):
    # 5am Wednesday: over an hour before sunrise, and after rain.
    sh = score_hour(make_hour(start=local(2026, 10, 28, 5), rain_prior_in=0.5), config)
    assert sh.failures == ("dark", "rain")
    assert sh.reason == "dark"


def test_daylight_runs_from_an_hour_before_sunrise_to_an_hour_after_sunset(config):
    # make_hour: sunrise 7:25am, sunset 6:12pm -> hours may start from 6:25am and end by 7:12pm
    assert score_hour(make_hour(start=local(2026, 10, 28, 7)), config).passes
    assert score_hour(make_hour(start=local(2026, 10, 28, 6)), config).reason == "dark"
    on_the_limit = make_hour(start=local(2026, 10, 28, 6), sunrise=local(2026, 10, 28, 7))
    assert score_hour(on_the_limit, config).passes
    assert score_hour(make_hour(start=local(2026, 10, 28, 18)), config).passes  # ends 7pm
    assert score_hour(make_hour(start=local(2026, 10, 28, 19)), config).reason == "dark"  # ends 8pm


def test_rain_threshold_is_inclusive(config):
    assert score_hour(make_hour(rain_prior_in=0.1), config).reason == "rain"
    assert score_hour(make_hour(rain_prior_in=0.09), config).passes


def test_ok_size_passes_without_favor(config):
    sh = score_hour(make_hour(swell_height_m=0.5), config)  # 2.7 ft -> waist
    assert sh.size == "waist" and sh.passes and not sh.favored


def test_ideal_tide_favors_an_hour_without_glassy_wind(config):
    sh = score_hour(make_hour(wind_speed_mph=8, wind_direction_deg=180), config)  # tide 1.0 -> 1.5 ft
    assert sh.wind == "light" and sh.states["tide"] == "fav" and sh.favored


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
        "size": "3–4 ft+, chest-high (2.3 ft at 12 s from SSW)",
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


def test_overhead_passes_with_a_big_wave_warning_and_beyond_7_ft_is_a_no_go(config):
    overhead = score_hour(make_hour(swell_height_m=1.1), config)  # 5.8 ft -> 5-7 ft
    assert (overhead.size, overhead.passes, overhead.big_waves, overhead.favored) == ("overhead", True, True, False)
    too_big = score_hour(make_hour(swell_height_m=1.4), config)  # 7.4 ft -> 6-8 ft
    assert too_big.size == "way_over" and too_big.failures == ("size",)
    assert not score_hour(make_hour(), config).big_waves
