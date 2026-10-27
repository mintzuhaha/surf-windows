# Surf Windows

Puts good surf windows for Pleasure Point (Santa Cruz) on your calendar. Every forecast hour for the coming week is scored against the user's preferences (wave size, tide, wind, rain, daylight, free hours). Good hours are merged into windows and published as a web page plus a calendar feed anyone can subscribe to.

## Today's goal (MVP, due end of day)

A live link at `https://surf-windows.vercel.app` that shows this week's windows and offers a one-click subscribe link to `/feed.ics`. Preferences come from `config.yaml` (no form yet). Ship small, then improve.

**In scope today:** fetch → score → merge → publish, an HTML page and `feed.ics` deployed on Vercel, unit tests on saved fixtures.

**Out of scope today:** preferences form, Google Calendar API, traffic, accounts, database. Do not build these unless asked.

## Stack

- Python 3.12
- Vercel Python serverless functions under `api/`
- Libraries: `httpx`, `PyYAML`, `astral`, `icalendar`, `pytest`. Ask before adding anything else.
- No frontend framework. One server-rendered HTML page with plain CSS. A few lines of inline JS are fine (e.g. copy-to-clipboard).

## Layout

```
surf/                 pure logic; only fetch.py does I/O
  fetch.py            API clients, return plain dicts
  normalize.py        merge sources into hourly records in local time
  score.py            classify each hour (pure functions)
  windows.py          merge hours into windows, find near misses (pure)
  ics.py              windows -> iCalendar text
  render.py           windows -> HTML
api/
  index.py            GET /          -> HTML page
  feed.py             GET /feed.ics  -> text/calendar
scripts/
  record_fixtures.py  fetch real responses once into tests/fixtures/
tests/
  fixtures/
  test_score.py  test_windows.py  test_ics.py
config.yaml
DECISIONS.md
```

## Data sources (free, no API keys)

- **Swell:** Open-Meteo Marine, `https://marine-api.open-meteo.com/v1/marine`
  - `hourly=wave_height,wave_period,wave_direction,swell_wave_height,swell_wave_period,swell_wave_direction`
  - `timezone=America/Los_Angeles&forecast_days=7`
  - Heights are meters by default. Directions are where waves come FROM (0° = north).
- **Wind and rain:** Open-Meteo Forecast, `https://api.open-meteo.com/v1/forecast`
  - `hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation`
  - `wind_speed_unit=mph&precipitation_unit=inch&timezone=America/Los_Angeles&forecast_days=7&past_days=3`
  - `past_days=3` is required for the 72-hour rain rule.
- **Tides:** NOAA CO-OPS station `9413450` (Monterey). The Santa Cruz station `9413745` is a subordinate station with high/low predictions only, so `interval=h` fails there (see DECISIONS.md).
  - `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&station=9413450&datum=MLLW&interval=h&units=english&time_zone=lst_ldt&format=json&begin_date=YYYYMMDD&end_date=YYYYMMDD&application=surf-windows`
  - Request today through today+7 (local dates), so the last forecast hour still has a "next hour" for rising/falling.
- **Daylight:** compute dawn, sunrise and sunset locally with `astral` for the spot's lat/lon. No API.
- **Attribution (required):** show "Weather data by Open-Meteo.com" and "Tide predictions: NOAA" on the page. Open-Meteo is free for non-commercial use.

## Scoring rules

For each local hour in the next 7 days, starting from the current hour. Hours that already ended today are never scored and never become windows.

1. **Hard filters**, in order. Record the first failure as the hour's reason.
   - `dark`: the hour must start no earlier than 15 minutes before civil dawn (`DAWN_GRACE` in score.py) and end at or before sunset.
   - `busy`: the hour must fall inside a free slot for that day (weekday vs weekend lists in config).
   - `rain`: if total precipitation in the prior `rain.skip_after_hours` hours is >= `rain.threshold_in`, the hour fails.
