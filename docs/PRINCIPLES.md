# Principles

This document is the working reference for the rules the code already
enforces. It exists because `README.md` and several modules (`app/risk/
risk_engine.py`, `app/core/config.py`, `app/core/config_check.py`) cite
numbered sections of the owner's master prompt in comments, but that
master prompt itself is not checked into this repo. This file reconstructs
those sections from what is actually implemented, so the reasoning behind
a check is discoverable from the docs, not just from a comment pointing
at a document nobody here can open.

If the owner's original master prompt and this file ever disagree, the
master prompt wins — update this file to match it, not the other way
around.

## 0. Survival > profit

The single governing principle, stated in `README.md`: **survival of the
₹5,000 starting capital matters more than any single trade's profit.**
Every other rule in this document is a specific, mechanical consequence
of that one sentence. When a future phase is ambiguous about what to do,
resolve it in favor of the account surviving to trade another day.

## 1. Roles and authority (spec section 47)

Three layers, one hierarchy:

1. **Strategy / AI advisory layer** (technical analysis, regime detection,
   news/sentiment, LLM) — *proposes* candidate trades. It has opinions,
   not authority.
2. **Risk Engine** (`app/risk/risk_engine.py`) — *approves or rejects*
   every candidate. Its decision is final and cannot be overridden by
   any other module, including the LLM. This is the one non-negotiable
   architectural rule in the whole system.
3. **Execution Engine** (not yet built — Phase 14) — executes only what
   the Risk Engine has approved, exactly as approved (symbol, side,
   quantity). It has no discretion to resize or re-route an order.

No module upstream of the Risk Engine may talk to the broker directly.

## 2. Capital floor (spec sections 2, 5)

- `INITIAL_CAPITAL_INR` / `PROTECTED_CAPITAL_INR` = ₹5,000 by default
  (`app/core/config.py`). This is the amount the system is built to
  protect, not a number that changes because a strategy looks confident.
- Capital growth is a *result* of surviving, not a target that risk rules
  bend to reach faster.

## 3. Per-trade risk ceiling (spec section 4)

- `MAX_RISK_PER_TRADE_PCT` defaults to 1% of current equity and is
  **hard-capped at 1% in code** (`Settings._cap_risk_per_trade`) — the
  application refuses to start if `.env` asks for more. This is a
  backstop; the Risk Engine re-derives and re-checks position size on
  every single candidate at runtime too (defense in depth, not a single
  point of failure).
- Position size is derived from the stop distance, never guessed:
  `quantity = floor(risk_amount_inr / stop_distance)`, then walked down
  further until estimated transaction costs are also inside the risk
  budget (`RiskEngine.evaluate`, step 6).

## 4. Daily loss limit (spec section 22)

- `MAX_DAILY_LOSS_PCT` defaults to 2% of equity and is capped at 2% in
  code (`Settings._cap_daily_loss`).
- Once today's realized loss reaches that limit, the Risk Engine rejects
  every new candidate for the rest of the day
  (`RiskDecision.REJECT_DAILY_LOSS_LIMIT`). There is no override path in
  this phase — a human can only change it by editing `.env` before the
  next run, deliberately, outside the running system.

## 5. Consecutive loss protection (spec section 23)

- `CONSECUTIVE_LOSS_SOFT_LIMIT` (default 3) and
  `CONSECUTIVE_LOSS_HARD_LIMIT` (default 5) exist because a losing streak
  is often a signal that the current regime doesn't match the strategy,
  not that the next trade will "average it out."
- At the hard limit the Risk Engine halts new trades
  (`RiskDecision.REJECT_CONSECUTIVE_LOSSES`) pending review. The soft
  limit is reserved for a later phase (e.g. throttling size or triggering
  a notification) once the journal/notification layers exist.

## 6. Stop loss and expected value are mandatory (spec sections 14, 18)

- A candidate with no stop loss, or a stop equal to entry, is rejected
  outright (`RiskDecision.REJECT_NO_STOP_LOSS`) — there is no such thing
  as a trade without a defined worst case.
- A candidate whose reward at target, net of estimated costs, is not
  strictly positive is rejected (`RiskDecision.REJECT_NEGATIVE_EXPECTED_VALUE`).
  Costs (brokerage, STT, GST, exchange fees, slippage) are a first-class
  input to every risk decision, not an afterthought applied to a report
  later.

