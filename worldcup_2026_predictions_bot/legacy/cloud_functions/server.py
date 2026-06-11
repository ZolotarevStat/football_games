from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .app_factory import build_bot_from_env

LOG = logging.getLogger(__name__)
BOT = build_bot_from_env()


class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def do_POST(self) -> None:
        if self.path not in {"/", "/webhook"}:
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            update = json.loads(body.decode("utf-8") or "{}")
            BOT.handle_update(update)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        except Exception:
            LOG.exception("Webhook request failed")
            self.send_response(500)
            self.end_headers()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    server = ThreadingHTTPServer(("0.0.0.0", 8080), WebhookHandler)
    LOG.info("Listening on http://0.0.0.0:8080/webhook")
    server.serve_forever()


if __name__ == "__main__":
    main()

