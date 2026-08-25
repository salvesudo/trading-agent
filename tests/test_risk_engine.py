import os
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

from app.agent import TradingAgent, build_paper_agent
from app.risk.risk_engine import RiskEngine, TradeCandidate, AccountState, RiskDecision


def make_trade(**overrides):
    base = dict(
        symbol="RELIANCE",
        side="BUY",
        entry_price=2500.0,
        stop_loss=2480.0,   # ₹20 stop distance
        target=2560.0,      # ₹60 reward distance
        account_equity=5000.0,
        estimated_costs=15.0,
    )
    base.update(overrides)
    return TradeCandidate(**base)


def test_normal_trade_approved_within_1pct_risk():
    engine = RiskEngine()
    verdict = engine.evaluate(make_trade())
    assert verdict.decision == RiskDecision.APPROVE
    # 1% of ₹5000 = ₹50 risk budget; stop distance ₹20 -> raw qty 2 (~₹40+costs)
    assert verdict.approved_quantity >= 1
    assert verdict.risk_pct <= 1.0


def test_kill_switch_blocks_everything():
    from app.core.config import settings
    settings.stop_trading = True
    try:
        engine = RiskEngine()
        verdict = engine.evaluate(make_trade())
        assert verdict.decision == RiskDecision.REJECT_KILL_SWITCH
        assert verdict.approved_quantity == 0
    finally:
        settings.stop_trading = False


def test_no_stop_loss_rejected():
    engine = RiskEngine()
    verdict = engine.evaluate(make_trade(stop_loss=2500.0))  # equals entry
    assert verdict.decision == RiskDecision.REJECT_NO_STOP_LOSS


def test_daily_loss_limit_blocks_new_trades():
    # 2% of ₹5000 = ₹100 daily loss limit; already down ₹100+
    acct = AccountState(today_realized_pnl=-105.0)
    engine = RiskEngine(acct)
    verdict = engine.evaluate(make_trade())
    assert verdict.decision == RiskDecision.REJECT_DAILY_LOSS_LIMIT


def test_consecutive_loss_hard_limit_blocks_new_trades():
    acct = AccountState(consecutive_losses=5)
    engine = RiskEngine(acct)
    verdict = engine.evaluate(make_trade())
    assert verdict.decision == RiskDecision.REJECT_CONSECUTIVE_LOSSES


def test_unhealthy_system_blocks_new_trades():
    acct = AccountState(system_healthy=False)
    engine = RiskEngine(acct)
    verdict = engine.evaluate(make_trade())
    assert verdict.decision == RiskDecision.REJECT_SYSTEM_HEALTH


def test_wide_stop_that_forces_zero_quantity_is_rejected_not_undersized():
    # Stop distance so wide that even qty=1 blows the ₹50 risk budget.
    engine = RiskEngine()
    verdict = engine.evaluate(make_trade(stop_loss=2000.0))  # ₹500 stop distance
    assert verdict.decision == RiskDecision.REJECT_ZERO_QUANTITY
    assert verdict.approved_quantity == 0


def test_negative_expected_value_rejected():
    # Larger equity so quantity survives the sizing step, but target is
    # close enough to entry that costs eat the entire reward.
    engine = RiskEngine()
    verdict = engine.evaluate(make_trade(
        account_equity=50000.0, target=2501.0, estimated_costs=50.0
    ))
    assert verdict.decision == RiskDecision.REJECT_NEGATIVE_EXPECTED_VALUE


def test_costs_that_exceed_risk_budget_are_rejected_as_zero_qty_not_silently_undersized():
    # If costs alone blow the risk budget even at qty=1, the engine must
    # reject outright rather than approve a qty=0 "trade".
    engine = RiskEngine()
    verdict = engine.evaluate(make_trade(target=2501.0, estimated_costs=50.0))
    assert verdict.decision == RiskDecision.REJECT_ZERO_QUANTITY
    assert verdict.approved_quantity == 0


def test_risk_pct_never_exceeds_configured_max():
    engine = RiskEngine()
    for stop_dist in [5, 10, 20, 50, 100]:
        v = engine.evaluate(make_trade(stop_loss=2500 - stop_dist, target=2500 + stop_dist * 2))
        if v.decision == RiskDecision.APPROVE:
            assert v.risk_pct <= 1.0 + 1e-6


def test_agent_returns_risk_decision_without_submitting_order():
    result = TradingAgent().run_once(make_trade())
    assert result.verdict.decision == RiskDecision.APPROVE
    assert result.order_submitted is False


def test_paper_agent_factory_returns_agent():
    assert isinstance(build_paper_agent(), TradingAgent)
