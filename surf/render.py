"""Forecast -> HTML page."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from surf.score import ScoredHour, format_time, size_label
from surf.windows import Window, describe_window

if TYPE_CHECKING:
    from surf.pipeline import Forecast

REPO_URL = "https://github.com/mintzuhaha/surf-windows"
GRID_FIRST_HOUR, GRID_LAST_HOUR = 5, 19  # widened if daylight runs past these
DAYS_SHOWN = 7
HARD_FILTER_CELLS = {"dark": "dark", "busy": "busy", "rain": "rain"}


def render_page(forecast: Forecast, feed_url: str) -> str:
    """feed_url is the absolute https URL of /feed.ics."""
    f = forecast
    spot = f.config["spot"]
    favored = sum(w.favored for w in f.windows)
    count = _plural(len(f.windows), "window") + (f" · {favored} favored" if f.windows else "")
    body = [
        _header(spot["name"], f.now),
        '<main>',
        '<section class="card">',
        f'<div class="card-head"><h1>Next 7 days at {escape(spot["name"])}</h1>'
        f'<span class="mono muted">{count}</span></div>',
        _grid(f),
        _legend(),
        '</section>',
        _window_list(f.windows, f.config),
        _near_misses(f),
        _calendar_card(feed_url, len(f.windows)),
        _how_it_works(f.config),
        '</main>',
        _footer(),
    ]
    return _document(spot["name"], "\n".join(body))


# --- Sections ---------------------------------------------------------------


def _header(spot_name: str, now: datetime) -> str:
    return (
        '<header class="top"><div class="brand">'
        '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M2 15c2.5 0 2.5-2 5-2s2.5 2 5 2 '
        '2.5-2 5-2 2.5 2 5 2M2 19.5c2.5 0 2.5-2 5-2s2.5 2 5 2 2.5-2 5-2 2.5 2 5 2M9 10a3 3 0 1 0 0-6" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>'
        '<span>Surf Windows</span></div>'
        f'<div class="where"><span class="spot">{escape(spot_name)}, Santa Cruz</span>'
        f'<span class="pill mono" data-updated="{now.isoformat(timespec="seconds")}">'
        f'Updated {format_time(now)}</span></div></header>'
    )


def _grid(f: Forecast) -> str:
    today = f.now.date()
    days = [today + timedelta(days=i) for i in range(DAYS_SHOWN)]
    by_slot = {(sh.hour.start.date(), sh.hour.start.hour): sh for sh in f.hours}
    window_at: dict[tuple[date, int], tuple[Window, bool]] = {}
    for w in f.windows:
        for i, sh in enumerate(w.hours):
            window_at[(sh.hour.start.date(), sh.hour.start.hour)] = (w, i == 0)
    lit = [sh.hour.start.hour for sh in f.hours if sh.reason != "dark"]
    rows = range(min([GRID_FIRST_HOUR, *lit]), max([GRID_LAST_HOUR, *lit]) + 1)

    cells = ['<div class="gh" style="grid-column:1;grid-row:1"></div>']
    for col, d in enumerate(days, start=2):
        first = next((sh.hour for sh in f.hours if sh.hour.start.date() == d), None)
        sun = f"{_short_time(first.sunrise)}–{_short_time(first.sunset)}" if first else ""
        cells.append(f'<div class="gh" style="grid-column:{col};grid-row:1">'
                     f'<b>{d:%a} {d:%b} {d.day}</b><span class="mono">{sun}</span></div>')
    for row, hour in enumerate(rows, start=2):
        cells.append(f'<div class="gt mono" style="grid-row:{row}">{_short_hour(hour)}</div>')
        for col, d in enumerate(days, start=2):
            slot = (d, hour)
            place = f"grid-column:{col};grid-row:{row}"
            if slot in window_at:
                w, is_first = window_at[slot]
                if is_first:
                    cls = ("fav" if w.favored else "ok") + (" tent" if w.tentative else "")
                    star = "★ " if w.favored else ""
                    cells.append(f'<a class="cell win {cls}" href="#{w.id}" style="{place} / span {len(w.hours)}" '
                                 f'title="{escape(_window_title(w))}">{star}{_time_range(w.start, w.end)}</a>')
                continue
            sh = by_slot.get(slot)
            if sh is None:
                cells.append(f'<div class="cell past" style="{place}"></div>')
                continue
            state = HARD_FILTER_CELLS.get(sh.reason or "", "nofit")
            text = "after rain" if state == "rain" else ""
            cells.append(f'<div class="cell {state}" style="{place}" title="{escape(_hour_title(sh))}">{text}</div>')
    return f'<div class="grid-scroll"><div class="grid">{"".join(cells)}</div></div>'


def _legend() -> str:
    items = [("fav", "Favored window"), ("ok", "Will-surf window"), ("tent", "Tentative (3+ days out)"),
             ("nofit", "Conditions don't fit"), ("busy", "Outside your free hours"), ("dark", "Dark"),
             ("rain", "72 hours after rain")]
    spans = "".join(f'<span><i class="sw {cls}"></i>{label}</span>' for cls, label in items)
    return f'<div class="legend">{spans}</div>'


def _window_list(windows: list[Window], config: dict[str, Any]) -> str:
    if not windows:
        return ""
    groups: dict[date, list[Window]] = {}
    for w in windows:
        groups.setdefault(w.start.date(), []).append(w)
    out = [_picker(len(windows))]
    for d, ws in groups.items():
        out.append(f'<section class="day-group"><h2 class="day-title">{_day_title(d, ws[0].days_out)}</h2>')
        out.extend(_window_card(w, config) for w in ws)
        out.append('</section>')
    return "\n".join(out)


def _window_card(w: Window, config: dict[str, Any]) -> str:
    badge = '<span class="badge fav">★ Favored</span>' if w.favored else '<span class="badge ok">Will surf</span>'
    if w.tentative:
        badge += '<span class="badge tent">Tentative</span>'
    chips = {"fav": '<span class="chip fav">★ Favored</span>', "ok": '<span class="chip ok">Will surf</span>'}
    rows = []
    for factor, text, state in describe_window(w, config):
        chip = chips[state] if factor in ("size", "wind", "tide") else '<span class="chip check">✓</span>'
        rows.append(f'<div class="row"><dt>{factor.capitalize()}</dt><dd>{escape(text)}</dd>{chip}</div>')
    rows.append(f'<div class="row"><dt>Confidence</dt><dd>{_confidence(w)}</dd></div>')
    cls = ("fav" if w.favored else "ok") + (" tent" if w.tentative else "")
    return (f'<article class="card window {cls}" id="{w.id}"><div class="win-head">{badge}'
            f'<h3>{_time_range(w.start, w.end)}</h3>'
            f'<label class="pick"><input type="checkbox" data-window="{w.id}" checked> Add</label></div>'
            f'<dl class="factors">{"".join(rows)}</dl></article>')


def _picker(count: int) -> str:
    """Select all / Deselect all over the window checkboxes; JS keeps the count and links in sync."""
    return (f'<div class="picker"><span class="pick-count">{count} of {count} windows selected</span>'
            '<button type="button" class="link" data-select="all">Select all</button>'
            '<button type="button" class="link" data-select="none">Deselect all</button></div>')


def _near_misses(f: Forecast) -> str:
    if f.windows and not f.near_misses:
        return ""
    title = "Flat week. Here's what's closest:" if not f.windows else "Also close:"
    if not f.near_misses:
        items = "<li>Nothing came close this time.</li>"
    else:
        items = "".join(f"<li>{escape(m.text)}</li>" for m in f.near_misses)
    return f'<section class="card empty"><h2>{title}</h2><ul class="misses mono">{items}</ul></section>'


def _calendar_card(feed_url: str, window_count: int) -> str:
    """The links start as the full feed; the page's JS adds ?skip= for unchecked windows."""
    webcal = "webcal://" + feed_url.split("://", 1)[-1]
    google = "https://calendar.google.com/calendar/render?cid=" + quote(webcal, safe="")
    picks = ""
    if window_count:
        picks = (f'<p class="pick-count">{window_count} of {window_count} windows selected</p>'
                 '<p>Uncheck any window above to leave it off. New windows are still added as they show up.</p>')
    return (
        '<section class="card cal"><h2>Put these windows on your calendar</h2>'
        '<p>Subscribe once and windows appear, change and drop off as the forecast moves. '
        'Calendar apps re-check the feed every few hours.</p>'
        f'{picks}<div class="buttons">'
        f'<a class="btn primary" id="google-add" href="{escape(google)}" target="_blank" rel="noopener">'
        '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="3.5" y="5" width="17" height="15" '
        'rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M3.5 10h17M8 3v4M16 3v4" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>Add to Google Calendar</a>'
        f'<button class="btn" type="button" data-copy="{escape(feed_url)}">Copy feed link</button></div>'
        f'<code class="feed mono" id="feed-url" data-base="{escape(feed_url)}">{escape(feed_url)}</code>'
        '<p class="hint">On a phone? If the button doesn\'t add it, open this page on a computer once. '
        'The calendar then syncs to your phone. Already subscribed? Changing your picks makes a new link, '
        'so remove the old Surf windows calendar in Google first.</p></section>'
    )


