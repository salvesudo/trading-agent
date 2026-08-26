import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest

from app.core.config import settings
from app.risk.capital_ledger import CapitalLedger, initial_ledger


def test_initial_ledger_uses_settings_defaults():
    ledger = initial_ledger()
    assert ledger.tradable_capital_inr == settings.initial_capital_inr
    assert ledger.protected_floor_inr == settings.protected_capital_inr
    assert ledger.reserved_capital_inr == 0.0


def test_initial_ledger_accepts_explicit_overrides():
    ledger = initial_ledger(initial_capital_inr=1000.0, protected_floor_inr=1000.0)
    assert ledger.tradable_capital_inr == 1000.0
    assert ledger.protected_floor_inr == 1000.0


def test_total_equity_is_tradable_plus_reserved():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=4000.0, reserved_capital_inr=800.0)
    assert ledger.total_equity_inr == 4800.0


def test_profitable_trade_splits_80_20_by_default():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=0.0)
    updated = ledger.apply_trade_outcome(realized_pnl=100.0)

    assert updated.reserved_capital_inr == pytest.approx(20.0)
    assert updated.tradable_capital_inr == pytest.approx(5080.0)
    assert updated.total_equity_inr == pytest.approx(5100.0)


def test_profitable_trade_respects_configured_reserve_pct():
    original = settings.profit_reserve_pct
    settings.profit_reserve_pct = 50.0
    try:
        ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=0.0)
        updated = ledger.apply_trade_outcome(realized_pnl=100.0)
        assert updated.reserved_capital_inr == pytest.approx(50.0)
        assert updated.tradable_capital_inr == pytest.approx(5050.0)
    finally:
        settings.profit_reserve_pct = original


def test_losing_trade_comes_entirely_out_of_tradable_capital():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=800.0)
    updated = ledger.apply_trade_outcome(realized_pnl=-150.0)

    assert updated.tradable_capital_inr == pytest.approx(4850.0)
    assert updated.reserved_capital_inr == 800.0  # untouched by the loss


def test_zero_pnl_trade_changes_nothing():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=200.0)
    updated = ledger.apply_trade_outcome(realized_pnl=0.0)
    assert updated.tradable_capital_inr == 5000.0
    assert updated.reserved_capital_inr == 200.0


def test_sequential_wins_and_losses_compound_correctly():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=0.0)
    ledger = ledger.apply_trade_outcome(100.0)   # +100 -> +80 tradable, +20 reserved
    ledger = ledger.apply_trade_outcome(-50.0)   # -50 tradable
    ledger = ledger.apply_trade_outcome(200.0)   # +200 -> +160 tradable, +40 reserved

    assert ledger.reserved_capital_inr == pytest.approx(60.0)
    assert ledger.tradable_capital_inr == pytest.approx(5000.0 + 80 - 50 + 160)


def test_apply_trade_outcome_does_not_mutate_original_ledger():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=5000.0, reserved_capital_inr=0.0)
    ledger.apply_trade_outcome(100.0)
    assert ledger.tradable_capital_inr == 5000.0  # original unchanged -- frozen/functional style
    assert ledger.reserved_capital_inr == 0.0


def test_breached_protected_floor_false_when_total_equity_at_or_above_floor():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=4500.0, reserved_capital_inr=800.0)
    assert ledger.total_equity_inr == 5300.0
    assert not ledger.breached_protected_floor


def test_breached_protected_floor_true_when_total_equity_below_floor():
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=4000.0, reserved_capital_inr=200.0)
    assert ledger.total_equity_inr == 4200.0
    assert ledger.breached_protected_floor


def test_reserve_counts_toward_floor_even_though_tradable_alone_is_below_it():
    # The specific case that proves the floor check uses TOTAL equity,
    # not tradable capital alone: tradable is under the floor by itself,
    # but the reserve brings the account's real total value back above it.
    ledger = CapitalLedger(protected_floor_inr=5000.0, tradable_capital_inr=4500.0, reserved_capital_inr=800.0)
    assert ledger.tradable_capital_inr < ledger.protected_floor_inr
    assert not ledger.breached_protected_floor
