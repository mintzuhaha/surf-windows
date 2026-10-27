"""GET /feed.ics -> iCalendar feed, one event per surf window."""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api._http import feed_response, send  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        send(self, feed_response(urlsplit(self.path).query))

    def do_HEAD(self) -> None:
        send(self, feed_response(urlsplit(self.path).query), include_body=False)