def _how_it_works(config: dict[str, Any]) -> str:
    prefs = config["preferences"]
    return (
        '<section class="card how"><h2>How it works</h2><ul>'
        '<li>Every hour of the next 7 days is checked for daylight, your free hours and '
        f'the {prefs["rain"]["skip_after_hours"]}-hour rain rule (stormwater runoff carries bacteria into the surf).</li>'
        '<li>Wave size, wind and tide are each scored <em>skip</em>, <em>will surf</em> or <em>favored</em> '
        'against your preferences.</li>'
        f'<li>Good hours merge into windows of {prefs["min_window_hours"]}+ hours, published here and as a calendar '
        'feed. The forecast is re-fetched every 30 minutes.</li>'
        f'</ul><p><a href="{REPO_URL}">Source on GitHub</a></p></section>'
    )


def _footer() -> str:
    return (
        '<footer><a href="https://open-meteo.com/">Weather data by Open-Meteo.com</a> · '
        '<a href="https://tidesandcurrents.noaa.gov/">Tide predictions: NOAA</a></footer>'
    )


# --- Formatting -------------------------------------------------------------


def _time_range(start: datetime, end: datetime) -> str:
    """7–9am, 11am–1pm."""
    a, b = format_time(start, minutes=False), format_time(end, minutes=False)
    return f"{a[:-2]}–{b}" if a[-2:] == b[-2:] else f"{a}–{b}"


