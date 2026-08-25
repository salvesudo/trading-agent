# Paper-Trading Acceptance Criteria

> **Status: draft, owner review required.** This file is referenced by
> `README.md` and `app/core/config_check.py` as the gate that must be
> satisfied before `TRADING_MODE` is manually switched from `PAPER` to
> `LIVE`. No such criteria existed in the repo before this document, so
> the numbers below are a reasonable starting proposal derived from the
> risk parameters already hard-coded in `app/core/config.py`
> (1% max risk/trade, 2% max daily loss, ₹5,000 protected capital) —
> **not** a transcription of the owner's original master prompt. Tighten
> or loosen any threshold before treating this as a real gate; until the
> owner has reviewed and confirmed it, treat every number here as
> provisional.

No code in this repo enforces these criteria automatically. The switch
from `PAPER` to `LIVE` is, by design (see [`PRINCIPLES.md`](PRINCIPLES.md#9-paper-before-live-always)),
a manual, deliberate act — this document is what the owner checks
against before making that edit to `.env`, not a script that decides it
for them.

## 0. Prerequisite phases complete

Live testing is Phase 22 of 22. Before evaluating anything below, confirm
every earlier phase (per `README.md`'s build order) is implemented and
its own tests pass — in particular:

- [ ] Risk Engine wired to real position/P&L/reconciliation state from
      the database (not the Phase-1 `AccountState` placeholder defaults).
- [ ] Position reconciliation running and its mismatch check feeding
      `AccountState.system_healthy`.
- [ ] Monitoring/health checks operational, so a stale-data or downtime
      condition is actually detected, not just theoretically checked.
- [ ] Notifications working, so the owner is alerted in real time, not
      only discoverable by reading logs after the fact.
- [ ] Security hardening pass complete (credential handling, static IP
      whitelisting, `docs/STATIC_IP.md`).

## 1. Duration and sample size

- [ ] At least **20 trading days** of continuous paper trading in the
      exact runtime configuration intended for live use (same schedule,
      same strategies enabled, same risk parameters).
- [ ] At least **30 closed paper trades** in that window. Fewer than
      this is not a statistically meaningful sample for a system whose
      edge, if any, is thin by construction (small-capital, cost-aware).
- [ ] No period of the paper run was silently paused and resumed to
      cherry-pick a favorable window — the 20 days must be contiguous
      trading days, gaps only for market holidays.

## 2. Risk-control integrity

- [ ] Zero instances of realized risk on any single closed trade
      exceeding `MAX_RISK_PER_TRADE_PCT` (1% of equity at entry).
      A single breach here is a bug, not statistical noise, and must be
      root-caused and fixed before the clock on this criteria run
      restarts.
- [ ] Zero instances of the daily loss limit (`MAX_DAILY_LOSS_PCT`, 2%)
      being exceeded without the Risk Engine correctly halting further
      entries that day.
- [ ] The consecutive-loss hard limit correctly halted trading at least
      once if it was ever reached during the run (i.e. the control was
      exercised, not just present and untested).
- [ ] The kill switch (`STOP_TRADING`) was manually tested at least once
      during the paper run and confirmed to block all new positions
      immediately.

## 3. Financial outcome

- [ ] Max drawdown over the run stayed within **2× the daily loss limit**
      as a rolling peak-to-trough measure (i.e. ≤ 4% of starting equity
      for the default config) — small-capital survival, not just
      per-day discipline, is what's being verified.
- [ ] Capital at the end of the run is **not below the protected floor**
      (`PROTECTED_CAPITAL_INR`). A paper run that would have breached the
      floor is disqualifying regardless of any later recovery.
- [ ] Net result after estimated transaction costs is reported honestly
      even if negative. A negative but small, cost-explained result is a
      different finding than a strategy that loses because the EV check
      is broken — the acceptance decision should say which one this is.

## 4. Execution and reconciliation fidelity

- [ ] Paper fills used realistic assumptions (spread/slippage, not
      always-fill-at-signal-price) consistent with what
      `app/paper/` implements.
- [ ] Every paper position reconciled cleanly against the system's own
      order/position records with **zero unexplained mismatches**.
- [ ] No trade was placed, sized, or closed by any path other than
      Risk-Engine-approved instructions (spot-check the journal against
      the risk decisions logged for the same trades).

## 5. Operational readiness

- [ ] Static IP provisioned, whitelisted with FYERS, and confirmed
      stable for the full paper run (no unexpected IP changes that would
      have broken a live connection).
- [ ] Daily auth/2FA flow ran unattended (or with the owner's intended
      manual step) for the full duration without a single failure that
      would have left the system silently offline during market hours.
- [ ] Owner has read the trading journal for the full run, not just the
      summary statistics — qualitative review of a sample of both
      winning and losing trades.

## 6. Sign-off

- [ ] Owner has explicitly reviewed this checklist against the actual
      paper-run data (not from memory) and initials/dates it below.
- [ ] `MAX_RISK_PER_TRADE_PCT` and `MAX_DAILY_LOSS_PCT` for the live run
      are confirmed to be the same values used during the qualifying
      paper run, or any change is justified in writing here.

```
Reviewed by:            ______________________
Date:                    ______________________
Paper run window:        ______________________  to  ______________________
Decision:  [ ] Approved for LIVE   [ ] Not yet — see notes
Notes:
```

Only after every box above is checked and this section is signed does
the owner edit `TRADING_MODE=LIVE` in `.env`. No process in this repo
does that edit automatically or should ever be changed to do so.
