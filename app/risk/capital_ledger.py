"""
Capital ledger -- owner-directed profit-reserve policy, added after
Phase 9.

Tracks tradable vs. reserved capital across the account's lifetime.
After every trade that closes in profit, `PROFIT_RESERVE_PCT` (default
20%, see app/core/config.py) of that profit is swept into a reserved
balance that is never risked again; the rest stays in tradable capital
and compounds. A loss reduces tradable capital by its full amount --
there is no reserve interaction on a loss. The reserve exists to lock in
gains, not to cushion losses; letting a loss eat into it would defeat
the entire point of having one.

This is deliberately separate from app/risk/risk_engine.py's
AccountState (today's realized P&L / consecutive losses / system
health) -- AccountState is about *today*; this ledger is about capital
composition across the account's entire life.

**The Risk Engine's position sizing must be given `tradable_capital_inr`
as `TradeCandidate.account_equity`, never `total_equity_inr`.** Handing
it total equity would silently let the reserve get risked again the
next time a candidate is sized, which is exactly the outcome this
ledger exists to prevent. See app/strategy/candidate.py.

Not wired into the live agent loop yet -- same status as
app/risk/risk_engine.py's AccountState (docs/PRINCIPLES.md section 15):
this becomes load-bearing once Phase 11 (paper trading engine) has an
actual persistent loop to update it after every closed trade.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class CapitalLedger:
    protected_floor_inr: float  # the account's absolute floor (spec section 2, PROTECTED_CAPITAL_INR)
    tradable_capital_inr: float  # what Risk Engine position sizing is actually based on
    reserved_capital_inr: float = 0.0  # cumulative swept-profit reserve; never re-risked

    @property
    def total_equity_inr(self) -> float:
        """Real money still in the account -- tradable + reserved. The
        reserve is an untouchable buffer, not a withdrawal (per the
        owner's choice), so it still counts toward the account's total
        value even though it's excluded from risk sizing."""
        return self.tradable_capital_inr + self.reserved_capital_inr

    @property
    def breached_protected_floor(self) -> bool:
        """True once *total* equity has fallen below the protected
        floor. Checked against total, not tradable alone -- the floor is
        about the account's overall survival, not the trading
        sub-ledger, so reserved capital correctly counts toward staying
        above it."""
        return self.total_equity_inr < self.protected_floor_inr

    def apply_trade_outcome(self, realized_pnl: float) -> "CapitalLedger":
        """Return a new ledger reflecting one closed trade's P&L.

        A profit is split between tradable and reserved capital per
        `settings.profit_reserve_pct`. A loss (realized_pnl <= 0) comes
        entirely out of tradable capital.
        """
        if realized_pnl > 0:
            reserve_fraction = settings.profit_reserve_pct / 100.0
            reserved_delta = realized_pnl * reserve_fraction
            tradable_delta = realized_pnl - reserved_delta
            return CapitalLedger(
                protected_floor_inr=self.protected_floor_inr,
                tradable_capital_inr=self.tradable_capital_inr + tradable_delta,
                reserved_capital_inr=self.reserved_capital_inr + reserved_delta,
            )
        return CapitalLedger(
            protected_floor_inr=self.protected_floor_inr,
            tradable_capital_inr=self.tradable_capital_inr + realized_pnl,
            reserved_capital_inr=self.reserved_capital_inr,
        )


def initial_ledger(
    initial_capital_inr: float = None, protected_floor_inr: float = None
) -> CapitalLedger:
    """Build the starting ledger. Defaults come from settings
    (INITIAL_CAPITAL_INR / PROTECTED_CAPITAL_INR) so this matches
    whatever the rest of the app is configured with unless overridden
    (e.g. in a test)."""
    return CapitalLedger(
        protected_floor_inr=protected_floor_inr if protected_floor_inr is not None else settings.protected_capital_inr,
        tradable_capital_inr=initial_capital_inr if initial_capital_inr is not None else settings.initial_capital_inr,
        reserved_capital_inr=0.0,
    )


__all__ = ["CapitalLedger", "initial_ledger"]