def _short_hour(hour: int) -> str:
    return f"{hour % 12 or 12}{'a' if hour < 12 else 'p'}"


def _short_time(dt: datetime) -> str:
    return format_time(dt)[:-1]  # 7:22a


def _day_title(d: date, days_out: int) -> str:
    prefix = {0: "Today", 1: "Tomorrow"}.get(days_out, f"{d:%A}")
    return f"{prefix}, {d:%b} {d.day}"


def _confidence(w: Window) -> str:
    when = "today" if w.days_out == 0 else f"{_plural(w.days_out, 'day')} out"
    if w.tentative:
        return f"Tentative, {when}. Forecasts this far out often change."
    return f"Solid, {when}."


def _window_title(w: Window) -> str:
    return f"{size_label(w.size)}, {w.wind}, {w.tide_level} tide"


def _hour_title(sh: ScoredHour) -> str:
    when = format_time(sh.hour.start, minutes=False)
    reason = {"dark": "dark", "busy": "outside your free hours"}.get(sh.reason or "", "")
    if reason:
        return f"{when}: {reason}"
    detail = f"{size_label(sh.size)}, {sh.wind} {sh.hour.wind_speed_mph:.0f} mph, {sh.tide_level} tide"
    return f"{when}: {detail}" + (f" (fails {sh.reason.replace('_', ' ')})" if sh.reason else "")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


# --- Document -----------------------------------------------------------------


