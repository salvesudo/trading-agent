"""
Backtesting engine -- Phase 12.

Answers the question every phase since 9 has flagged and none has
answered: do any of the six strategies actually have edge? To make that
answer trustworthy, this replays historical candles through the *exact*
production code path -- app.strategy.engine.generate_signals,
app.risk.risk_engine.RiskEngine, app.paper.engine.PaperTradingEngine --
rather than a separate reimplementation that could quietly diverge from
what would actually run live.

No look-ahead: at simulated bar `i`, every decision (regime, signals,
risk evaluation) only ever sees `candles[:i+1]`, never a future bar.

Pure and DB-free by design, unlike app/paper/service.py -- a backtest is
throwaway analysis, not production state, and must never be persisted
into the same tables live/paper trading uses (Phase 5/11). It reuses
app.risk.capital_ledger.CapitalLedger and
app.risk.service.compute_next_account_state directly (both already
pure) rather than app/risk/service.py's DB-backed functions.

News is not backtested -- app.news.aggregator has no historical
archive, only live RSS feeds, so every StrategyContext here gets
news_items=[] and the NEWS strategy will simply never fire in a
backtest. This is a real, current limitation, not a design choice to be
proud of; a result that leans on NEWS won't show up here at all.

Single-symbol only: this drives one `symbol` through one candle series.
A multi-symbol backtest would need synchronized candle feeds across
symbols, which is future work, not this phase's scope.

Bounded lookback, not full history, on every bar: earlier versions of
this loop handed `candles[:i+1]` -- the *entire* history since bar 0 --
to detect_regime()/generate_signals() on every single bar. Every
indicator underneath (app/analysis/indicators.py) rebuilds a pandas
DataFrame from scratch and recomputes over its whole input each call,
and a couple of them (ADX, Supertrend) do that with a Python-level loop
rather than a vectorized op. Doing that with an ever-growing window
across thousands of bars is quadratic, not linear -- on a real multi-
month 5-minute-candle backtest (thousands of bars) it made the CLI look
hung when it was just doing an enormous, unnecessary amount of repeat
work. MAX_LOOKBACK_CANDLES below caps the window each bar actually
sees to its own trailing slice, which is also the more honest reading
of what these modules already claim to do -- detect_regime's own
docstring says "recent history" for its percentile ranking, not "all
history since inception."
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, List, Optional

from app.analysis.indicators import InsufficientDataError
from app.backtest.models import BacktestResult, StrategyStats
from app.data.models import Candle
from app.paper.engine import PaperTradingEngine, PositionLimitError
from app.paper.models import PaperPosition
from app.regime.detector import detect_regime
from app.risk.capital_ledger import CapitalLedger, initial_ledger
from app.risk.risk_engine import AccountState, RiskDecision, RiskEngine
from app.risk.service import compute_next_account_state
from app.strategy.candidate import to_trade_candidate
from app.strategy.engine import Strategy, generate_signals, select_best_signal
from app.strategy.models import StrategyContext

# Comfortably above every indicator/strategy's own minimum (ADX needs
# window*2=28, MACD needs 26, breakout needs LOOKBACK+1=21) while still
# being a bounded, constant-size window -- see this module's docstring
# for why an unbounded window was a real (quadratic) problem, not just a
# style choice. 300 candles is ~4 trading days of 5-minute bars or well
# over a year of daily bars; either way it's "recent history" for
# regime/percentile purposes, not the entire backtest range.
MAX_LOOKBACK_CANDLES = 300


def _max_drawdown_pct(equity_curve: List[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak * 100.0)
    return worst


def _strategy_breakdown(trades: List[PaperPosition]) -> List[StrategyStats]:
    groups: dict[str, List[PaperPosition]] = {}
    for trade in trades:
        groups.setdefault(trade.strategy or "UNKNOWN", []).append(trade)
    stats = []
    for name, group in groups.items():
        pnls = [t.realized_pnl() for t in group]
        stats.append(
            StrategyStats(
                strategy=name,
                trade_count=len(group),
                wins=sum(1 for p in pnls if p > 0),
                losses=sum(1 for p in pnls if p <= 0),
                total_pnl_inr=sum(pnls),
            )
        )
    return sorted(stats, key=lambda s: s.strategy)


def run_backtest(
    candles: List[Candle],
    symbol: str,
    strategies: Optional[List[Strategy]] = None,
    initial_capital_inr: Optional[float] = None,
    protected_floor_inr: Optional[float] = None,
    estimated_costs: float = 15.0,
    max_lookback_candles: int = MAX_LOOKBACK_CANDLES,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> BacktestResult:
    """Replay `candles` (ascending, one symbol) through the strategy
    engine and Risk Engine, simulating fills via PaperTradingEngine.
    Raises InsufficientDataError if there's nothing meaningful to
    replay (fewer than 2 candles).

    `on_progress(bars_done, total_bars)`, if given, is called
    periodically -- purely cosmetic (e.g. so a CLI can print a progress
    line on a long run), never affects the replay itself."""
    if len(candles) < 2:
        raise InsufficientDataError("Need at least 2 candles to run a backtest.")

    engine = PaperTradingEngine()
    ledger = initial_ledger(initial_capital_inr, protected_floor_inr)
    starting_capital_inr = ledger.total_equity_inr  # captured before any trade mutates the ledger
    account_state = AccountState()
    equity_curve: List[float] = [ledger.total_equity_inr]

    def _book_close(closed: PaperPosition) -> None:
        nonlocal account_state, ledger
        pnl = closed.realized_pnl()
        account_state = compute_next_account_state(account_state, pnl)
        ledger = ledger.apply_trade_outcome(pnl)
        equity_curve.append(ledger.total_equity_inr)

    total_bars = len(candles) - 1
    for i in range(1, len(candles)):
        if on_progress is not None and (i % 500 == 0 or i == total_bars):
            on_progress(i, total_bars)
        window = candles[max(0, i + 1 - max_lookback_candles) : i + 1]
        current_candle = window[-1]

        closed = engine.process_candle(symbol, current_candle)
        if closed is not None:
            _book_close(closed)

        if engine.open_positions:
            continue  # already holding this symbol -- no new entry until it's flat

        try:
            regime = detect_regime(window)
        except InsufficientDataError:
            continue  # not enough history yet for a regime reading

        context = StrategyContext(symbol=symbol, candles=window, regime=regime, news_items=[])
        best = select_best_signal(generate_signals(context, strategies=strategies))
        if best is None:
            continue

        candidate = to_trade_candidate(best, account_equity=ledger.tradable_capital_inr, estimated_costs=estimated_costs)
        verdict = RiskEngine(account_state).evaluate(candidate)
        if verdict.decision != RiskDecision.APPROVE:
            continue

        try:
            engine.open_position(candidate, verdict, current_candle.timestamp, strategy=best.strategy.value)
        except PositionLimitError:
            continue  # shouldn't happen given the "already holding" check above; stay defensive anyway

    # Data ran out with a position still open -- force-close at the last
    # candle so every trade in the report is actually closed. A real,
    # continuously-running system wouldn't do this; a backtest has to.
    last = candles[-1]
    for open_position in list(engine.open_positions):
        closed = engine.close_manually(open_position.symbol, last.close, last.timestamp)
        _book_close(closed)

    return BacktestResult(
        symbol=symbol,
        start=candles[0].timestamp,
        end=candles[-1].timestamp,
        starting_capital_inr=starting_capital_inr,
        ending_tradable_capital_inr=ledger.tradable_capital_inr,
        ending_reserved_capital_inr=ledger.reserved_capital_inr,
        total_trades=len(engine.closed),
        wins=sum(1 for t in engine.closed if t.realized_pnl() > 0),
        losses=sum(1 for t in engine.closed if t.realized_pnl() <= 0),
        total_realized_pnl_inr=sum(t.realized_pnl() for t in engine.closed),
        max_drawdown_pct=_max_drawdown_pct(equity_curve),
        per_strategy=_strategy_breakdown(engine.closed),
        trades=list(engine.closed),
    )


__all__ = ["run_backtest"]
