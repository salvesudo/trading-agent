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

## 15. Everything here is defense in depth

Notice the repeated pattern: a limit enforced by a `pydantic` validator
at config load time (5% risk-per-trade in `.env` will refuse to boot),
re-checked again by the Risk Engine at evaluate time, with the agent
layer additionally refusing to run in a non-`PAPER` mode when execution
doesn't exist yet. That redundancy is deliberate. A single well-placed
`if` statement guarding ₹5,000 of real money is not considered
sufficient anywhere in this system.
