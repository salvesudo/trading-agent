"""Paper-safe orchestration for one trading decision cycle.

This module deliberately stops at risk evaluation. Market data, strategies,
paper fills, and broker execution will be connected in later phases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.config import TradingMode, settings
from app.risk.risk_engine import (
    AccountState,
    RiskDecision,
    RiskEngine,
    RiskVerdict,
    TradeCandidate,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class AgentCycleResult:
    """Outcome of evaluating one candidate without placing an order."""

    symbol: str
    verdict: RiskVerdict
    order_submitted: bool = False


class TradingAgent:
    """Coordinate candidate evaluation while execution is not yet available."""

    def __init__(self, account_state: AccountState | None = None) -> None:
        self.risk_engine = RiskEngine(account_state)

    def run_once(self, candidate: TradeCandidate) -> AgentCycleResult:
        """Evaluate a candidate and return a decision for the next phase.

        Even when LIVE is configured, this phase has no execution adapter and
        therefore never submits an order. A risk rejection remains the final
        result for the candidate.
        """
        verdict = self.risk_engine.evaluate(candidate)
        return AgentCycleResult(symbol=candidate.symbol, verdict=verdict)

    @staticmethod
    def execution_available() -> bool:
        """Report whether an order execution path exists in this phase."""
        return False


def build_paper_agent(
    account_state: AccountState | None = None,
    session: "Session | None" = None,
) -> TradingAgent:
    """Build the only supported agent mode in the project foundation.

    If `session` is given and `account_state` isn't, real AccountState is
    loaded from the database (app/risk/service.py, Phase 10) instead of
    falling back to AccountState()'s Phase-1 placeholder defaults. An
    explicit `account_state` always wins over `session` -- this is
    additive, not a change to the existing default (no-DB) behavior.
    """
    if settings.trading_mode != TradingMode.PAPER:
        raise RuntimeError(
            "Execution is not implemented yet. Keep TRADING_MODE=PAPER "
            "until the execution phase is complete."
        )
    if account_state is None and session is not None:
        from app.risk.service import load_account_state

        account_state = load_account_state(session)
    return TradingAgent(account_state)


__all__ = [
    "AgentCycleResult",
    "TradingAgent",
    "build_paper_agent",
]