# Decisions

One or two lines per choice, with the why. Newest at the bottom.

- **2026-10-27 · Backend service, not a Chrome extension.** It has to keep working when the laptop is closed, and the calendar on my phone is the real interface.
- **2026-10-27 · Calendar feed (ICS) before the Google Calendar API.** No sign-in needed, so it ships today. Tradeoff: Google refreshes subscribed calendars on its own schedule, often hours apart. Revisit in M1.
- **2026-10-27 · Wave-height buckets instead of board profiles.** Simpler to configure, and it's how surfers actually describe conditions.
- **2026-10-27 · Three-state preferences (skip / will surf / favored).** One control gives both a filter and a ranking.
- **2026-10-27 · Hourly granularity.** Matches the forecast data. Windows are whole hours.
- **2026-10-27 · Stateless, no database.** Preferences live in config.yaml for now and will move into the feed URL in M3. Vercel's CDN cache stands in for storing forecasts.
- **2026-10-27 · Rough face-height conversion.** Open-ocean swell height isn't what breaks at a sheltered spot, so the model applies a period factor and a spot factor. Both are guesses until calibrated against real sessions.
- **2026-10-27 · Swell at the spot's own coordinates.** Checked Open-Meteo Marine at 36.95469, -121.97253: it snaps to a sea cell (36.958, -121.958) with no nulls across all 168 hours, so no offshore point is needed. `record_fixtures.py` prints null counts to re-check.
- **2026-10-27 · Tides from Monterey (9413450), not Santa Cruz (9413745).** Santa Cruz is a subordinate station: NOAA serves only high/low there and rejects `interval=h`. Its published offsets from Monterey are 6-11 min and x0.97-0.99 height, too small to change a tide third or direction at hourly resolution, and this avoids interpolating highs/lows.
