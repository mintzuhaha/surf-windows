"""GET / -> HTML page of the next 7 days' surf windows. Also routes /feed.ics (see _http.py)."""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api._http import Response, feed_response, not_found, page_response, send  # noqa: E402

PAGE_PATHS = {"/", "/api/index", "/api/index.py"}
FEED_PATHS = {"/feed.ics", "/api/feed", "/api/feed.py"}


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        send(self, self._route())

    def do_HEAD(self) -> None:
        send(self, self._route(), include_body=False)

    def _route(self) -> Response:
        path = urlsplit(self.path).path
        if path in PAGE_PATHS:
            return page_response(self.headers)
        if path in FEED_PATHS:
            return feed_response()
        return not_found()
