"""
One-shot local HTTP listener for the FYERS OAuth-style redirect -- Phase 2.

app/broker/auth.py's default flow works by manual copy-paste: open the
login URL, complete FYERS login, then paste the resulting redirect URL
back into the CLI. That works even when FYERS_REDIRECT_URI points at
nothing reachable (see docs/PRINCIPLES.md, README).

This module is for the case where the redirect URI *is* reachable (e.g.
an EC2 instance with the port open to your browser): it binds a tiny
HTTP server, waits for FYERS to redirect the browser here with
`?auth_code=...`, exchanges it immediately, and writes the token to
`.env` -- no copy-paste required. It handles exactly one callback, then
stops; it is not meant to run as a long-lived service.

Like the rest of app/broker/, this never places an order -- it only
ever writes an access token to `.env`. Not exercised against a live
FYERS redirect from this environment (no live network access here).
"""
from __future__ import annotations

import argparse
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from app.broker.auth import FyersAuthManager, update_env_file
from app.broker.models import BrokerError
from app.core.config import settings
from app.core.console import ensure_utf8_stdio


@dataclass
class _CallbackResult:
    auth_code: Optional[str] = None
    error: Optional[str] = None


def _make_handler(callback_path: str, result: _CallbackResult, done: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib naming convention)
            parsed = urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)
            auth_code = params.get("auth_code", [None])[0]
            if auth_code:
                result.auth_code = auth_code
                self.send_response(200)
                body = b"<html><body><h3>FYERS login received. You can close this tab.</h3></body></html>"
            else:
                result.error = f"No auth_code in callback query string: {parsed.query!r}"
                self.send_response(400)
                body = b"<html><body><h3>Login failed: no auth_code received. Check the terminal.</h3></body></html>"
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, fmt: str, *args) -> None:
            pass  # keep stdout clean; the CLI prints its own status lines

    return Handler


class CallbackServer:
    """Binds immediately on construction (so a bad host/port fails fast,
    before the login URL is even printed); `wait()` then blocks until a
    single callback request arrives, or `timeout_seconds` elapses."""

    def __init__(self, host: str, port: int, path: str) -> None:
        self._path = path
        self._result = _CallbackResult()
        self._done = threading.Event()
        self._server = HTTPServer((host, port), _make_handler(path, self._result, self._done))
        self.port = self._server.server_address[1]

    def wait(self, timeout_seconds: int = 300) -> str:
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        try:
            if not self._done.wait(timeout=timeout_seconds):
                raise BrokerError(
                    f"Timed out after {timeout_seconds}s waiting for the FYERS "
                    f"redirect on port {self.port}{self._path}. If this is an "
                    "EC2/cloud instance, check the security group and OS "
                    "firewall both allow inbound TCP on that port from "
                    "wherever your browser is."
                )
        finally:
            self._server.shutdown()
        if self._result.error:
            raise BrokerError(self._result.error)
        assert self._result.auth_code is not None
        return self._result.auth_code


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Start a one-shot local HTTP listener for the FYERS "
                     "redirect, so the auth-code exchange happens "
                     "automatically instead of manual copy-paste."
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Interface to bind. 0.0.0.0 accepts the redirect from an "
             "external browser (e.g. an EC2 instance); 127.0.0.1 restricts "
             "it to the same machine.",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--path", default="/fyers/callback",
        help="Must match the path portion of FYERS_REDIRECT_URI exactly.",
    )
    parser.add_argument(
        "--timeout", type=int, default=300,
        help="Seconds to wait for the redirect before giving up.",
    )
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    try:
        manager = FyersAuthManager(
            app_id=settings.fyers_app_id,
            secret_id=settings.fyers_secret_id,
            redirect_uri=settings.fyers_redirect_uri,
        )
        server = CallbackServer(args.host, args.port, args.path)

        print("=" * 60)
        print("FYERS DAILY LOGIN (automatic callback)")
        print("=" * 60)
        print(f"Listening on {args.host}:{server.port}{args.path}")
        print("1. Open this URL in a browser and complete login + 2FA:")
        print(f"   {manager.login_url()}")
        print(f"2. Waiting up to {args.timeout}s for FYERS to redirect back here...")

        auth_code = server.wait(args.timeout)
        result = manager.exchange_auth_code(auth_code)
        update_env_file(Path(args.env_file), "FYERS_ACCESS_TOKEN", result.access_token)
        print("=" * 60)
        print(f"Access token saved to {args.env_file}. Valid for today's trading session only.")
        print("Run this again tomorrow before the market opens.")
    except BrokerError as exc:
        print(f"\n❌ {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