def _document(spot_name: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Surf Windows · {escape(spot_name)}</title>
<meta name="description" content="Good surf windows for {escape(spot_name)}, Santa Cruz, as a calendar feed.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
{body}
<script>{JS}</script>
</body>
</html>
"""


CSS = """
:root {
  --fav: #12466F; --ok: #9EC5E8; --tent: #D7E7F5; --text: #10283A; --bg: #F4F5F2;
  --card: #FFFFFF; --line: #E2E5DF; --muted: #5B6B77; --busy: #E8EAE5; --nofit: #FFFFFF;
  --dark-a: #DDE0D9; --dark-b: #EBEDE8; --rain-a: #D3DEE8; --rain-b: #EEF2F6;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); font: 15px/1.5 "IBM Plex Sans", system-ui, sans-serif; }
.mono, code { font-family: "IBM Plex Mono", ui-monospace, monospace; }
.muted { color: var(--muted); font-size: 12px; }
a { color: var(--fav); }
.top { display: flex; flex-wrap: wrap; gap: 8px 16px; justify-content: space-between; align-items: center;
  padding: 14px max(16px, calc((100% - 960px) / 2)); background: var(--card); border-bottom: 1px solid var(--line); }
.brand { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 16px; color: var(--fav); }
.brand span { color: var(--text); }
.where { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; font-size: 13px; }
.spot { font-weight: 600; }
.pill { border: 1px solid var(--line); border-radius: 999px; padding: 2px 10px; font-size: 12px; color: var(--muted); }
main { max-width: 960px; margin: 0 auto; padding: 16px; display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 20px; min-width: 0; }
.card h1, .card h2 { margin: 0 0 12px; font-size: 18px; font-weight: 600; }
.card-head { display: flex; flex-wrap: wrap; gap: 4px 16px; justify-content: space-between; align-items: baseline; }
.card-head h1 { margin-bottom: 14px; }

.grid-scroll { overflow-x: auto; margin: 0 -4px; padding: 0 4px 4px; }
.grid { display: grid; grid-template-columns: 32px repeat(7, minmax(78px, 1fr)); grid-template-rows: 36px; grid-auto-rows: 22px;
  gap: 3px; min-width: 600px; }
.gh { padding-bottom: 4px; font-size: 12px; line-height: 1.3; display: flex; flex-direction: column; justify-content: end; }
.gh b { font-weight: 600; }
.gh span { font-size: 10px; color: var(--muted); }
.gt { grid-column: 1; font-size: 10px; color: var(--muted); align-self: center; text-align: right; padding-right: 4px; }
.cell { border-radius: 3px; font: 500 10px/1 "IBM Plex Mono", monospace; padding: 5px 6px; overflow: hidden; white-space: nowrap; }
.cell.nofit { background: var(--nofit); border: 1px solid var(--line); }
.cell.busy { background: var(--busy); }
.cell.past { background: transparent; border: 1px dashed var(--line); opacity: .6; }
.cell.dark { background: repeating-linear-gradient(135deg, var(--dark-a) 0 3px, var(--dark-b) 3px 7px); }
.cell.rain { background: repeating-linear-gradient(135deg, var(--rain-a) 0 3px, var(--rain-b) 3px 7px); color: var(--muted); }
.cell.win { text-decoration: none; display: block; border: 1px solid transparent; }
.cell.win.fav { background: var(--fav); color: #fff; }
.cell.win.ok { background: var(--ok); color: var(--text); }
.cell.win.tent { border: 1.5px dashed var(--fav); }
.cell.win.ok.tent { background: var(--tent); }
.cell.win:hover, .cell.win:focus-visible { outline: 2px solid #E0703A; outline-offset: 1px; }

.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-top: 14px; font-size: 12px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.sw { width: 12px; height: 12px; border-radius: 2px; display: inline-block; }
.sw.fav { background: var(--fav); } .sw.ok { background: var(--ok); }
.sw.tent { background: var(--tent); border: 1px dashed var(--fav); }
.sw.nofit { background: #fff; border: 1px solid #C9CEC6; } .sw.busy { background: var(--busy); }
.sw.dark { background: repeating-linear-gradient(135deg, #C9CEC4 0 2px, var(--dark-b) 2px 4px); }
.sw.rain { background: repeating-linear-gradient(135deg, #B9CADB 0 2px, var(--rain-b) 2px 4px); }

.day-group { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }
.day-title { margin: 6px 0 0; font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; }
.window { border-left: 4px solid var(--ok); scroll-margin-top: 12px; }
.window.fav { border-left-color: var(--fav); }
.window.tent { border-style: dashed; border-left-style: solid; }
.window:target { box-shadow: 0 0 0 2px #E0703A; }
.win-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 10px; }
.win-head h3 { margin: 0; font-size: 18px; font-weight: 600; }
.badge, .chip { display: inline-block; border-radius: 999px; font-size: 11px; font-weight: 600; padding: 2px 9px; white-space: nowrap; }
.badge.fav, .chip.fav { background: var(--fav); color: #fff; }
.badge.ok, .chip.ok { background: var(--tent); color: var(--fav); }
.badge.tent { border: 1px dashed var(--fav); color: var(--fav); }
.chip.check { color: var(--fav); background: none; font-size: 13px; }
.factors { margin: 0; }
.row { display: grid; grid-template-columns: 96px 1fr auto; gap: 4px 12px; align-items: center; padding: 9px 0; border-top: 1px solid var(--line); font-size: 14px; }
.row dt { color: var(--muted); font-size: 13px; }
.row dd { margin: 0; min-width: 0; }

.empty h2 { margin-bottom: 8px; }
.misses { margin: 0; padding-left: 18px; font-size: 13px; display: grid; gap: 4px; }
.cal p { margin: 0 0 14px; color: var(--muted); font-size: 14px; }
.cal p.hint { margin: 12px 0 0; font-size: 12px; }
.buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }
.btn { display: inline-flex; align-items: center; gap: 8px; font: 600 14px "IBM Plex Sans", sans-serif; padding: 10px 16px;
  border-radius: 6px; border: 1px solid #C9D3DB; background: #fff; color: var(--text); cursor: pointer; text-decoration: none; }
.btn.primary { background: var(--fav); border-color: var(--fav); color: #fff; }
.btn:hover { filter: brightness(1.08); }
.feed { display: block; background: var(--bg); border-radius: 6px; padding: 10px 12px; font-size: 12px; overflow-wrap: anywhere; }
.how ul { margin: 0 0 12px; padding-left: 18px; display: grid; gap: 6px; font-size: 14px; }
.how p { margin: 0; font-size: 14px; }
footer { max-width: 960px; margin: 0 auto; padding: 4px 16px 32px; font-size: 12px; color: var(--muted); }
footer a { color: var(--muted); }

.picker { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; font-size: 13px; }
.pick-count { color: var(--muted); font-size: 13px; }
.cal .pick-count { margin: 0 0 4px; font-weight: 600; color: var(--text); }
button.link { background: none; border: 0; padding: 0; font: 600 13px "IBM Plex Sans", sans-serif; color: var(--fav);
  text-decoration: underline; cursor: pointer; }
.pick { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600;
  color: var(--fav); cursor: pointer; }
.pick input { width: 18px; height: 18px; margin: 0; accent-color: var(--fav); cursor: pointer; }
.window.off, .cell.win.off { opacity: .45; }
.btn[aria-disabled="true"] { opacity: .5; pointer-events: none; }

@media (max-width: 560px) {
  .card { padding: 16px; }
  .row { grid-template-columns: 76px 1fr; }
  .row .chip { grid-column: 2; justify-self: start; }
}
"""

JS = """
(function () {
  var el = document.querySelector('[data-updated]');
  if (el) {
    var m = Math.max(0, Math.round((Date.now() - Date.parse(el.dataset.updated)) / 60000));
    el.textContent = 'Updated ' + (m < 1 ? 'just now' : m === 1 ? '1 minute ago'
      : m < 120 ? m + ' minutes ago' : Math.round(m / 60) + ' hours ago');
  }
  var boxes = Array.prototype.slice.call(document.querySelectorAll('input[data-window]'));
  var feed = document.getElementById('feed-url');
  function sync() {
    var off = boxes.filter(function (b) { return !b.checked; })
      .map(function (b) { return b.dataset.window; }).sort();
    var url = feed.dataset.base + (off.length ? '?skip=' + off.join(',') : '');
    feed.textContent = url;
    document.querySelectorAll('[data-copy]').forEach(function (b) { b.dataset.copy = url; });
    var google = document.getElementById('google-add');
    google.href = 'https://calendar.google.com/calendar/render?cid=' + encodeURIComponent('webcal://' + url.split('://')[1]);
    google.setAttribute('aria-disabled', off.length === boxes.length ? 'true' : 'false');
    document.querySelectorAll('.pick-count').forEach(function (el) {
      el.textContent = (boxes.length - off.length) + ' of ' + boxes.length + ' windows selected';
    });
    boxes.forEach(function (b) {
      document.getElementById(b.dataset.window).classList.toggle('off', !b.checked);
      var cell = document.querySelector('.cell.win[href="#' + b.dataset.window + '"]');
      if (cell) cell.classList.toggle('off', !b.checked);
    });
  }
  boxes.forEach(function (b) { b.addEventListener('change', sync); });
  document.querySelectorAll('[data-select]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      boxes.forEach(function (b) { b.checked = btn.dataset.select === 'all'; });
      sync();
    });
  });
  if (boxes.length) sync();
  document.querySelectorAll('[data-copy]').forEach(function (b) {
    b.addEventListener('click', function () {
      var done = function () { b.textContent = 'Copied'; setTimeout(function () { b.textContent = 'Copy feed link'; }, 1600); };
      if (navigator.clipboard) { navigator.clipboard.writeText(b.dataset.copy).then(done); return; }
      var r = document.createRange(); r.selectNodeContents(document.getElementById('feed-url'));
      var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
    });
  });
})();
"""