## 7. System health gating (spec sections 20, 56, 57)

- The Risk Engine will not approve trades while `AccountState.system_healthy`
  is `False` — stale market data, a down database, or a reconciliation
  mismatch between the broker's view of positions and this system's own
  are all reasons to stop, not to keep trading on unverified state.
  `AccountState` is a Phase-1 placeholder; wiring it to real DB/health
  checks is later-phase work (Database, Position Reconciliation, Monitoring).

## 8. Kill switch (spec section referenced via `STOP_TRADING`)

- `STOP_TRADING=true` in `.env` is checked first, before every other
  rule, and blocks all new positions unconditionally
  (`RiskDecision.REJECT_KILL_SWITCH`). It is intentionally the crudest,
  least clever control in the system — a kill switch that had edge cases
  would not be a kill switch.

## 9. Paper before live, always (README, `docs/ACCEPTANCE_CRITERIA.md`)

- `TRADING_MODE` defaults to `PAPER`. Nothing in this codebase contains a
  code path that flips it to `LIVE` automatically. That switch is a
  manual, deliberate act by the owner, made only after the criteria in
  [`ACCEPTANCE_CRITERIA.md`](ACCEPTANCE_CRITERIA.md) are met.
- `app/agent.py::build_paper_agent` raises if `TRADING_MODE` is anything
  other than `PAPER` while no execution adapter exists — a second,
  independent guard against accidentally-live behavior during
  early-phase development, on top of the Risk Engine and the
  `execution_available()` check.

## 10. No secrets in logs or output (spec sections 42, 43)

- `app/core/config_check.py` prints *whether* a credential is set, never
  its value. Every future module that logs configuration state must
  follow the same rule: presence/absence and non-sensitive metadata only.

## 11. Build order is sequential, not a suggestion (spec section 63)

- The 22-phase order in `README.md` exists because later phases
  (execution, live testing) depend on earlier ones (risk engine,
  reconciliation, monitoring) actually working and being tested first.
  "Skipping ahead to live execution" is called out explicitly as the
  failure mode this order exists to prevent.

## 12. The broker client is its own guard, too (Phase 2)

`app/broker/client.py::FyersClient` re-checks `settings.is_live` on every
call that can create, modify, or cancel an order, and refuses outright if
`TRADING_MODE` is not `LIVE` — independent of the Risk Engine, the agent's
own `build_paper_agent` check (section 9), and whatever the execution
engine will eventually do in a later phase. Read-only calls (quotes,
profile, positions, funds, orderbook, tradebook) carry no such guard —
later phases need those in `PAPER` mode too, and none of them can move
money or create broker-side state.

The daily auth flow (`app/broker/auth.py`, run as `python -m app.broker.auth`)
only ever writes an access token to `.env`. It has no path to place an
order either, by construction, not just by convention.

## 13. Compliance checks are advisory until they have somewhere to live (Phase 3)

`app/security/compliance.py` (`python -m app.security.compliance_check`)
checks the static IP, session/token freshness, and an explicit
`OWNER_CONFIRMED_ALGO_PERMISSIONS` acknowledgment. None of it is wired
into the Risk Engine or the agent loop automatically yet — same as
`AccountState` in section 7, it needs a database (Phase 5) to be
something the running system can check on every cycle rather than a
script the owner runs by hand. Treat a failing compliance check as a
reason not to trade that day, manually, until that wiring exists.

The one check code cannot do itself is confirming SEBI algo-trading /
FYERS permission requirements are actually met -- those requirements
change over time and this codebase should not be trusted as the source
of truth for them (see README). `OWNER_CONFIRMED_ALGO_PERMISSIONS` makes
that gap an explicit, deliberate acknowledgment instead of a silent
assumption.

## 14. Volume is cumulative, not per-tick (Phase 4)

