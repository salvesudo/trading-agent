# FYERS AI Trading Agent

Autonomous, AI-assisted intraday trading system for FYERS API v3.
Initial capital: ₹5,000. Survival > profit. See `docs/PRINCIPLES.md`.

## Status: Phase 2 — FYERS API v3 Integration

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
2. **FYERS API v3 integration (auth, order, quotes, WS)** ← you are here
3. Compliance checks (static IP, 2FA, permissions)
4. Market data service
5. Database (PostgreSQL schema)
6. Technical analysis engine
7. Market regime detection
8. News/sentiment engine
9. Strategy engine (trend/momentum/mean-reversion/breakout/VWAP/news)
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
