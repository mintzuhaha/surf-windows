"""Windows -> iCalendar feed text."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from icalendar import Calendar, Event

from surf.score import format_time, surf_range
from surf.windows import Window, describe_window

REFRESH = timedelta(hours=3)


def build_feed(
    windows: list[Window], config: dict[str, Any], now: datetime, skip: frozenset[str] = frozenset()
) -> str:
    """skip holds window ids the subscriber unchecked on the page."""
    cal = Calendar()
    cal.add("prodid", "-//Surf Windows//surf-windows//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "Surf windows")
    cal.add("x-wr-timezone", config["spot"]["timezone"])
    cal.add("refresh-interval", REFRESH, parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT3H")

    stamp = now.astimezone(timezone.utc)
    for w in windows:
        if w.id in skip:
            continue
        event = Event()
        event.add("uid", f"{w.id}@surf-windows")
        event.add("dtstamp", stamp)
        event.add("dtstart", w.start)
        event.add("dtend", w.end)
        event.add("summary", summary(w, config))
        event.add("description", description(w, config, now))
        event.add("status", "TENTATIVE" if w.tentative else "CONFIRMED")
        event.add("transp", "TRANSPARENT")  # a suggestion, not a commitment: don't block free/busy
        cal.add_component(event)

    cal.add_missing_timezones(first_date=now.date(), last_date=now.date() + timedelta(days=366))
    return cal.to_ical().decode()


def summary(w: Window, config: dict[str, Any]) -> str:
    """★ Surf: Pleasure Point · 3–4 ft+ · glassy, or Surf (tentative): Pleasure Point · 2–3 ft."""
    label = "Surf (tentative)" if w.tentative else "Surf"
    text = f"{label}: {config['spot']['name']} · {surf_range(w.surf_ft)}{' ⚠ big waves' if w.big_waves else ''}"
    if not w.favored:
        return text
    wind_is_fav = config["preferences"]["wind"].get(w.wind) == "fav"
    return f"★ {text} · {w.wind if wind_is_fav else 'ideal tide'}"


def description(w: Window, config: dict[str, Any], now: datetime) -> str:
    lines = [
        f"{factor.capitalize()}: {text}{' ★' if state == 'fav' else ''}"
        + (" ⚠ big waves" if factor == "size" and w.big_waves else "")
        for factor, text, state in describe_window(w, config)
    ]
    lines.append(f"Updated {now:%a %b} {now.day}, {format_time(now)}")
    return "\n".join(lines)