FYERS quote updates (REST and WS alike) carry the day's *cumulative*
traded volume, not a per-tick trade size. `app/data/candle_builder.py`
diffs successive cumulative readings to get each candle's own volume,
clamping negative deltas (e.g. a new trading day's counter resetting) to
zero rather than subtracting. Anything built later that reads candle
volume (breakout/volume-confirmation logic, for instance) depends on
this being right -- if it silently regressed to just copying the
cumulative field, every candle would report the full day's volume
instead of its own, and nothing about that would look obviously wrong
in a quick glance at the numbers.

## 15. The database exists; nothing reads from it *automatically* yet (Phase 5, wired in Phase 10)

`app/risk/service.py` (Phase 10) can now load real, DB-backed
`AccountState` and `CapitalLedger`, build a ready-to-use `RiskEngine`
from them, and record a closed trade's outcome across both atomically.
`app/agent.py::build_paper_agent` accepts an optional `session` and will
use it -- but **nothing calls it that way automatically**. Without an
explicit `session`, `build_paper_agent()` still defaults to
`AccountState()`'s Phase-1 placeholder, on purpose. That's deliberate,
not an oversight: "today's realized P&L" and "consecutive losses" only
mean something once there's an actual persistent trading loop
accumulating them across multiple trades in a day, which doesn't exist
until Phase 11 (paper trading engine). Wiring the Risk Engine to
silently read stale or empty DB state before a real loop exists to keep
it current would be worse than the current explicit placeholder.
Phase 10 built the plumbing; Phase 11 is what's expected to actually
turn the tap on.

SQLite works against every model in `app/db/models.py` for local dev and
tests (see `app/db/base.py`), but Postgres is the intended production
database -- don't assume SQLite-specific behavior (or lack thereof, see
`app/db/repository.py::_as_utc`) generalizes; test anything dialect-
sensitive against both before trusting it in production.

## 16. Indicators fail loud on insufficient data, and Supertrend is unverified (Phase 6)

`app/analysis/indicators.py` raises `InsufficientDataError` rather than
handing back a mostly-NaN series when there aren't enough candles for a
requested window -- a NaN silently flowing into a later phase's strategy
logic is a worse failure mode than an explicit exception here, at the
one point that actually knows the data was too short.

EMA/RSI/MACD/ATR/ADX/Bollinger Bands are thin wrappers over the `ta`
library; Supertrend is hand-rolled because `ta` doesn't have one. Every
other indicator in this module inherits `ta`'s own correctness; Supertrend
inherits only whatever confidence its own directional tests provide (see
`tests/test_indicators.py`) -- it has not been cross-checked against
another implementation or a live chart. Treat it as the least-trusted
piece of this phase until someone does that comparison.

## 17. Regime thresholds are starting points, not calibrated (Phase 7)

`app/regime/detector.py` classifies trend via a fixed ADX threshold (25)
and volatility via percentile rank in recent history (33rd/67th cutoffs).
The percentile approach is deliberately instrument-relative -- a fixed
absolute volatility cutoff would silently misclassify whichever
instruments it wasn't tuned for, since "high volatility" means something
different for a ₹50 stock than for NIFTY. But the specific numbers (25,
33, 67) are still just defensible starting points, the same as
`docs/ACCEPTANCE_CRITERIA.md`'s numbers: nobody has calibrated them
against actual trading outcomes for the instruments this will trade.
Revisit them once Phase 9 (strategy engine) or Phase 12 (backtesting)
produces real evidence one way or the other.

## 18. News sentiment is a keyword heuristic, not a model (Phase 8)

