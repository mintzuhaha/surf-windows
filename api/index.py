"""GET / -> HTML page of the next 7 days' surf windows."""

from __future__ import annotations

import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surf.pipeline import run  # noqa: E402
from surf.render import render_page  # noqa: E402

CACHE_CONTROL = "s-maxage=1800, stale-while-revalidate=3600"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        try:
            body = render_page(run(), feed_url(self.headers))
        except Exception:
            traceback.print_exc()
            self._send(503, "text/plain; charset=utf-8", "Forecast sources are unavailable. Try again in a few minutes.\n", "no-store")
            return
        self._send(200, "text/html; charset=utf-8", body, CACHE_CONTROL)

    def _send(self, status: int, content_type: str, body: str, cache_control: str) -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)


def feed_url(headers) -> str:
    host = headers.get("x-forwarded-host") or headers.get("host") or "surf-windows.vercel.app"
    proto = headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.0.0.1")) else "https")
    return f"{proto}://{host}/feed.ics"