2. **Classify** the hour:
   - **Face height (ft)** = `swell_wave_height_m × 3.281 × period_factor × spot.size_factor`, where `period_factor = min(1.4, 1 + 0.05 × max(0, period_s − 10))`. Fall back to `wave_height` / `wave_period` when swell values are null. These constants are starting guesses: keep them in one place and note any change in DECISIONS.md.
   - **Size bucket** from `size_buckets` in config.
   - **Wind class.** Offshore = wind blowing FROM within ±60° of `(spot.faces_deg + 180) mod 360`. `glassy` = speed < 5 mph or offshore. `light` = not glassy and speed <= 12 mph. `windy` = everything else.
   - **Tide level:** `high` when the tide reaches the break's `spot.high_tide_ft` (Pleasure Point: 4.2 ft) at the start or end of the hour. Below that, the bottom third of that calendar day's predicted range = `low`, the rest = `mid`. **Direction** from the next hour's predicted height (`rising` / `falling`).
3. **Apply preferences.** Each factor's value maps to `skip | ok | fav` in config.
   - The tide state is upgraded to `fav` when the tide stays below the break's `spot.ideal_tide_ft` (Pleasure Point: 3.7 ft) at the start and end of the hour, unless its level is `skip`.
   - The hour **passes** when no factor is `skip` and its tide direction is enabled.
   - The hour is **favored** when size is `fav` AND (wind is `fav` OR tide level is `fav`).
4. Every hour keeps an explanation: each factor's value and state, plus the failure reason when it fails.

## Windows

- Merge consecutive passing hours within the same day. Drop runs shorter than `min_window_hours`.
- A window is **favored** when at least half its hours are favored.
- A window is **tentative** when it starts `tentative_after_days` (3) or more calendar days after today, by local date: `(window_date - today).days >= tentative_after_days`.
- Stable id: `f"{spot_id}-{YYYYMMDD}-{start_hour:02d}"`.
- **Near misses:** if there are fewer than 2 windows this week, also return the top 5 daylight + free hours that failed exactly one factor, with that reason (e.g. "Thu 8am: chest-high, but 14 mph onshore"). The page uses these for its empty state.

## Calendar feed (`/feed.ics`)

- One `VEVENT` per window. `UID` = window id + `@surf-windows`. Include `DTSTAMP`. Use `America/Los_Angeles` times.
- `SUMMARY`: `★ Surf: Pleasure Point · chest-high · glassy` for favored, `Surf: Pleasure Point · waist-high` otherwise. Prefix tentative ones `Surf (tentative): …`.
- `DESCRIPTION`: one line per factor (size, wind, tide, rain, daylight) and `Updated <local time>`.
- Calendar headers: `X-WR-CALNAME:Surf windows`, `REFRESH-INTERVAL;VALUE=DURATION:PT3H`, `X-PUBLISHED-TTL:PT3H`.
- `?skip=<window id>,<window id>` leaves those windows out. Everything else, including windows that appear later, stays in.

## Page (`/`)

- Header with the spot name and "Updated N minutes ago".
- Label the windows section "Next 7 days", not "This week".
- Windows grouped by day: time range, size, wind, tide, plus rain and daylight checks. Favored windows look stronger; tentative ones are labeled.
- Empty state: "Flat week. Here's what's closest:" followed by the near misses with reasons.
- Buttons: "Add to Google Calendar" using Google's add-by-URL link (`https://calendar.google.com/calendar/render?cid=<url-encoded webcal:// feed URL>`; verify it works on desktop and phone) and "Copy feed link".
- Each window card has an "Add" checkbox, all checked by default, plus "Select all" / "Deselect all". The Google button, copy button and feed URL leave unchecked windows out via `?skip=`.
- "How it works" (3 bullets), a link to the GitHub repo, and the data attribution.
- Works at phone width.
- Visual reference: mockup screenshots in `docs/` if present. Colors: favored `#12466F`, will-surf `#9EC5E8`, text `#10283A`, background `#F4F5F2`. Fonts: IBM Plex Sans and IBM Plex Mono (Google Fonts).

## Caching

Fetch on request, and set `Cache-Control: s-maxage=1800, stale-while-revalidate=3600` on both endpoints so Vercel's CDN serves cached responses. Use one shared fetch per request for both sources.

## How to work

- Plan first and wait for approval. Then build in this order, committing after each step: fixtures script → fetch → normalize → score → windows → ics → render → api → deploy.
- Logic in `surf/` is pure and type-hinted. Tests run offline against `tests/fixtures/`.
- Log every non-obvious choice in `DECISIONS.md`: one or two lines with the why.
- Never commit secrets or a home location. The config holds only the public spot.
- Ask before adding dependencies, changing the layout, or building anything out of scope.
