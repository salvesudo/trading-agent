"""
Real FYERS transaction cost estimation -- added 2026-09-06.

Every backtest before this used a flat, guessed `--costs` value (₹15
per trade, applied identically regardless of trade size). Pooling
results across all real-data backtests run so far revealed why that
mattered: net P&L was -₹832.77 across 65 trades, but *gross* P&L (net
+ the flat costs assumed) was +₹142.23 -- the underlying signals may
have real, if marginal, edge, and a flat cost assumption was the thing
actually deciding whether the reported result was a profit or a loss.
Getting the cost number right is not a cosmetic detail here; it's the
deciding variable.

Source: FYERS' own published Standard-plan fee schedule, confirmed
against the owner's actual account tier (2026-09-06) --
https://fyers.in/pricing, https://fyers.in/charges-list,
https://support.fyers.in/portal/en/kb/articles/what-are-the-statutory-charges-on-trades-at-fyers-stt-gst-sebi-turnover-fee-ipft-etc :
  - Brokerage: min(₹20, 0.03% of order value) per executed order
    (FYERS Prime subscribers get a ₹15 cap instead -- see `prime`).
  - STT (Securities Transaction Tax): 0.025% on the SELL leg only,
    for intraday equity.
  - Exchange transaction charges (NSE): 0.0030699% per leg.
  - GST: 18% on brokerage + exchange charges only -- NOT on STT, SEBI
    fee, or stamp duty.
  - SEBI turnover fee: ₹10 per crore (both legs).
  - Stamp duty: 0.003% on the BUY leg only.

For the position sizes this system actually trades (1% risk on a
₹5,000-ish account -- notional per leg usually ₹1,000-15,000), the
0.03%/₹20 brokerage comparison almost always resolves to the
percentage, not the ₹20 cap: a ₹20 order value would need to exceed
roughly ₹66,667 before the flat cap ever binds. That's *why* a flat
₹15-20 "round number" per trade was a rough approximation rather than
a real model -- it overstates cost on the smallest trades (a 1-share,
₹1,200 trade's real round-trip cost is under ₹2) and understates it on
the largest ones.
"""
from __future__ import annotations

import math

from app.core.config import settings

BROKERAGE_PCT = 0.0003  # 0.03% per executed order
STANDARD_BROKERAGE_CAP_INR = 20.0
PRIME_BROKERAGE_CAP_INR = 15.0
STT_SELL_PCT = 0.00025  # 0.025%, intraday, sell leg only
EXCHANGE_TXN_PCT = 0.00030699 / 100.0  # NSE 0.0030699%, both legs -- see module docstring
GST_RATE = 0.18  # on brokerage + exchange charges only
SEBI_FEE_PCT = 0.0000001  # ₹10/crore, both legs
STAMP_DUTY_BUY_PCT = 0.00003  # 0.003%, buy leg only


def round_trip_cost(buy_price: float, sell_price: float, quantity: int, prime: bool = False) -> float:
    """Real (not flat-guessed) round-trip cost for one BUY + SELL of
    `quantity` shares -- brokerage (both legs, capped) + STT (sell) +
    exchange charges (both legs) + GST (on brokerage+exchange only) +
    SEBI fee (both legs) + stamp duty (buy). Returns 0.0 for a
    non-positive quantity rather than raising -- a candidate that never
    gets sized shouldn't need this to guard against it separately.

    `prime`: pass True only if the account is confirmed to be on FYERS
    Prime (₹15/order cap) -- defaults to False (Standard, ₹20/order
    cap), which is what this project's account is actually on
    (confirmed 2026-09-06, not assumed)."""
    if quantity <= 0:
        return 0.0
    cap = PRIME_BROKERAGE_CAP_INR if prime else STANDARD_BROKERAGE_CAP_INR

    buy_notional = buy_price * quantity
    sell_notional = sell_price * quantity

    brokerage_buy = min(cap, buy_notional * BROKERAGE_PCT)
    brokerage_sell = min(cap, sell_notional * BROKERAGE_PCT)
    exchange_buy = buy_notional * EXCHANGE_TXN_PCT
    exchange_sell = sell_notional * EXCHANGE_TXN_PCT
    stt_sell = sell_notional * STT_SELL_PCT
    stamp_buy = buy_notional * STAMP_DUTY_BUY_PCT
    sebi_fee = (buy_notional + sell_notional) * SEBI_FEE_PCT
    gst = GST_RATE * (brokerage_buy + brokerage_sell + exchange_buy + exchange_sell)

    return brokerage_buy + brokerage_sell + exchange_buy + exchange_sell + stt_sell + stamp_buy + sebi_fee + gst


def estimate_intraday_costs(
    entry_price: float,
    stop_loss: float,
    account_equity: float,
    risk_pct: float | None = None,
    prime: bool | None = None,
) -> float:
    """Convenience for the one place this actually gets used
    (app.strategy.candidate.to_trade_candidate / app.backtest.engine):
    at the point a cost estimate is needed, the Risk Engine hasn't sized
    the trade yet -- estimated_costs is itself one of its sizing
    inputs. This approximates the quantity the same way
    app.risk.risk_engine.RiskEngine does before its own cost-aware
    refinement loop (risk_amount / stop_distance, floored) -- close
    enough for an upfront estimate; the Risk Engine's final quantity
    may end up a share or two smaller once it accounts for costs
    itself, which is a second-order correction on top of this, not a
    different estimate. The exit price isn't known yet either, so this
    uses `entry_price` for both legs -- a reasonable approximation
    since the fee components are all roughly proportional to price
    level and a single trade's price move is typically a small
    percentage of it."""
    risk_pct = risk_pct if risk_pct is not None else settings.max_risk_per_trade_pct
    prime = prime if prime is not None else settings.fyers_prime_subscription
    risk_amount = account_equity * (risk_pct / 100.0)
    stop_distance = abs(entry_price - stop_loss)
    if stop_distance <= 0:
        return 0.0
    quantity = math.floor(risk_amount / stop_distance)
    return round_trip_cost(entry_price, entry_price, quantity, prime=prime)


__all__ = ["round_trip_cost", "estimate_intraday_costs"]
