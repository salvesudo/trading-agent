"""
Run this to backtest the strategy engine against real historical candles:

    python -m app.backtest.run_backtest --symbol NSE:RELIANCE-EQ \\
        --timeframe 5 --from-date 2025-01-01 --to-date 2025-06-01

Fetches real candles via FyersClient.history() (needs a working daily
login -- see app/broker/auth.py) and replays them through
app.backtest.engine.run_backtest, then prints a report.

Not runnable from this environment (no FYERS credentials here) -- this
is the script meant to finally answer, on real data, whether any of the
six strategies (Phase 9) actually have edge. Nothing it does places an
order; it only ever reads historical data.
"""
from __future__ import annotations

import argparse

from app.analysis.indicators import InsufficientDataError
from app.backtest.engine import MAX_LOOKBACK_CANDLES, run_backtest
from app.backtest.models import BacktestResult
from app.broker.client import FyersClient
from app.broker.models import BrokerError
from app.core.console import ensure_utf8_stdio
from app.data.history import fetch_candles
from app.data.models import Timeframe


def _print_report(result: BacktestResult) -> None:
    print("=" * 60)
    print(f"BACKTEST REPORT: {result.symbol}")
    print(f"{result.start} -> {result.end}")
    print("=" * 60)
    print(f"Starting capital:  ₹{result.starting_capital_inr:,.2f}")
    print(
        f"Ending equity:     ₹{result.ending_total_equity_inr:,.2f} "
        f"(tradable ₹{result.ending_tradable_capital_inr:,.2f} + "
        f"reserved ₹{result.ending_reserved_capital_inr:,.2f})"
    )
    print(f"Net return:        {result.net_return_pct:+.2f}%")
    print(f"Max drawdown:      {result.max_drawdown_pct:.2f}%")
    print()
    print(
        f"Total trades: {result.total_trades}  Wins: {result.wins}  Losses: {result.losses}  "
        f"Win rate: {result.win_rate_pct:.1f}%"
    )
    print(f"Total realized P&L (net of est. costs): ₹{result.total_realized_pnl_inr:,.2f}")
    print()
    print("Per strategy:")
    if not result.per_strategy:
        print("  (no trades)")
    for stats in result.per_strategy:
        print(
            f"  {stats.strategy:20s} trades={stats.trade_count:4d} "
            f"win_rate={stats.win_rate_pct:5.1f}%  pnl=₹{stats.total_pnl_inr:,.2f} (net)"
        )
    print("=" * 60)
    print("All P&L above is net of estimated per-trade costs (--costs, "
          f"₹{result.total_estimated_costs_inr:,.2f} total across {result.total_trades} trades here) -- "
          "not just a display adjustment, this is what actually posts to the ledger now.")
    print("None of this has been backtested/calibrated before now -- see")
    print("docs/PRINCIPLES.md sections 17, 19, 22. A backtest result is a")
    print("starting point for judgment, not proof of a working strategy.")
    print("News is NOT included -- no historical news archive exists yet,")
    print("so the NEWS strategy never fires here (see engine.py's own docstring).")


def main() -> None:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Backtest the strategy engine against real historical candles. Read-only -- never places an order."
    )
    parser.add_argument("--symbol", required=True, help='e.g. "NSE:RELIANCE-EQ"')
    parser.add_argument(
        "--timeframe", default="5", choices=[t.value for t in Timeframe], help="FYERS resolution (minutes, or 1D)"
    )
    parser.add_argument("--from-date", required=True, help="yyyy-mm-dd")
    parser.add_argument("--to-date", required=True, help="yyyy-mm-dd")
    parser.add_argument("--equity", type=float, default=None, help="Starting capital (defaults to INITIAL_CAPITAL_INR)")
    parser.add_argument("--costs", type=float, default=15.0, help="Estimated per-trade costs, in rupees")
    parser.add_argument(
        "--max-lookback",
        type=int,
        default=MAX_LOOKBACK_CANDLES,
        help="Trailing candles shown to regime/strategy detection each bar (bounded window, not full history)",
    )
    args = parser.parse_args()

    try:
        timeframe = Timeframe(args.timeframe)
        client = FyersClient.from_settings()
        candles = fetch_candles(client, args.symbol, timeframe, args.from_date, args.to_date)
        print(f"Fetched {len(candles)} candles for {args.symbol} ({args.from_date} to {args.to_date}).")

        def _report_progress(done: int, total: int) -> None:
            print(f"  ...processed {done}/{total} bars ({done / total * 100:.0f}%)", flush=True)

        result = run_backtest(
            candles,
            args.symbol,
            initial_capital_inr=args.equity,
            estimated_costs=args.costs,
            max_lookback_candles=args.max_lookback,
            on_progress=_report_progress,
        )
        _print_report(result)
    except (BrokerError, InsufficientDataError) as exc:
        print(f"\n❌ {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
