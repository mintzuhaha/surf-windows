"""Responses shared by the endpoints. Vercel builds this project as one Python app
with api/index.py as the entrypoint, so index.py routes /feed.ics itself."""

from __future__ import annotations

import sys
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from surf.ics import build_feed  # noqa: E402
from surf.pipeline import run  # noqa: E402
from surf.render import render_page  # noqa: E402

CACHE_CONTROL = "s-maxage=1800, stale-while-revalidate=3600"
UNAVAILABLE = "Forecast sources are unavailable. Try again in a few minutes.\n"


class Response(NamedTuple):
    status: int
    content_type: str
    body: str
    cache_control: str


def page_response(headers) -> Response:
    try:
        return Response(200, "text/html; charset=utf-8", render_page(run(), feed_url(headers)), CACHE_CONTROL)
    except Exception:
        traceback.print_exc()
        return Response(503, "text/plain; charset=utf-8", UNAVAILABLE, "no-store")


def feed_response() -> Response:
    try:
        forecast = run()
        body = build_feed(forecast.windows, forecast.config, forecast.now)
        return Response(200, "text/calendar; charset=utf-8", body, CACHE_CONTROL)
    except Exception:
        traceback.print_exc()
        return Response(503, "text/plain; charset=utf-8", UNAVAILABLE, "no-store")


def not_found() -> Response:
    return Response(404, "text/plain; charset=utf-8", "Not found\n", "s-maxage=86400")


def send(handler: BaseHTTPRequestHandler, response: Response, include_body: bool = True) -> None:
    data = response.body.encode()
    handler.send_response(response.status)
    handler.send_header("Content-Type", response.content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", response.cache_control)
    if response.content_type.startswith("text/calendar"):
        handler.send_header("Content-Disposition", 'inline; filename="surf-windows.ics"')
    handler.end_headers()
    if include_body:
        handler.wfile.write(data)


def feed_url(headers) -> str:
    host = headers.get("x-forwarded-host") or headers.get("host") or "surf-windows.vercel.app"
    proto = headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.0.0.1")) else "https")
    return f"{proto}://{host}/feed.ics"
