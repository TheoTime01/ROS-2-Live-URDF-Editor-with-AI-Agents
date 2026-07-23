#!/usr/bin/env python3
"""Zero-dependency static dev server for the URDF live editor front-end.

The front-end is a plain ES-module app with no build step, so serving it is just
static file hosting with correct MIME types and no-cache headers (so edits show
up on refresh). In offline mode the app uses its in-browser mock backend; to
point it at a real ``web_api_node`` instead, open::

    http://localhost:8080/?api=http://localhost:8000

Usage::

    python3 server.py [--port 8080] [--host 127.0.0.1]
"""

from __future__ import annotations

import argparse
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WEB_ROOT = os.path.dirname(os.path.abspath(__file__))


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".css": "text/css",
        ".json": "application/json",
        ".svg": "image/svg+xml",
    }

    def end_headers(self):
        # Dev convenience: never cache, so a hard refresh always reloads modules.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):  # quieter, structured-ish logging
        print(f"[web] {self.address_string()} {fmt % args}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    handler = partial(Handler, directory=WEB_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving URDF live editor UI at http://{args.host}:{args.port}/  (Ctrl-C to stop)")
    print("Offline mock backend is used unless you pass ?api=<web_api_node_url>.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
