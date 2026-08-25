"""
FYERS API v3 daily login flow -- Phase 2.

FYERS requires a fresh login + 2FA + app authorization once per trading
day; this SDK's auth flow has no long-lived refresh token, only the
"authorization code" exchange documented for API v3. This module wraps
that exchange and persists the resulting access token to `.env`, so the
rest of the app just reads `FYERS_ACCESS_TOKEN` at startup like any
other config value (app/core/config.py).

Meant to be run by a human, once a day, before trading starts:

    python -m app.broker.auth

It never runs automatically, is not wired into the agent loop, and
never places an order -- it only ever writes one line to `.env`.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from app.broker.models import BrokerError
from app.core.config import settings
from app.core.console import ensure_utf8_stdio


@dataclass(frozen=True)
class TokenResult:
    access_token: str
    raw_response: dict


class FyersAuthManager:
    """Wraps fyers_apiv3.SessionModel with typed errors.

    No network call happens until `exchange_auth_code` is invoked --
    `login_url()` only builds a URL string locally.
    """

    def __init__(self, app_id: str, secret_id: str, redirect_uri: str, state: str = "fyers_agent"):
        if not app_id or not secret_id or not redirect_uri:
            raise BrokerError(
                "FYERS_APP_ID, FYERS_SECRET_ID and FYERS_REDIRECT_URI must "
                "all be set in .env before starting the auth flow."
            )
        self.app_id = app_id
        self.secret_id = secret_id
        self.redirect_uri = redirect_uri
        self.state = state

    def _session(self):
        # Imported lazily so importing this module never requires the
        # real SDK to be present for tests that only exercise the
        # non-network parts (extract_auth_code, _update_env_file).
        from fyers_apiv3.fyersModel import SessionModel

        return SessionModel(
            client_id=self.app_id,
            secret_key=self.secret_id,
            redirect_uri=self.redirect_uri,
            response_type="code",
            grant_type="authorization_code",
            state=self.state,
        )

    def login_url(self) -> str:
        return self._session().generate_authcode()

    def exchange_auth_code(self, auth_code: str) -> TokenResult:
        if not auth_code:
            raise BrokerError("auth_code is empty.")
        session = self._session()
        session.set_token(auth_code)
        response = session.generate_token()
        if not isinstance(response, dict) or response.get("s") != "ok":
            detail = response.get("message", response) if isinstance(response, dict) else response
            raise BrokerError(f"Token exchange failed: {detail}")
        access_token = response.get("access_token", "")
        if not access_token:
            raise BrokerError(f"Token exchange returned no access_token: {response}")
        return TokenResult(access_token=access_token, raw_response=response)


def extract_auth_code(redirected_url_or_code: str) -> str:
    """Accept either the bare auth_code or the full redirect URL FYERS
    sends the browser to, and return just the code."""
    match = re.search(r"[?&]auth_code=([^&]+)", redirected_url_or_code)
    if match:
        return match.group(1)
    return redirected_url_or_code.strip()


def update_env_file(env_path: Path, key: str, value: str) -> None:
    """Rewrite a single KEY=value line in .env, appending it if missing.

    .env is already gitignored (see .gitignore) -- this never touches
    .env.example, and never runs unless a human invokes this module.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    pattern = re.compile(rf"^{re.escape(key)}=.*$")
    new_line = f"{key}={value}"
    for i, line in enumerate(lines):
        if pattern.match(line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="FYERS API v3 daily login flow. Only ever writes an "
                     "access token to .env -- never places an order."
    )
    parser.add_argument(
        "--code",
        help="The auth_code (or the full redirect URL containing it) from "
             "the browser after completing FYERS login/2FA. If omitted, "
             "you'll be prompted after opening the login URL.",
    )
    parser.add_argument(
        "--env-file", default=".env",
        help="Path to the .env file to update with the new access token.",
    )
    args = parser.parse_args()

    try:
        manager = FyersAuthManager(
            app_id=settings.fyers_app_id,
            secret_id=settings.fyers_secret_id,
            redirect_uri=settings.fyers_redirect_uri,
        )

        print("=" * 60)
        print("FYERS DAILY LOGIN")
        print("=" * 60)
        print("1. Open this URL in a browser and complete login + 2FA:")
        print(f"   {manager.login_url()}")
        print("2. After authorizing, FYERS redirects to your redirect URI with")
        print("   an auth_code query parameter. Paste that full URL (or just")
        print("   the code) below.")

        code_input = args.code or input("auth_code or redirect URL: ")
        auth_code = extract_auth_code(code_input)

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
