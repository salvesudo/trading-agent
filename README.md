# FYERS AI Trading Agent

Autonomous, AI-assisted intraday trading system for FYERS API v3.
Initial capital: ₹5,000. Survival > profit. See `docs/PRINCIPLES.md`.

## Status: Phase 9 — Strategy Engine

This repo is being built in the exact phase order specified by the owner's
master prompt (Phase 1 → Phase 22). Nothing in this repo places live orders.
`TRADING_MODE` defaults to `PAPER` and there is no code path that flips it
automatically — that switch is a manual, deliberate act by the owner after
paper-trading acceptance criteria are met (see `docs/ACCEPTANCE_CRITERIA.md`).

Phase 2 adds `app/broker/`: a typed FYERS v3 client (auth, quotes, orders,
WebSocket market data and order updates). Every call that can create,
modify, or cancel a live order is refused unless `TRADING_MODE=LIVE` — a
guard independent of the Risk Engine and the agent's own PAPER-only check
(defense in depth, see `docs/PRINCIPLES.md` section 12). Read-only calls
(quotes, profile, positions, funds) work in PAPER mode, since later phases
need them without placing anything.

**Live-verified (2026-08-25):** the owner ran the full daily login flow
(`app/broker/callback_server.py`) against the real FYERS API from their own
EC2 instance — login, 2FA, redirect capture, code exchange, and real
`profile()`, `quotes()`, and `funds()` calls all succeeded end-to-end
(`Quote` field mapping confirmed correct against a live response). Order
placement/modify/cancel and both WebSocket clients remain unverified
against live FYERS endpoints.

