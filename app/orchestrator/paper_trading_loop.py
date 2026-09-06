"""
Paper trading loop -- ties every prior phase together into something
that actually runs. See app/orchestrator/__init__.py for why this is
the right next step instead of more backtesting or Phase 13.

Run it:

    python -m app.orchestrator.paper_trading_loop \\
        --watchlist NSE:RELIANCE-EQ,NSE:INFY-EQ,NSE:ICICIBANK-EQ,NSE:TCS-EQ \\
        --poll-interval 300

Needs a completed daily login (python -m app.broker.auth or
callback_server.py) and TRADING_MODE=PAPER -- refuses to start
otherwise. Runs a compliance check (app/security/compliance.py) once
at startup and refuses to start if it fails; does not re-check mid-day
(deliberately -- polling that on every cycle would be excessive against
FYERS' own API, and a session, once valid, stays valid until the next
day's token expiry).

Per cycle, for every symbol in the watchlist:
  1. Fetch a trailing window of real candles (15 calendar days --
     comfortably more than MAX_LOOKBACK_CANDLES=300 needs, so there is
     no cold-start "warm-up" period the way a fresh backtest has one --
     see docs/PRINCIPLES.md section 27 on exactly that bug).
  2. Check any existing open position for an exit (stop/target/
     square-off) via app.paper.service.close_position -- the same
     tick-based process_price_update() live trading always uses, never
     process_candle() (that is backtest-only, see docs/PRINCIPLES.md
     section 24).
  3. If still flat, run detect_regime + generate_signals (with live
     news this cycle fetched, unlike any backtest -- see
     app/backtest/engine.py's own docstring on why NEWS never fires
     there) + select_best_signal, size it with a real cost estimate
     (app.broker.costs), and evaluate via the Risk Engine. Approved ->
     open a paper position. Rejected or no signal -> do nothing.

STOP_TRADING (the kill switch, checked fresh every cycle) force-closes
every open position immediately rather than running the normal cycle
at all -- same principle as app.paper.engine.PaperTradingEngine.
close_manually (docs/PRINCIPLES.md section 8).

Known, deliberate simplifications for a first working version (not
silently glossed over): single-process, no crash resilience beyond
what restore_open_positions() already rebuilds from the database on
restart; refetches the full trailing candle window every cycle rather
than maintaining an incremental store (app/data/store.py exists for
that and isn't used here yet); does not know about NSE holidays (a
holiday just produces no new candles, so the loop harmlessly does
nothing that cycle rather than erroring, but it will still wake up and
try).
"""
from __future__ import annotations

import argparse
import datetime as dt
import time
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from app.analysis.indicators import InsufficientDataError
from app.broker.client import FyersClient
from app.broker.costs import estimate_intraday_costs
from app.broker.models import BrokerError
from app.core.config import TradingMode, settings
from app.core.console import ensure_utf8_stdio
from app.data.history import fetch_candles
from app.data.models import Timeframe
from app.news import aggregator as news_aggregator
from app.news.models import NewsItem
from app.paper import service as paper_service
from app.paper.engine import PaperTradingEngine, PositionLimitError
from app.regime.detector import detect_regime
from app.risk import service as risk_service
from app.risk.risk_engine import RiskDecision, RiskEngine
from app.security.compliance import run_compliance_check
from app.strategy.candidate import to_trade_candidate
from app.strategy.engine import generate_signals, select_best_signal
from app.strategy.models import StrategyContext

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
CANDLE_LOOKBACK_DAYS = 15  # calendar days of history refetched each cycle -- see module docstring


def _log(message: str) -> None:
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    print(f"[{timestamp}] {message}", flush=True)


def _symbol_keyword(symbol: str) -> str:
    """'NSE:RELIANCE-EQ' -> 'RELIANCE' -- a rough, best-effort company
    keyword for app.news.aggregator.filter_by_keyword's substring match.
    Same documented limitation as that function itself: no NER, no
    fuzzy matching, a company referred to by a different name in a
    headline just won't match."""
    core = symbol.split(":")[-1]
    return core.split("-")[0]


