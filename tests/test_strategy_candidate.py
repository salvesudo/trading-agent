from app.risk.risk_engine import TradeCandidate
from app.strategy.candidate import to_trade_candidate
from app.strategy.models import StrategyName, StrategySignal


def _signal(confidence=0.7):
    return StrategySignal(
        strategy=StrategyName.TREND_FOLLOWING, symbol="RELIANCE", side="BUY",
        entry_price=2500.0, stop_loss=2480.0, target=2560.0, confidence=confidence, reason="test",
    )


def test_to_trade_candidate_maps_price_fields():
    candidate = to_trade_candidate(_signal(), account_equity=5000.0, estimated_costs=15.0)
    assert isinstance(candidate, TradeCandidate)
    assert candidate.symbol == "RELIANCE"
    assert candidate.side == "BUY"
    assert candidate.entry_price == 2500.0
    assert candidate.stop_loss == 2480.0
    assert candidate.target == 2560.0
    assert candidate.account_equity == 5000.0
    assert candidate.estimated_costs == 15.0


def test_expected_win_prob_defaults_to_signal_confidence():
    candidate = to_trade_candidate(_signal(confidence=0.65), account_equity=5000.0, estimated_costs=15.0)
    assert candidate.expected_win_prob == 0.65


def test_expected_win_prob_explicit_override_wins():
    candidate = to_trade_candidate(
        _signal(confidence=0.65), account_equity=5000.0, estimated_costs=15.0, expected_win_prob=0.42
    )
    assert candidate.expected_win_prob == 0.42