Phase 3 adds `app/security/compliance.py` and the
`python -m app.security.compliance_check` script: static-IP verification
(fetches this machine's outbound IP and compares it to `FYERS_STATIC_IP`),
session/token freshness (a real `profile()` call — there's no other
reliable way to know today's token still works), and an explicit
`OWNER_CONFIRMED_ALGO_PERMISSIONS` acknowledgment for the one thing code
genuinely cannot verify itself: current SEBI algo-trading / FYERS
permission requirements for this account. These results are **advisory
only** in this phase — nothing yet blocks `LIVE` mode automatically based
on them; that wiring is later-phase work, same as `AccountState` in the
Risk Engine (see `docs/PRINCIPLES.md`).

**Live-verified (2026-08-25):** the owner ran `compliance_check` on their
EC2 instance — all three checks passed against the real FYERS API: outbound
IP matched `FYERS_STATIC_IP`, today's token authenticated via a real
`profile()` call, and `OWNER_CONFIRMED_ALGO_PERMISSIONS` was set after
confirming with FYERS. Phase 3 is confirmed working end-to-end, not just
unit-tested.

This phase also fixed a real bug surfaced while testing it: `pydantic-settings`
silently reads a trailing `# comment` as part of a blank `.env` value
instead of stripping it, which had left `FYERS_ACCESS_TOKEN` holding
literal comment text. `.env.example` was reformatted (no more trailing
inline comments) and `Settings` now rejects any config value containing
`#` at startup, so this can't silently recur.

Phase 4 adds `app/data/`: historical OHLC fetch (`app/data/history.py`,
via a new `FyersClient.history()`), a pure-logic tick→candle aggregator
(`app/data/candle_builder.py` — correctly diffs FYERS' *cumulative* daily
volume field into per-candle volume, not just copying it), an in-memory
`MarketDataStore` (latest quote + bounded candle history per symbol/
timeframe), and `MarketDataService` tying historical seeding + the Phase 2
WebSocket stream + the store together. Read-only by construction — this
module has no import path to anything that places an order. Not
exercised against a live WS tick stream from this environment; the WS
message parsing is deliberately defensive (drops anything it doesn't
recognize rather than raising) for exactly that reason.

**Live-verified (2026-08-25):** the owner ran `MarketDataService.seed_history()`
on their EC2 instance — a real call to FYERS' `/history` endpoint returned
750 one-minute `NSE:RELIANCE-EQ` candles, correctly parsed into typed
`Candle` objects (epoch timestamps, OHLCV all sane). Historical fetch is
confirmed working end-to-end. `start_streaming()` (the live WebSocket tick
path, and the volume-diffing in `candle_builder.py` operating on real
cumulative-volume ticks) remains unverified against live FYERS endpoints.

Phase 5 adds `app/db/`: SQLAlchemy models (`account_state`,
`risk_evaluations`, `compliance_checks`, `candles`) and a repository layer
(`app/db/repository.py`) that's the only place translating between ORM
rows and the dataclasses the rest of the app already uses and tests
(`AccountState`, `ComplianceReport`, `Candle`). Postgres is the intended
production database; a `sqlite:///` URL also works against the same
models for local dev/tests (every column type is dialect-generic).
Migrations live in `migrations/` (Alembic), reading `DATABASE_URL` from
the same `.env`/`settings` source of truth as everything else — the
initial migration was generated and verified (upgrade **and** downgrade)
against a throwaway local SQLite database, since there's no live Postgres
reachable from this environment.

Repository functions exist and are tested (28 new tests, using in-memory
SQLite), but are **not wired into the live agent loop or compliance_check
script yet** — `AccountState` in the Risk Engine still uses its Phase-1
defaults unless a caller explicitly loads from DB. That wiring belongs to
Phase 11 (paper trading engine), once there's an actual persistent trading
loop for "today's realized P&L" and "consecutive losses" to accumulate
across, rather than one-off CLI evaluations. This phase also caught and
fixed a real bug: SQLite's `DateTime(timezone=True)` doesn't actually
preserve `tzinfo` across a round trip (unlike Postgres) — candle
timestamps read back from a SQLite-backed session came back naive, which
silently broke both equality comparisons and duplicate-detection on
re-seeding. `app/db/repository.py` now normalizes every timestamp read
back from the DB to UTC-aware, a no-op for Postgres and a real fix for
SQLite.

Phase 6 adds `app/analysis/indicators.py`: EMA, RSI, MACD, ATR, ADX, and
Bollinger Bands, all thin typed wrappers over the `ta` library (whose
exact method signatures were checked against the installed version before
writing this, not assumed), plus a hand-rolled Supertrend since `ta`
doesn't include one. Every function takes a `list[Candle]` and returns
plain floats/lists — callers never touch pandas, and this module never
imports `app/broker` or `app/data.store`, only `app/data/models.py`'s
`Candle`. All functions raise `InsufficientDataError` rather than
silently returning a mostly-NaN series when given fewer candles than a
window needs. Advisory only, same as everything upstream of the Risk
Engine — nothing here decides whether to trade (spec section 47).

18 new tests (114 total), including golden-value checks where the math is
simple enough to hand-verify independently (EMA of a constant series
equals that constant; ATR converges to a fixed true range) and directional
sanity checks for the rest. **Supertrend specifically has not been
cross-checked against another reference implementation or a live chart**
— only against its own directional logic (ends up below price in a clear
uptrend, above price in a clear downtrend) — since it's hand-rolled rather
than from an established library, spot-check its actual values before
trusting it in a strategy.

Phase 7 adds `app/regime/detector.py`: classifies recent price action
into a trend state (`TRENDING_UP` / `TRENDING_DOWN` / `RANGING`, from
ADX + directional index) and a volatility state (`LOW` / `NORMAL` /
`HIGH`), built entirely on Phase 6's indicators. Volatility is classified
by **percentile rank within its own recent history**, not a fixed
absolute cutoff — "high volatility" means something different for a ₹50
stock than for NIFTY, so a hardcoded threshold would misclassify
whichever instruments it wasn't tuned for. The ADX trend threshold (25)
and volatility percentile cutoffs (33rd/67th) are defensible starting
points, not calibrated against real trading outcomes — treat them like
`docs/ACCEPTANCE_CRITERIA.md`'s numbers: provisional until reviewed.

12 new tests (126 total). One caught a real subtlety worth flagging: the
`ta` library's `AverageTrueRange` leaves its warm-up period as literal
`0.0`, not `NaN` — checked against the installed source before writing
this, not assumed. Left uncorrected, those fake "zero volatility" entries
would have inflated every real reading's percentile rank (extra entries
that always count as "below," pushing genuinely normal volatility toward
a false HIGH classification). `detect_regime` excludes them from the
distribution; a test computes both the buggy and correct percentile from
the same data and confirms the code matches the correct one.

Phase 8 adds `app/news/`: free RSS feeds from four Indian financial
publishers (Moneycontrol, Economic Times, LiveMint, Business Standard —
`app/news/feeds.py`), a hand-rolled RSS 2.0 parser (`app/news/rss_client.py`,
stdlib `xml.etree.ElementTree` + `email.utils` — no new dependency,
deliberately, since every feed was confirmed to be standard RSS 2.0
before writing this rather than reached for a general-purpose feed
library up front), simple lexicon-based sentiment scoring
(`app/news/sentiment.py`), and `app/news/aggregator.py` tying fetch +
keyword filtering + scoring together. Advisory only, same as every
analysis-layer module here — nothing decides whether to trade.

**Live-verified (2026-08-25) — from this environment itself, not just
by the owner:** unlike every FYERS-dependent phase, public RSS feeds
need no credentials or whitelisted IP, so `fetch_all()` was run for real
here and returned 124 genuine, current news items across all four
sources, correctly merged and sorted by actual publish time, with
keyword filtering and sentiment scoring both exercised on live data (the
sentiment output is noisy, as documented — a crude keyword heuristic,
not a claim of accuracy).

22 new tests (148 total). Parser tests use fixtures faithful to each
feed's real, confirmed structure (CDATA usage, RFC-822 dates) rather
than invented XML shapes.

Phase 9 adds `app/strategy/`: six strategies (trend-following, momentum,
mean-reversion, breakout, VWAP, news), each a pure function of a
`StrategyContext` (candles + regime + pre-filtered news) built entirely
on Phases 4/6/7/8. `app/analysis/indicators.py` gained a session-aware
VWAP (resets each trading day in IST — `ta` has no VWAP at all) since the
VWAP strategy needed it. Every strategy returns a `StrategySignal`, never
places an order, and never bypasses the Risk Engine — converting a signal
into an actual `TradeCandidate` (`app/strategy/candidate.py`) is a
separate, explicit step, same reason `app/broker/models.OrderRequest`
isn't the same shape as `TradeCandidate` either. `StrategyEngine.
generate_signals()` runs all six and collects whatever fires;
`select_best_signal()` is a simple confidence-based placeholder, not a
claim of real arbitration — that's likely Phase 13's job.

None of the six strategies' specific rules (ADX/EMA/Supertrend gates,
RSI/MACD crossings, Bollinger squeeze thresholds, VWAP pullback
tolerance, news sentiment cutoffs) have been backtested or calibrated —
they're explicit, documented starting rules, same honesty standard as
Phase 7's regime thresholds (see `docs/PRINCIPLES.md`).

39 new tests (197 total). Exact trigger conditions for RSI/MACD crossings,
Bollinger squeezes, and VWAP pullbacks were found by iterating against
the real indicator code with a script, not by writing synthetic data and
hoping it happened to trigger the right branch — the same discipline
applied to verifying the FYERS SDK and `ta` library elsewhere in this
project, just applied to this project's own code instead of a
third-party one.

**Live-verified (2026-08-25) — the first full end-to-end pipeline run,
from this environment:** real live news (Phase 8) + synthetic candles in
a clear uptrend (this environment has no FYERS credentials for real
candles) were assembled into a `StrategyContext`, run through all six
strategies (`TREND_FOLLOWING` fired), converted to a `TradeCandidate`,
and evaluated by the real `RiskEngine` — result: `APPROVE, qty=5,
max_loss=₹45.00 (0.90% of equity)`. This confirms Phases 1, 4, 6, 7, 8,
and 9 genuinely compose, not just that each passes its own tests in
isolation.

## What this environment can and can't do

This codebase was generated in a sandboxed dev environment with **no live
network access** and **no FYERS credentials**. That means:

- All FYERS API integration code is written against the documented v3 REST/WS
  contract, but has **not been exercised against the live API** from here.
- Static IP provisioning, FYERS IP whitelisting, and daily 2FA/auth flows
  must be completed by you, on your own server, before Phase 2 testing.
- You must supply `FYERS_APP_ID`, `FYERS_SECRET_ID`, `FYERS_REDIRECT_URI` etc.
  via `.env` (never commit this file). Nothing here hardcodes credentials.
- Before any live order is placed, you are responsible for independently
  verifying current FYERS API v3 behavior, rate limits, and SEBI algo-trading
  requirements against FYERS' own current documentation — these change over
  time and this code should not be trusted as the source of truth for them.

## Build order (matches owner spec section 63)

1. **Project foundation** ✅
2. **FYERS API v3 integration (auth, order, quotes, WS)** ✅
3. **Compliance checks (static IP, 2FA, permissions)** ✅
4. **Market data service** ✅
5. **Database (PostgreSQL schema)** ✅
6. **Technical analysis engine** ✅
7. **Market regime detection** ✅
8. **News/sentiment engine** ✅
9. **Strategy engine (trend/momentum/mean-reversion/breakout/VWAP/news)** ← you are here
10. Risk engine ← skeleton included now, since it has veto power over every
    later phase and everything else must be built to respect it
11. Paper trading engine
12. Backtesting engine
13. AI decision engine (LLM layer, advisory only)
14. Execution engine
15. Position reconciliation
16. Trading journal
17. Notifications (email/SMS/WhatsApp)
18. Dashboard
19. Monitoring/health checks
20. Security hardening
21. Production deployment (Docker, systemd, static IP, HTTPS)
22. Small-capital live testing (₹5,000, 1% risk cap)

Each phase should be implemented, tested, and validated before the next
begins — no skipping ahead to live execution.

## Quick start (dev machine, paper mode only)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own values, never commit this
python -m app.core.config_check   # sanity-checks env vars, prints nothing live
# Evaluate one candidate through the risk engine; this never submits an order.
python -m app --symbol RELIANCE --side BUY --entry 2500 --stop 2480 --target 2560 --equity 5000 --costs 15
```

The command above is the initial agent loop: it accepts a candidate, applies
the risk veto, and reports the approved quantity. Market data, paper fills,
and execution adapters are intentionally not connected yet.

## FYERS daily login (Phase 2, requires your own credentials + static IP)

```bash
# Fill in FYERS_APP_ID / FYERS_SECRET_ID / FYERS_REDIRECT_URI in .env first.
python -m app.broker.auth
```

Prints a login URL — open it, complete FYERS login + 2FA, then paste the
redirect URL (or just the `auth_code` in it) back into the prompt. The
resulting access token is written to `.env`; it expires at the end of the
trading day, so this needs to run again each morning before trading starts.
This has not been run against the live FYERS API from this environment —
see "What this environment can and can't do" above.

If `FYERS_REDIRECT_URI` points at a server you actually control (e.g. an
EC2 instance with the port open), `python -m app.broker.callback_server`
does the same thing without the copy-paste step: it listens for the
redirect, captures `auth_code` automatically, and writes the token itself.

## Compliance check (Phase 3, contacts the network)

```bash
python -m app.security.compliance_check
```

Run this after the daily login, before trading. Unlike `config_check`, it
genuinely contacts the network — a public IP-lookup service and the real
FYERS API — to check your static IP actually matches what's whitelisted
and today's token actually still works. Results are advisory only right
now (see `docs/PRINCIPLES.md`); nothing blocks `LIVE` mode based on them
yet.

## Market data (Phase 4)

```python
from app.data.service import MarketDataService
from app.data.models import Timeframe

service = MarketDataService()  # uses FyersClient.from_settings() internally
service.seed_history("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")
service.track("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
# service.start_streaming(["NSE:RELIANCE-EQ"])  # blocks; run in its own thread/process

print(service.store.latest_quote("NSE:RELIANCE-EQ"))
print(service.store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE))
```

`seed_history` (a real REST call to FYERS' `/history` endpoint) is
live-verified — see the Phase 4 status note above. `start_streaming` (a
real WebSocket connection) has **not** been exercised against a live tick
stream yet — only against fakes in the test suite. The WS message parsing
in particular is defensive by design (drops anything it doesn't recognize
rather than raising) because of that.

## Database (Phase 5, needs a real Postgres — or SQLite for local dev)

```bash
# DATABASE_URL in .env: postgresql://user:pass@host:5432/dbname for real
# use, or sqlite:///./dev.db to try this out without a Postgres server.
python -m alembic upgrade head   # creates every table via migrations/
```

```python
from datetime import date

from app.db.base import build_sessionmaker
from app.db import repository
from app.risk.risk_engine import AccountState

Session = build_sessionmaker()
with Session() as session:
    repository.save_account_state(session, AccountState(consecutive_losses=1), trade_date=date.today())
    session.commit()
    print(repository.load_account_state(session, trade_date=date.today()))
```

Not wired into the live agent loop yet — see the Phase 5 note above.
`python -m alembic upgrade head` has been verified (upgrade **and**
downgrade) against a throwaway local SQLite database from this
environment; it has **not** been run against a real Postgres server —
that needs your own Postgres instance (local, Docker, or on the EC2 box)
with `DATABASE_URL` pointed at it.

## Technical indicators (Phase 6)

```python
from app.analysis import indicators
from app.data.service import MarketDataService
from app.data.models import Timeframe

service = MarketDataService()
service.seed_history("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")
candles = service.store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)

print("EMA20:", indicators.ema(candles, window=20)[-1])
print("RSI14:", indicators.rsi(candles, window=14)[-1])
print("ATR14:", indicators.atr(candles, window=14)[-1])
st = indicators.supertrend(candles)
print("Supertrend:", st.value[-1], "direction:", st.direction[-1])
```

Pure functions of whatever candles you hand them — no network, no
broker/DB dependency. EMA/RSI/MACD/ATR/ADX/Bollinger Bands come from the
`ta` library; Supertrend is hand-rolled and, unlike the rest, has not
been cross-checked against another reference implementation.

## Market regime (Phase 7)

```python
from app.regime.detector import detect_regime

snapshot = detect_regime(candles)  # same candles as above
print(snapshot.trend, snapshot.volatility)
print(f"ADX={snapshot.adx:.1f} +DI={snapshot.plus_di:.1f} -DI={snapshot.minus_di:.1f}")
print(f"ATR%={snapshot.atr_pct:.2f} (percentile {snapshot.atr_pct_percentile:.0f})")
```

Trend threshold (ADX ≥ 25) and volatility percentile cutoffs (33rd/67th)
are defensible starting points, not calibrated against real trading
outcomes for the instruments this will actually trade — see
`docs/PRINCIPLES.md` section 17.

## News/sentiment (Phase 8, no credentials needed — public RSS feeds)

```python
from app.news.aggregator import fetch_all, filter_by_keyword, score_all

items = fetch_all()  # all 4 known feeds; one source failing doesn't block the rest
reliance_news = filter_by_keyword(items, "Reliance")
scored = score_all(items[:10])
for s in scored:
    print(s.sentiment.sentiment.value, s.sentiment.score, s.item.title)
```

Genuinely live-tested from this environment (see the Phase 8 status note
above) — the one phase so far that didn't need your FYERS credentials or
EC2 setup to verify, since these are public feeds. Sentiment is a simple
keyword-count heuristic (`app/news/sentiment.py`), not an ML model or an
LLM — expect it to be noisy; it's a starting signal, not a claim of
accuracy.

## Strategy engine (Phase 9)

```python
from app.strategy.models import StrategyContext
from app.strategy.engine import generate_signals, select_best_signal
from app.strategy.candidate import to_trade_candidate
from app.risk.risk_engine import RiskEngine
from app.regime.detector import detect_regime
from app.news.aggregator import fetch_all, filter_by_keyword

# candles = MarketDataService().seed_history(...) then .store.candles(...)  (Phase 4)
context = StrategyContext(
    symbol="NSE:RELIANCE-EQ",
    candles=candles,
    regime=detect_regime(candles),
    news_items=filter_by_keyword(fetch_all(), "Reliance"),
)

signals = generate_signals(context)          # every strategy that fired
best = select_best_signal(signals)            # highest confidence -- a placeholder, not real arbitration
if best:
    candidate = to_trade_candidate(best, account_equity=5000.0, estimated_costs=15.0)
    verdict = RiskEngine().evaluate(candidate)  # final authority, always
    print(verdict.decision, verdict.reason)
```

Six strategies (trend/momentum/mean-reversion/breakout/VWAP/news), none
backtested or calibrated — explicit starting rules, not a claim of edge
(see `docs/PRINCIPLES.md`). **Live-verified (2026-08-25):** this exact
pipeline ran here with real live news and synthetic candles, producing a
real `RiskEngine` `APPROVE` — see the Phase 9 status note above for the
full result.