def is_market_open(local_time: dt.datetime) -> bool:
    """`local_time` must already be in IST. NSE trading hours only --
    does not know about market holidays (see module docstring)."""
    if local_time.weekday() >= 5:  # Saturday/Sunday
        return False
    current = (local_time.hour, local_time.minute)
    return MARKET_OPEN <= current < MARKET_CLOSE


def process_symbol(
    session: Session,
    engine: PaperTradingEngine,
    client: FyersClient,
    symbol: str,
    news_items: List[NewsItem],
    now: dt.datetime,
) -> None:
    """One symbol's worth of one cycle: check for an exit, then --
    only if still flat -- look for a new entry. Never raises for an
    ordinary "nothing to do" outcome (no candles, no signal, rejected
    candidate); callers should still catch unexpected exceptions per
    symbol so one symbol's failure doesn't take down the whole cycle."""
    range_to = now.date().isoformat()
    range_from = (now.date() - dt.timedelta(days=CANDLE_LOOKBACK_DAYS)).isoformat()
    candles = fetch_candles(client, symbol, Timeframe.FIVE_MINUTES, range_from, range_to)
    if len(candles) < 2:
        _log(f"[{symbol}] No usable candles yet this cycle -- skipping.")
        return

    latest = candles[-1]
    closed = paper_service.close_position(session, engine, symbol, price=latest.close, current_time=now)
    if closed is not None:
        _log(
            f"[{symbol}] Closed {closed.side} qty={closed.quantity} via {closed.exit_reason.value} "
            f"-- net P&L ₹{closed.realized_pnl():.2f}"
        )

    if any(p.symbol == symbol for p in engine.open_positions):
        return  # still (or now newly) holding -- no new entry until flat

    try:
        regime = detect_regime(candles)
    except InsufficientDataError:
        return

    context = StrategyContext(symbol=symbol, candles=candles, regime=regime, news_items=news_items)
    best = select_best_signal(generate_signals(context))
    if best is None:
        return

    ledger = risk_service.load_or_initialize_ledger(session)
    account_state = risk_service.load_account_state(session)
    cost_estimate = estimate_intraday_costs(
        entry_price=best.entry_price, stop_loss=best.stop_loss, account_equity=ledger.tradable_capital_inr
    )
    candidate = to_trade_candidate(best, account_equity=ledger.tradable_capital_inr, estimated_costs=cost_estimate)
    verdict = RiskEngine(account_state).evaluate(candidate)
    if verdict.decision != RiskDecision.APPROVE:
        _log(f"[{symbol}] {best.strategy.value} signal REJECTED: {verdict.reason}")
        return

    try:
        paper_service.open_position(session, engine, candidate, verdict, opened_at=now, strategy=best.strategy.value)
        _log(
            f"[{symbol}] Opened {candidate.side} qty={verdict.approved_quantity} @ ₹{candidate.entry_price:.2f} "
            f"via {best.strategy.value} (stop ₹{candidate.stop_loss:.2f}, target ₹{candidate.target:.2f})"
        )
    except PositionLimitError as exc:
        _log(f"[{symbol}] Approved but could not open: {exc}")


def _flatten_everything(session: Session, engine: PaperTradingEngine, client: FyersClient, now: dt.datetime) -> None:
    """STOP_TRADING is set -- close every open position immediately at
    the latest available price, regardless of stop/target/square-off.
    Same principle as PaperTradingEngine.close_manually
    (docs/PRINCIPLES.md section 8): the kill switch always wins."""
    for position in list(engine.open_positions):
        try:
            range_to = now.date().isoformat()
            range_from = (now.date() - dt.timedelta(days=CANDLE_LOOKBACK_DAYS)).isoformat()
            candles = fetch_candles(client, position.symbol, Timeframe.FIVE_MINUTES, range_from, range_to)
            price = candles[-1].close if candles else position.entry_price
            closed = paper_service.close_position_manually(session, engine, position.symbol, price=price, current_time=now)
            _log(f"[{position.symbol}] STOP_TRADING: force-closed -- net P&L ₹{closed.realized_pnl():.2f}")
        except Exception as exc:  # noqa: BLE001 -- flattening must not stop partway through
            _log(f"[{position.symbol}] STOP_TRADING: failed to force-close cleanly: {exc}")


