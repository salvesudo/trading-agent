"""
Run this before anything else: `python -m app.core.config_check`

Prints a checklist of what's configured vs. missing. Never prints secret
values -- only whether a variable is set, per spec section 42/43 (never
expose credentials in logs).
"""
from app.core.config import settings, TradingMode
from app.core.console import ensure_utf8_stdio


def _status(label: str, ok: bool, detail: str = "") -> str:
    mark = "✅" if ok else "❌"
    return f"{mark} {label}{(' — ' + detail) if detail and not ok else ''}"


def main() -> None:
    ensure_utf8_stdio()
    print("=" * 60)
    print("FYERS TRADING AGENT — CONFIG CHECK")
    print("=" * 60)

    print(_status("TRADING_MODE set", True, detail=settings.trading_mode.value))
    print(f"   -> mode = {settings.trading_mode.value}")
    if settings.trading_mode == TradingMode.LIVE:
        print("   ⚠️  LIVE mode is set. This script does NOT verify you have")
        print("      passed paper-trading acceptance criteria. That is a")
        print("      manual owner decision -- see docs/ACCEPTANCE_CRITERIA.md.")

    print(_status("STOP_TRADING flag readable", True, detail=str(settings.stop_trading)))

    print(_status("FYERS_APP_ID present", bool(settings.fyers_app_id)))
    print(_status("FYERS_SECRET_ID present", bool(settings.fyers_secret_id)))
    print(_status("FYERS_REDIRECT_URI present", bool(settings.fyers_redirect_uri)))
    print(_status("FYERS_STATIC_IP present", bool(settings.fyers_static_ip),
                   "required before any live order placement, see docs/STATIC_IP.md"))
    print(_status("FYERS_ACCESS_TOKEN present", bool(settings.fyers_access_token),
                   "obtained via the auth flow, not hand-entered"))

    print(_status("DATABASE_URL present", bool(settings.database_url)))

    print(_status("Capital floor set", True, detail=f"₹{settings.protected_capital_inr}"))
    print(_status("Max risk/trade <= 1%", settings.max_risk_per_trade_pct <= 1.0,
                   detail=f"{settings.max_risk_per_trade_pct}%"))
    print(_status("Max daily loss <= 2%", settings.max_daily_loss_pct <= 2.0,
                   detail=f"{settings.max_daily_loss_pct}%"))

    print(_status("OWNER_EMAIL present", bool(settings.owner_email),
                   "reports can't be sent until this is set"))

    print("=" * 60)
    print("This check does NOT contact FYERS or verify the static IP is")
    print("actually whitelisted -- run python -m app.security.compliance_check")
    print("for that (it contacts the network; this script never does).")


if __name__ == "__main__":
    main()
