from __future__ import annotations

from datetime import date

from conftest import local, make_hour
from surf.normalize import normalize
from surf.score import score_hours
from surf.windows import find_near_misses, find_windows

TODAY = date(2026, 10, 27)  # Tuesday


def saturday(hour: int, **overrides):
    return make_hour(start=local(2026, 10, 31, hour), **overrides)


def windy(**overrides):
    return {"wind_speed_mph": 14, "wind_direction_deg": 180, **overrides}


def test_merges_consecutive_passing_hours(config):
    scored = score_hours([saturday(h) for h in (7, 8, 9)], config)
    [window] = find_windows(scored, config, TODAY)
    assert (window.start, window.end) == (local(2026, 10, 31, 7), local(2026, 10, 31, 10))
    assert window.id == "pleasure-point-20261031-07"


def test_failing_hour_splits_and_short_runs_drop(config):
    hours = [saturday(7), saturday(8), saturday(9, **windy()), saturday(10), saturday(11), saturday(12, **windy()), saturday(13)]
    windows = find_windows(score_hours(hours, config), config, TODAY)
    assert [w.id for w in windows] == ["pleasure-point-20261031-07", "pleasure-point-20261031-10"]


def test_does_not_merge_across_midnight(config):
    config["preferences"]["free_hours"]["weekends"] = [[0, 24]]
    late = saturday(22, dawn=local(2026, 10, 31, 0), sunset=local(2026, 11, 1, 1))
    later = saturday(23, dawn=local(2026, 10, 31, 0), sunset=local(2026, 11, 1, 1))
    sunday = make_hour(start=local(2026, 11, 1, 0), dawn=local(2026, 11, 1, 0), sunset=local(2026, 11, 1, 2))
    sunday_1am = make_hour(start=local(2026, 11, 1, 1), dawn=local(2026, 11, 1, 0), sunset=local(2026, 11, 1, 2))
    windows = find_windows(score_hours([late, later, sunday, sunday_1am], config), config, TODAY)
    assert [len(w.hours) for w in windows] == [2, 2]


def test_favored_when_at_least_half_the_hours_are(config):
    waist = {"swell_height_m": 1.0}
    two = find_windows(score_hours([saturday(7), saturday(8, **waist)], config), config, TODAY)
    assert two[0].favored
    three = find_windows(score_hours([saturday(7), saturday(8, **waist), saturday(9, **waist)], config), config, TODAY)
    assert not three[0].favored
    assert three[0].size == "waist"


def test_tentative_by_calendar_days_after_today(config):
    thursday = [make_hour(start=local(2026, 10, 29, h)) for h in (7, 8)]
    friday = [make_hour(start=local(2026, 10, 30, h)) for h in (7, 8)]
    thu, fri = find_windows(score_hours(thursday + friday, config), config, TODAY)
    assert (thu.days_out, thu.tentative) == (2, False)
    assert (fri.days_out, fri.tentative) == (3, True)


def test_no_near_misses_with_two_windows(config):
    hours = [saturday(7), saturday(8), saturday(9, **windy()), saturday(11), saturday(12)]
    scored = score_hours(hours, config)
    windows = find_windows(scored, config, TODAY)
    assert len(windows) == 2
    assert find_near_misses(scored, windows, config) == []


def test_near_misses_fail_exactly_one_factor_in_daylight_and_free_hours(config):
    hours = [
        make_hour(start=local(2026, 10, 29, 8), **windy()),                # one miss: wind
        make_hour(start=local(2026, 10, 29, 10), **windy()),               # busy (weekday 10am)
        make_hour(start=local(2026, 10, 29, 6), **windy()),                # dark (before 7am dawn)
        make_hour(start=local(2026, 10, 29, 17), **windy(tide_ft=5.5)),    # two misses
        make_hour(start=local(2026, 10, 28, 17), swell_height_m=0.5),      # one miss: size
        make_hour(start=local(2026, 10, 28, 7), rain_prior_in=0.4),        # one miss: rain
    ]
    scored = score_hours(hours, config)
    misses = find_near_misses(scored, find_windows(scored, config, TODAY), config)
    assert [m.text for m in misses] == [
        'Wed 7am: chest-high, but 0.40" of rain in the prior 72 hours',
        "Wed 5pm: glassy, but only knee-high",
        "Thu 8am: chest-high, but 14 mph onshore",
    ]


def test_near_misses_keep_best_hour_per_day_and_reason_and_cap_at_five(config):
    config["preferences"]["free_hours"]["weekdays"] = [[6, 19]]
    hours = [make_hour(start=local(2026, 10, d, h), **windy()) for d in (27, 28, 29, 30) for h in (8, 9, 10)]
    hours += [make_hour(start=local(2026, 10, d, 8), tide_ft=5.5) for d in (28, 29)]
    scored = score_hours(hours, config)
    misses = find_near_misses(scored, [], config)
    assert len(misses) == 5
    assert len({(m.hour.hour.start.date(), m.hour.reason) for m in misses}) == 5
    assert [m.hour.hour.start for m in misses] == sorted(m.hour.hour.start for m in misses)


def test_fixture_windows_are_future_and_well_formed(raw, config, recorded_at):
    scored = score_hours(normalize(raw, config, recorded_at), config)
    windows = find_windows(scored, config, recorded_at.date())
    current_hour = recorded_at.replace(minute=0, second=0)
    assert len({w.id for w in windows}) == len(windows)
    for w in windows:
        assert w.start >= current_hour
        assert len(w.hours) >= config["preferences"]["min_window_hours"]
        assert all(h.passes for h in w.hours)