def _stop_trading_now() -> bool:
    """Re-read STOP_TRADING fresh from .env/the environment on every
    call, rather than trusting the long-lived `settings` singleton
    imported once at process start. This loop can run for hours -- the
    kill switch (docs/PRINCIPLES.md section 8) needs an edit to .env to
    take effect on the very next cycle, not require restarting the
    whole process."""
    from app.core.config import Settings

    return Settings().stop_trading


def run_cycle(
    session_factory: sessionmaker,
    engine: PaperTradingEngine,
    client: FyersClient,
    watchlist: List[str],
    now: dt.datetime,
) -> None:
    """One full pass over the watchlist, in its own DB session/commit."""
    with session_factory() as session:
        if _stop_trading_now():
            _log("STOP_TRADING is set -- flattening all open positions, skipping the normal cycle.")
            _flatten_everything(session, engine, client, now)
            session.commit()
            return

        news_items = news_aggregator.fetch_all()
        for symbol in watchlist:
            try:
                symbol_news = news_aggregator.filter_by_keyword(news_items, _symbol_keyword(symbol))
                process_symbol(session, engine, client, symbol, symbol_news, now)
            except Exception as exc:  # noqa: BLE001 -- one symbol's failure shouldn't sink the cycle
                _log(f"[{symbol}] ERROR this cycle: {exc}")
        session.commit()


def run_forever(
    watchlist: List[str],
    poll_interval_seconds: int = 300,
    max_iterations: Optional[int] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    ensure_utf8_stdio()
    if settings.trading_mode != TradingMode.PAPER:
        raise SystemExit(
            f"Refusing to start: TRADING_MODE={settings.trading_mode.value}, must be PAPER. "
            "This loop never places a real order regardless, but it should never even run "
            "while the rest of the system is configured for LIVE."
        )

    from app.db.base import build_engine, build_sessionmaker

    _log("Running startup compliance check...")
    report = run_compliance_check()
    for check in report.checks:
        _log(f"  [{'OK' if check.ok else 'FAIL'}] {check.name}: {check.detail}")
    if not report.all_passed:
        raise SystemExit("Compliance check failed -- see above. Refusing to start.")

    db_engine = build_engine()
    session_factory = build_sessionmaker(db_engine)
    client = FyersClient.from_settings()
    engine = PaperTradingEngine()

    with session_factory() as session:
        restored = paper_service.restore_open_positions(session, engine)
        _log(f"Restored {restored} open position(s) from the database.")

    _log(f"Watching {len(watchlist)} symbol(s): {', '.join(watchlist)}. Polling every {poll_interval_seconds}s.")

    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        now_utc = dt.datetime.now(dt.timezone.utc)
        local = now_utc.astimezone(IST)
        if not is_market_open(local):
            _log(f"Outside market hours ({local.strftime('%a %H:%M')} IST) -- sleeping.")
        else:
            try:
                run_cycle(session_factory, engine, client, watchlist, now_utc)
            except (BrokerError, Exception) as exc:  # noqa: BLE001 -- a bad cycle must not kill the loop
                _log(f"Cycle failed unexpectedly: {exc}")
        iteration += 1
        sleep_fn(poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the continuous paper-trading loop. Never places a real order -- "
        "refuses to start unless TRADING_MODE=PAPER."
    )
    parser.add_argument(
        "--watchlist",
        required=True,
        help='Comma-separated FYERS symbols, e.g. "NSE:RELIANCE-EQ,NSE:INFY-EQ,NSE:ICICIBANK-EQ,NSE:TCS-EQ" '
        "(these four, plus HDFCBANK/SBIN/ITC/LT, are the eight this project has already backtested).",
    )
    parser.add_argument("--poll-interval", type=int, default=300, help="Seconds between cycles (default 300 = 5 min)")
    parser.add_argument(
        "--max-iterations", type=int, default=None, help="Stop after this many cycles (mainly for a controlled test run)"
    )
    args = parser.parse_args()
    watchlist = [s.strip() for s in args.watchlist.split(",") if s.strip()]
    run_forever(watchlist, poll_interval_seconds=args.poll_interval, max_iterations=args.max_iterations)


if __name__ == "__main__":
    main()


__all__ = ["is_market_open", "process_symbol", "run_cycle", "run_forever"]
