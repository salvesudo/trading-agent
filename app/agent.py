"""Paper-safe orchestration for one trading decision cycle.

This module deliberately stops at risk evaluation. Market data, strategies,
paper fills, and broker execution will be connected in later phases.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import TradingMode, settings
from app.risk.risk_engine import (
    AccountState,
    RiskDecision,
    RiskEngine,
    RiskVerdict,
    TradeCandidate,
)


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


def build_paper_agent(account_state: AccountState | None = None) -> TradingAgent:
    """Build the only supported agent mode in the project foundation."""
    if settings.trading_mode != TradingMode.PAPER:
        raise RuntimeError(
            "Execution is not implemented yet. Keep TRADING_MODE=PAPER "
            "until the execution phase is complete."
        )
    return TradingAgent(account_state)


__all__ = [
    "AgentCycleResult",
    "TradingAgent",
    "build_paper_agent",
]