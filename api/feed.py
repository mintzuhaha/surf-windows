"""GET /feed.ics -> iCalendar feed, one event per surf window."""

from __future__ import annotations

import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surf.ics import build_feed  # noqa: E402
from surf.pipeline import run  # noqa: E402

CACHE_CONTROL = "s-maxage=1800, stale-while-revalidate=3600"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            forecast = run()
            body = build_feed(forecast.windows, forecast.config, forecast.now)
        except Exception:
            traceback.print_exc()
            self._send(503, "text/plain; charset=utf-8", "Forecast sources are unavailable. Try again in a few minutes.\n", "no-store")
            return
        self._send(200, "text/calendar; charset=utf-8", body, CACHE_CONTROL)

    def _send(self, status: int, content_type: str, body: str, cache_control: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        if content_type.startswith("text/calendar"):
            self.send_header("Content-Disposition", 'inline; filename="surf-windows.ics"')
        self.end_headers()
        self.wfile.write(data)
