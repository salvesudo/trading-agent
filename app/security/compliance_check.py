"""
Run this before a live trading session: `python -m app.security.compliance_check`

Unlike app/core/config_check.py, this DOES contact the network -- a real
IP-lookup service and the real FYERS API -- because that's the only way
to actually check a static IP or a session token. See
app/security/compliance.py for what each check does and why automatic
gating on these results is later-phase work, not wired in yet.
"""
from __future__ import annotations

from app.core.console import ensure_utf8_stdio
from app.security.compliance import run_compliance_check


def _status(label: str, ok: bool, detail: str) -> str:
    mark = "✅" if ok else "❌"
    return f"{mark} {label} — {detail}"


def main() -> None:
    ensure_utf8_stdio()
    print("=" * 60)
    print("FYERS TRADING AGENT — COMPLIANCE CHECK (Phase 3)")
    print("=" * 60)
    print("This contacts the network: an IP-lookup service and the real")
    print("FYERS API. Nothing here places an order.")
    print()

    report = run_compliance_check()
    for check in report.checks:
        print(_status(check.name, check.ok, check.detail))

    print("=" * 60)
    if report.all_passed:
        print("All compliance checks passed.")
    else:
        print("One or more checks failed -- see above. These results are")
        print("advisory only in this phase; nothing yet blocks LIVE mode")
        print("automatically based on them (see docs/PRINCIPLES.md).")


if __name__ == "__main__":
    main()
