"""
Risk Engine — final authority over every trade.

Per the owner's spec (sections 4, 16, 17, 20, 22, 23, 47):
  - The AI/strategy layer generates candidate trades.
  - The Risk Engine approves or rejects them. Its decision is final.
  - The Execution Engine only ever executes trades this module approves.
  - No other module -- including the LLM advisory layer -- may bypass this.

This is a Phase-1 skeleton: real position/state lookups (open positions,
today's realized P&L, consecutive loss streak) will be wired to the
database in later phases. For now this module defines the contract and
the pure-logic risk math, which has no external dependencies and can be
unit-tested immediately.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from app.core.config import settings


class RiskDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT_RISK_TOO_HIGH = "REJECT_RISK_TOO_HIGH"
    REJECT_DAILY_LOSS_LIMIT = "REJECT_DAILY_LOSS_LIMIT"
    REJECT_CONSECUTIVE_LOSSES = "REJECT_CONSECUTIVE_LOSSES"
    REJECT_ZERO_QUANTITY = "REJECT_ZERO_QUANTITY"
    REJECT_KILL_SWITCH = "REJECT_KILL_SWITCH"
    REJECT_NO_STOP_LOSS = "REJECT_NO_STOP_LOSS"
    REJECT_NEGATIVE_EXPECTED_VALUE = "REJECT_NEGATIVE_EXPECTED_VALUE"
    REJECT_SYSTEM_HEALTH = "REJECT_SYSTEM_HEALTH"


@dataclass
class TradeCandidate:
    symbol: str
    side: str  # "BUY" | "SELL"
    entry_price: float
    stop_loss: float
    target: float
    account_equity: float
    estimated_costs: float  # brokerage + STT + GST + exchange + slippage etc.
    expected_win_prob: float | None = None  # from strategy/confidence engine


@dataclass
class AccountState:
    """Populated from the DB in later phases. Placeholder defaults for Phase 1."""
    today_realized_pnl: float = 0.0
    consecutive_losses: int = 0
    system_healthy: bool = True  # False if data stale, DB down, reconciliation mismatch, etc.


@dataclass
class RiskVerdict:
    decision: RiskDecision
    approved_quantity: int
    max_loss_inr: float
    risk_pct: float
    reason: str


class RiskEngine:
    def __init__(self, acct_state: AccountState | None = None):
        self.acct_state = acct_state or AccountState()

    def evaluate(self, trade: TradeCandidate) -> RiskVerdict:
        # 1. Kill switch / STOP_TRADING always wins, no exceptions.
        if settings.stop_trading:
            return self._reject(RiskDecision.REJECT_KILL_SWITCH,
                                 "STOP_TRADING is set. No new positions.")

        # 2. System health -- spec section 20/56/57: never trade while
        #    data/DB/reconciliation is unhealthy.
        if not self.acct_state.system_healthy:
            return self._reject(RiskDecision.REJECT_SYSTEM_HEALTH,
                                 "System health check failed (stale data, DB, "
                                 "or reconciliation issue). No new trades.")

        # 3. Stop loss must be defined and on the correct side of entry.
        if trade.stop_loss is None or trade.stop_loss == trade.entry_price:
            return self._reject(RiskDecision.REJECT_NO_STOP_LOSS,
                                 "No valid stop loss defined.")

        # 4. Daily loss limit -- spec section 22.
        max_daily_loss_inr = trade.account_equity * (settings.max_daily_loss_pct / 100)
        if -self.acct_state.today_realized_pnl >= max_daily_loss_inr:
            return self._reject(RiskDecision.REJECT_DAILY_LOSS_LIMIT,
                                 f"Daily loss limit reached "
                                 f"(₹{-self.acct_state.today_realized_pnl:.2f} >= "
                                 f"₹{max_daily_loss_inr:.2f}). Stop for the day.")

        # 5. Consecutive loss protection -- spec section 23.
        if self.acct_state.consecutive_losses >= settings.consecutive_loss_hard_limit:
            return self._reject(RiskDecision.REJECT_CONSECUTIVE_LOSSES,
                                 f"{self.acct_state.consecutive_losses} consecutive "
                                 "losses >= hard limit. Trading halted pending review.")

        # 6. Position sizing -- spec section 17.
        risk_amount_inr = trade.account_equity * (settings.max_risk_per_trade_pct / 100)
        stop_distance = abs(trade.entry_price - trade.stop_loss)
        if stop_distance <= 0:
            return self._reject(RiskDecision.REJECT_ZERO_QUANTITY,
                                 "Stop distance is zero or invalid.")

        raw_qty = risk_amount_inr / stop_distance
        quantity = math.floor(raw_qty)

        if quantity <= 0:
            return self._reject(RiskDecision.REJECT_ZERO_QUANTITY,
                                 "Minimum practical position size makes the 1% "
                                 "risk rule impossible at this stop distance.")

        # Verify actual max loss (incl. costs) doesn't exceed the risk budget.
        actual_max_loss = quantity * stop_distance + trade.estimated_costs
        while actual_max_loss > risk_amount_inr and quantity > 0:
            quantity -= 1
            actual_max_loss = quantity * stop_distance + trade.estimated_costs

        if quantity <= 0:
            return self._reject(RiskDecision.REJECT_ZERO_QUANTITY,
                                 "After accounting for transaction costs, no "
                                 "quantity satisfies the 1% risk rule.")

        # 7. Expected value sanity check (spec section 14/18): net of costs,
        #    reward at target must be positive and worth the risk taken.
        reward_distance = abs(trade.target - trade.entry_price)
        gross_reward = quantity * reward_distance
        net_reward = gross_reward - trade.estimated_costs
        if net_reward <= 0:
            return self._reject(RiskDecision.REJECT_NEGATIVE_EXPECTED_VALUE,
                                 "Target reward net of estimated costs is not positive.")

        risk_pct = (actual_max_loss / trade.account_equity) * 100

        return RiskVerdict(
            decision=RiskDecision.APPROVE,
            approved_quantity=quantity,
            max_loss_inr=round(actual_max_loss, 2),
            risk_pct=round(risk_pct, 3),
            reason=f"Approved: qty={quantity}, max_loss=₹{actual_max_loss:.2f} "
                   f"({risk_pct:.2f}% of equity), net_reward=₹{net_reward:.2f}.",
        )

    @staticmethod
    def _reject(decision: RiskDecision, reason: str) -> RiskVerdict:
        return RiskVerdict(
            decision=decision,
            approved_quantity=0,
            max_loss_inr=0.0,
            risk_pct=0.0,
            reason=reason,
        )
