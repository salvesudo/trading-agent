"""
Converts a StrategySignal into a Risk-Engine-ready TradeCandidate --
Phase 9.

Deliberately a separate, explicit step: a StrategySignal only knows
about price levels and technical/news context, not the account's actual
equity or this trade's estimated transaction costs -- those come from
account state and cost estimation this module doesn't own. Same reason
app/broker/models.OrderRequest is deliberately not the same shape as
TradeCandidate: each layer only knows what's actually its job to know.
"""
from __future__ import annotations

from typing import Optional

from app.risk.risk_engine import TradeCandidate
from app.strategy.models import StrategySignal


def to_trade_candidate(
    signal: StrategySignal,
    account_equity: float,
    estimated_costs: float,
    expected_win_prob: Optional[float] = None,
) -> TradeCandidate:
    """`expected_win_prob` defaults to the signal's own `confidence` --
    a convenient stand-in, not a claim the two are the same statistical
    concept. The Risk Engine's current logic (app/risk/risk_engine.py)
    doesn't actually consume this field yet either way; pass an
    explicit value once something does and confidence isn't the right
    number for it."""
    return TradeCandidate(
        symbol=signal.symbol,
        side=signal.side,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target=signal.target,
        account_equity=account_equity,
        estimated_costs=estimated_costs,
        expected_win_prob=expected_win_prob if expected_win_prob is not None else signal.confidence,
    )


__all__ = ["to_trade_candidate"]
