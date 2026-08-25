"""
Compliance checks -- Phase 3: static IP, session/2FA freshness, permissions.

Unlike app/core/config_check.py (which never touches the network), these
checks are meant to contact both a public IP-lookup service and the real
FYERS API -- that's the whole point of a static-IP check, and the only way
to know an access token still actually works is to use it. Run this
deliberately, not on every process start:

    python -m app.security.compliance_check

Three things are checked:

1. **Static IP** -- FYERS requires the calling IP to be pre-whitelisted.
   This fetches the machine's current outbound public IP and compares it
   to FYERS_STATIC_IP. A mismatch here means every live API call will be
   rejected by FYERS regardless of what this codebase does right.
2. **Session freshness** -- FYERS access tokens are daily and there is no
   refresh-token flow in this SDK (see app/broker/auth.py). The only
   reliable way to know today's token still works is to use it: this
   calls FyersClient.profile().
3. **Algo-trading permission** -- code cannot verify this; see
   `Settings.owner_confirmed_algo_permissions`. This check only confirms
   the owner has explicitly acknowledged it, not that it's actually true.

None of this is wired into the Risk Engine or the agent loop yet -- like
`AccountState` in app/risk/risk_engine.py, automatic gating on these
results is later-phase work (once system health has somewhere to live,
e.g. the database in Phase 5). For now this is a diagnostic the owner runs
by hand, same spirit as config_check.py, just with real network calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

from app.core.config import settings

DEFAULT_IP_LOOKUP_URL = "https://checkip.amazonaws.com"


class SupportsGet(Protocol):
    def get(self, url: str, timeout: float = ...) -> "_HttpResponseLike": ...


class _HttpResponseLike(Protocol):
    text: str

    def raise_for_status(self) -> None: ...


def fetch_public_ip(http_client: Optional[SupportsGet] = None, url: str = DEFAULT_IP_LOOKUP_URL) -> str:
    """Return this machine's current outbound public IP as seen by `url`.

    `http_client` defaults to a real httpx.Client -- imported lazily so
    importing this module never requires network machinery for tests
    that inject a fake.
    """
    if http_client is None:
        import httpx

        http_client = httpx.Client()
    response = http_client.get(url, timeout=10.0)
    response.raise_for_status()
    return response.text.strip()


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ComplianceReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(check.ok for check in self.checks)


def check_static_ip(ip_fetcher: Callable[[], str] = fetch_public_ip) -> CheckResult:
    configured = settings.fyers_static_ip
    if not configured:
        return CheckResult(
            "static_ip",
            False,
            "FYERS_STATIC_IP is not set in .env -- nothing to compare against.",
        )
    try:
        actual = ip_fetcher()
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole run
        return CheckResult("static_ip", False, f"Could not determine outbound IP: {exc}")
    if actual == configured:
        return CheckResult("static_ip", True, f"Outbound IP {actual} matches FYERS_STATIC_IP.")
    return CheckResult(
        "static_ip",
        False,
        f"Outbound IP is {actual}, but FYERS_STATIC_IP is set to {configured}. "
        "FYERS will reject live API calls from this machine until this matches "
        "what's whitelisted with FYERS, or FYERS_STATIC_IP is updated to the "
        "IP actually whitelisted.",
    )


def check_session_valid(profile_fetcher: Optional[Callable[[], dict]] = None) -> CheckResult:
    if not settings.fyers_app_id or not settings.fyers_access_token:
        return CheckResult(
            "session_valid",
            False,
            "FYERS_APP_ID / FYERS_ACCESS_TOKEN not set -- run python -m app.broker.auth first.",
        )
    if profile_fetcher is None:
        from app.broker.client import FyersClient

        profile_fetcher = FyersClient.from_settings().profile
    try:
        profile = profile_fetcher()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "session_valid",
            False,
            f"Today's access token did not authenticate: {exc}. "
            "Run python -m app.broker.auth (or callback_server) again.",
        )
    name = profile.get("data", {}).get("name", "") if isinstance(profile, dict) else ""
    return CheckResult("session_valid", True, f"Access token authenticates as {name!r}.".strip())


def check_algo_permissions_acknowledged() -> CheckResult:
    if settings.owner_confirmed_algo_permissions:
        return CheckResult(
            "algo_permissions_acknowledged",
            True,
            "Owner has set OWNER_CONFIRMED_ALGO_PERMISSIONS=true.",
        )
    return CheckResult(
        "algo_permissions_acknowledged",
        False,
        "OWNER_CONFIRMED_ALGO_PERMISSIONS is not set. This code cannot verify "
        "SEBI algo-trading registration or FYERS API permissions itself -- "
        "confirm directly with FYERS/exchange what current rules require for "
        "this account, then set this flag deliberately in .env.",
    )


def run_compliance_check(
    ip_fetcher: Callable[[], str] = fetch_public_ip,
    profile_fetcher: Optional[Callable[[], dict]] = None,
) -> ComplianceReport:
    return ComplianceReport(
        checks=[
            check_static_ip(ip_fetcher),
            check_session_valid(profile_fetcher),
            check_algo_permissions_acknowledged(),
        ]
    )


__all__ = [
    "CheckResult",
    "ComplianceReport",
    "fetch_public_ip",
    "check_static_ip",
    "check_session_valid",
    "check_algo_permissions_acknowledged",
    "run_compliance_check",
]