`app/news/sentiment.py` counts positive/negative words from a small,
curated list -- it will misfire on sarcasm, negation ("shares fail to
fall"), and any real sentiment expressed in words that aren't on either
list. It's an honest, zero-dependency starting point, not a claim of
accuracy, and it was chosen deliberately over an LLM-based score for
this phase (see README's Phase 8 note on the source-selection decision).
Phase 13 (AI decision engine) is the natural place to replace or augment
it later -- don't assume this scorer is good enough to drive a real
trading decision on its own before that happens.

This is also the first phase in this project genuinely live-verified
*from Claude's own environment*, not just reported back by the owner --
public RSS feeds need no FYERS credentials or whitelisted IP. Don't
generalize that to mean other phases could have been verified here too;
it's specific to this phase's data source being public.

## 19. A signal is a proposal, never an order (Phase 9)

`app/strategy/`'s six strategies each return a `StrategySignal`, not a
`TradeCandidate` -- converting one to the other (`app/strategy/candidate.py`)
is a separate, explicit step that adds account equity and cost estimates
a strategy has no business knowing. No strategy imports anything from
`app/broker/client.py`'s order-placement methods, and nothing in
`app/strategy/` has any path to an order that doesn't go through the
Risk Engine first (spec section 47, section 1 above). `select_best_signal`
in `app/strategy/engine.py` is a simple confidence-based placeholder for
picking among strategies that disagree -- not a claim it's the right way
to arbitrate; real arbitration is later-phase work.

None of the six strategies' specific rules were backtested or calibrated
before shipping -- they're explicit, documented starting points, the
same honesty standard as Phase 7's regime thresholds. Don't read "the
Risk Engine approved a candidate" as "the strategy that produced it is
good" -- the Risk Engine only checks that a trade's *risk math* is sound
(position size, stop distance, daily/consecutive-loss limits), never
whether the underlying signal has any real edge. That question is still
completely open and won't be answered by anything before Phase 12
(backtesting).

## 20. Owner directives, added after Phase 9 (2026-08-26)

The owner gave six additional instructions before continuing past Phase
9. Recorded here in full so a later phase can't quietly drift from what
was actually agreed, and so anyone reading this understands *why* each
one is shaped the way it is.

**20.1 — "The agent should be scared of getting destroyed."** Already
the design, not new work: `MAX_RISK_PER_TRADE_PCT` (1%, hard-capped in
`app/core/config.py`), `MAX_DAILY_LOSS_PCT` (2%, also hard-capped), the
5-consecutive-loss hard halt, and the `STOP_TRADING` kill switch
together are what this principle *is*, mechanically. See section 0
("Survival > profit") and section 26 (defense in depth). Nothing to
build; a reason to never loosen any of the above without the owner
explicitly asking.

**20.2 — "It should earn something every day, no matter what."** Refused
as literally stated, and replaced with something safer after discussing
it with the owner: **a guaranteed daily profit is not something any
legitimate trading system can promise — markets have losing days, that's
arithmetic, not a solvable engineering problem.** Building toward a forced
daily win is one of the most well-documented ways retail accounts blow
up (oversizing late in the day to force a green number, ignoring a stop
because "today must be profitable," or quietly loosening the
kill-switch/daily-loss-limit that exist specifically to prevent this).
The agreed replacement: **the agent must genuinely look for a qualifying
setup every trading day and take one if the Risk Engine approves it, but
must be equally willing to end a day flat or red if nothing clears the
bar.** No future phase may lower a strategy's confidence threshold, relax
the Risk Engine, or add a "must trade by X o'clock" fallback in order to
manufacture activity. This is already how the architecture behaves today
— `app/strategy/engine.py::select_best_signal` returns `None` when
nothing fires, and nothing anywhere reacts to "no signal yet" by trying
harder — the point of this entry is to make sure it stays that way.

**20.3 — 20% profit reserve, swept after every winning trade.** Built:
`app/risk/capital_ledger.py`. After every trade that closes with
positive P&L, `PROFIT_RESERVE_PCT` (default 20%, `.env`-configurable) of
that profit moves into `reserved_capital_inr` and is never risked again;
the remaining 80% joins `tradable_capital_inr` and compounds. A loss
comes entirely out of tradable capital -- the reserve protects gains, it
never subsidizes losses. Per the owner's choice, the reserve is an
**untouchable buffer that stays in the account, not a withdrawal** -- it
still counts toward `total_equity_inr` (and toward whether the account
has breached `protected_floor_inr`), just never toward what the Risk
Engine sizes a position against. **Any code that builds a
`TradeCandidate` must pass `tradable_capital_inr`, never
`total_equity_inr`, as `account_equity`** (see
`app/strategy/candidate.py`) -- getting this backwards would silently
let the reserve be risked again, defeating the entire mechanism.
Persisted via `app/db/models.CapitalLedgerRow` (Phase 5's schema) but,
like `AccountState`, not wired into a live loop yet -- becomes load-
bearing once Phase 11 (paper trading engine) exists to call
`apply_trade_outcome()` after every closed trade.

**20.4 — "Keep earning until I ask it to stop; stop-loss always
present."** Already the design: `STOP_TRADING=true` is the "ask it to
stop" mechanism (section 8), and the Risk Engine already refuses any
candidate without a valid stop-loss (section 6). This item is really
asking for Phase 11's continuous loop to exist and run indefinitely,
respecting the kill switch -- nothing new to decide now, just confirming
the eventual loop must not add any other implicit stopping condition
(like a target profit that halts trading) unless the owner asks for one.

**20.5 — Long-term/positional holds for high-conviction stocks.**
Deferred by the owner's own choice: with only ₹5,000 total starting
capital, carving out a separate bucket for multi-day/weekly holds right
now would come directly out of the already-thin intraday risk budget.
**No capital split exists, and none should be added, until the account
has grown meaningfully beyond the starting capital and the owner
explicitly revisits this.** When it is revisited, it is a materially
different strategy than anything in `app/strategy/` today (overnight/gap
risk, a different product type than `INTRADAY`, a much higher conviction
bar than any of the six existing strategies use) -- treat it as new work
requiring its own design pass, not a small extension of Phase 9.

**20.6 — "Agent should invent its own best strategies from market
studies and world situations."** Refused as an autonomous, guaranteed-
profitable strategy generator -- no system, including a hedge fund's,
can honestly promise that. Scoped down, with the owner's agreement, to
exactly what Phase 13 already specifies: an **advisory-only** LLM layer
that can add macro/global-event context as one more input the strategy
engine considers. It never overrides the Risk Engine (spec section 47),
and nothing it produces gets trusted with real money until it's been
backtested (Phase 12) against actual historical data, same as every
other strategy. Building this is still future work (Phase 12 and 13
haven't started); this entry exists so the scope is agreed *before*
either phase is built, not decided under pressure while writing them.

## 21. The Risk Engine is now DB-ready, still not DB-driven (Phase 10)

`app/risk/service.py` closes the gap between the Phase-1 Risk Engine
(pure logic), the Phase-5 database (schema with nothing reading/writing
it automatically), and the Capital Ledger added after Phase 9 (also
pure logic). It provides `load_account_state`, `load_or_initialize_ledger`,
`build_risk_engine`, and — the one genuinely new operation —
`record_trade_close`, which updates `AccountState.today_realized_pnl`
and `consecutive_losses` *and* the `CapitalLedger`'s tradable/reserved
split together, in one session, so a caller can never persist one
without the other and leave them inconsistent.

`consecutive_losses` increments on a loss, resets to 0 on a win, and is
left unchanged on an exact breakeven (`realized_pnl == 0.0`) — a scratch
trade neither extends nor breaks a losing streak. This is a judgment
call, not something the owner specified; revisit it if it turns out to
matter once real trades start closing at exactly zero.

Still true after this phase: nothing calls any of this automatically.
See section 15.

## 22. Simulated fills stay simulated, and someone still has to press "go" (Phase 11)

`app/paper/engine.py` never imports anything from `app/broker/client.py`'s
order-placement methods -- there is no code path from a `PaperPosition`
to a real order, by construction, not just by the
`TRADING_MODE=LIVE` guard (section 12) that would also stop it. A
`PaperPosition` is a bookkeeping fiction that exists so the Risk
Engine's approvals have somewhere to be tracked to a close.

Two portfolio-level controls live here, not in the Risk Engine:
`MAX_CONCURRENT_POSITIONS` and one open position per symbol. The Risk
Engine evaluates exactly one candidate at a time and has no way to know
what else is already open -- these exist specifically to fill that gap,
and like every other threshold in this project (regime cutoffs, Phase 9
strategy parameters), the default of 3 concurrent positions is a
starting point, not calibrated against real outcomes.

Exit price is always the price actually observed when an exit condition
fired, never the idealized stop/target level -- a real fill can be
worse in a fast-moving market, and pretending otherwise would make
paper results look better than live ones ever will.

`app/paper/service.py::close_position` derives its trading day from
`current_time` (converted to IST), never from `dt.date.today()` --
getting this backwards was an actual bug caught by this phase's own
tests, not a hypothetical: a backtested or simulated timestamp would
otherwise have silently booked P&L against whatever the real-world date
happened to be when the test ran, not the date the trade actually
belongs to. Any future code that touches trade dates should default the
same way.

Everything built in Phases 1-11 is now a complete, tested set of parts:
market data, indicators, regime, news, six strategies, the Risk Engine,
capital ledger, and a position lifecycle. None of it runs on its own.
There is still no scheduler, no loop polling live prices during market
hours, nothing deciding when to call `generate_signals` or
`process_price_update`. Wiring that loop together is real, remaining
work -- don't describe Phase 11 as "the agent can trade now." It can't,
yet; it can be driven, one explicit call at a time, to prove every piece
behaves correctly.

## 23. A backtest is only trustworthy if it runs the real code (Phase 12)

`app/backtest/engine.py` replays historical candles through the exact
same `generate_signals` / `RiskEngine` / `PaperTradingEngine` code that
would run live -- deliberately, not a separate, faster, or simplified
reimplementation. A backtest that scores a *fork* of the strategy/risk
logic answers a different question than "would this actually have
worked," and the gap between the two only shows up once real money is
on the line. If a strategy, the Risk Engine, or the paper engine ever
changes, this backtest changes with it automatically -- that coupling
is the point, not a coincidence to be refactored away.

No look-ahead is enforced structurally, not by convention: at simulated
bar `i`, `detect_regime` and `generate_signals` are only ever given
`candles[:i+1]`. Any future change to this loop that hands a strategy
more than that -- even accidentally, even for "just checking something"
-- would produce results that cannot happen live and should not be
trusted.

News is not backtested. There is no historical news archive (Phase 8 is
live RSS only), so every `StrategyContext` built here gets
`news_items=[]`, and the NEWS strategy will never fire in a backtest.
A strategy mix that looks weak here may simply be missing the one input
that isn't replayable yet -- don't read a backtest report as covering
all six strategies equally.

A backtest result is a starting point for judgment, not proof of a
working strategy: it says a strategy's *rules*, applied mechanically to
*this specific historical window*, would have produced *this* outcome.
It says nothing about a different window, different market conditions,
or overfitting to whichever window was chosen. Treat every number this
produces with the same skepticism as any other unvalidated threshold in
this project (sections 17, 19).

## 24. What the first real-data backtest run actually found (2026-08-26)

Running `app/backtest/run_backtest.py` against real FYERS candles for
the first time (RELIANCE, INFY, ICICIBANK, TCS, all March-May 2025,
5-minute bars) surfaced three real bugs that months of synthetic-data
testing never would have -- all worth recording so nobody "fixes" them
back in later without reading why.

**1. Unbounded lookback was quadratic, not a hang.** The bar loop in
`run_backtest()` originally handed `detect_regime()`/`generate_signals()`
the *entire* history since bar 0 (`candles[:i+1]`, growing every bar).
Every indicator underneath rebuilds a pandas DataFrame from scratch and
recomputes over its whole input each call, and two of them (ADX,
Supertrend) do that with a Python-level loop rather than a vectorized
op. Across thousands of bars that's O(n²), and a real 3-month/5-minute
run (4425 bars) made the CLI look permanently hung with zero output.
Fixed by bounding the window each bar sees to a trailing
`MAX_LOOKBACK_CANDLES` (300, comfortably above every indicator's own
minimum) -- also the more honest reading of what `detect_regime`'s own
docstring already claimed ("recent history," not "all history since
inception"). A progress callback was added to the CLI too, so a slow
run is never silent again.

**2. Costs were sized for, never actually deducted -- anywhere.**
`app/risk/risk_engine.py`'s sizing/approval math treats
`estimated_costs` as real money leaving the account (it reduces
approved quantity and required reward:risk), but
`PaperPosition.realized_pnl()` never actually subtracted it -- the
capital ledger, `AccountState.today_realized_pnl`, and every backtest
report were silently gross-of-costs. This isn't a backtest-only
cosmetic issue: `app/paper/service.py` uses the exact same
`realized_pnl()` for real (paper) capital tracking, so a live paper-
trading run would have understated how much a losing day actually cost
in the same way -- exactly the kind of optimism section 1 exists to
prevent. Fixed by giving `PaperPosition` an `estimated_costs` field
(threaded through from `TradeCandidate` at open, defaulting to 0.0 so
every pre-existing caller/test is unaffected) and having
`realized_pnl()` net it out; `gross_pnl()` still exists for anyone who
specifically wants the pre-cost number. New migration
`a1c7e0f2b834`.

Concretely, on the INFY run this took the reported result from "-1.2%,
roughly breakeven" to "-14.7% net of realistic costs" once 45 trades'
worth of `--costs` were actually counted -- the same trades, the same
market data, a materially different conclusion. Treat every number from
before this fix (there weren't any real-data ones yet) as gross, not
net.

**3. Close-only stop/target checking understated real stop-loss risk.**
Looking at real TREND_FOLLOWING trades one by one (`--show-trades`,
added for exactly this) surfaced a pattern: several stop-outs exited
noticeably past the nominal stop distance (one nearly 2x the intended
risk). The cause: `PaperTradingEngine.process_price_update()` is
tick-based -- correct for live/paper trading, which really does see one
price at a time -- but the backtest was feeding it one bar's *close*
per candle. On 5-minute bars, price can wick through a stop or target
intrabar and never show up in the close; the position survives bars it
should have exited, and by the time a later close finally confirms the
breach, price has often moved well past the original stop level. Fixed
by adding `process_candle()`, a backtest-only method that checks the
bar's full high/low range, with two standard, deliberately conservative
conventions: a fill can never be better than a gapped-through open
price, and if a single bar's range spans both stop and target (which
OHLC data alone can't order), stop is assumed hit first -- a strategy's
win rate should never look better than the data can actually support.
`app/backtest/engine.py` now calls `process_candle()` instead of
`process_price_update()`; nothing about live/paper trading changed.

## 25. Fixing TREND_FOLLOWING on the evidence, not a guess (2026-08-28)

Section 24 found bugs; this is different -- deliberate design changes
to TREND_FOLLOWING, made because two independent clean backtest runs
(post-lookback-fix and post-intrabar-fix, RELIANCE/INFY/ICICIBANK/TCS,
March-May 2025) both showed it losing every single time it fired
(0-for-10 combined). Three changes, each tied to a specific real trade,
not a parameter sweep fit to this small sample:

1. **No new entries within `MIN_MINUTES_BEFORE_SQUARE_OFF_FOR_ENTRY`
   (default 30) minutes of square-off.** A RELIANCE trade entered at
   14:20 IST, 55 minutes before the 15:15 square-off, and got flattened
   at a loss with no realistic chance of reaching target. This is a
   general portfolio-timing rule enforced in
   `PaperTradingEngine.open_position()` -- it applies to every
   strategy, not just TREND_FOLLOWING, same reasoning as
   `MAX_CONCURRENT_POSITIONS`.
2. **`POST_STOP_LOSS_COOLDOWN_MINUTES` (default 30).** A RELIANCE SELL
   stopped out, and the very next signal immediately flipped to a BUY
   at the same price/moment -- which also lost. `PaperTradingEngine`
   now tracks each symbol's most recent stop-loss close and blocks a
   new entry on that symbol until the cooldown passes. Also general,
   not TREND_FOLLOWING-specific. Purely in-memory -- does not survive a
   process restart, since `restore_position()` only rebuilds open
   positions, not closed-trade history. A known limitation, not a
   silent gap.
3. **TREND_FOLLOWING's `REWARD_MULTIPLE`: 2.0 -> 1.5.** Not one trade
   in the 0-for-10 sample ever reached target -- including a TCS trade
   that held the full trading day (the maximum possible runway) and
   still only covered ~24% of the distance to a 2x target. 1.5 still
   has positive expectancy above a 40% win rate.

**Deliberately not changed yet:** whether TREND_FOLLOWING's entry
itself fires too late. It requires ADX-confirmed regime + price above
EMA20 + Supertrend already flipped, all three at once -- three lagging
confirmations stacked together can mean the easy part of a move is
already over by the time all three agree. A tighter fix (e.g. trigger
on a *fresh* Supertrend flip rather than a sustained aligned state)
was considered and set aside for now: it risks colliding with the ADX
regime gate (a fresh flip often precedes ADX crossing its own
threshold) and redesigning it convincingly needs its own dedicated look
rather than being bundled into this pass. Revisit once the three
changes above have real-data results to look at.

`app/backtest/engine.py`'s two synthetic-data tests
(`test_sustained_uptrend_produces_mostly_winning_trend_following_trades`,
`test_uptrend_then_reversal_produces_a_losing_trade_and_positive_drawdown`)
were re-verified against the new code rather than assumed unaffected --
their expected trade/win/loss counts changed (see the tests' own
comments), and their synthetic candle start time moved from 14:30 IST
to 9:20 IST so a 120-bar series doesn't run into the new square-off
guard purely as a test-data artifact.

## 26. Everything here is defense in depth

Notice the repeated pattern: a limit enforced by a `pydantic` validator
at config load time (5% risk-per-trade in `.env` will refuse to boot),
re-checked again by the Risk Engine at evaluate time, with the agent
layer additionally refusing to run in a non-`PAPER` mode when execution
doesn't exist yet. That redundancy is deliberate. A single well-placed
`if` statement guarding ₹5,000 of real money is not considered
sufficient anywhere in this system.
