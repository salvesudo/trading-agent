import pytest

from app.broker.costs import (
    BROKERAGE_PCT,
    EXCHANGE_TXN_PCT,
    GST_RATE,
    PRIME_BROKERAGE_CAP_INR,
    SEBI_FEE_PCT,
    STANDARD_BROKERAGE_CAP_INR,
    STAMP_DUTY_BUY_PCT,
    STT_SELL_PCT,
    estimate_intraday_costs,
    round_trip_cost,
)


def _manual_cost(buy_price, sell_price, qty, cap):
    buy_notional = buy_price * qty
    sell_notional = sell_price * qty
    brokerage_buy = min(cap, buy_notional * BROKERAGE_PCT)
    brokerage_sell = min(cap, sell_notional * BROKERAGE_PCT)
    exchange_buy = buy_notional * EXCHANGE_TXN_PCT
    exchange_sell = sell_notional * EXCHANGE_TXN_PCT
    stt_sell = sell_notional * STT_SELL_PCT
    stamp_buy = buy_notional * STAMP_DUTY_BUY_PCT
    sebi_fee = (buy_notional + sell_notional) * SEBI_FEE_PCT
    gst = GST_RATE * (brokerage_buy + brokerage_sell + exchange_buy + exchange_sell)
    return brokerage_buy + brokerage_sell + exchange_buy + exchange_sell + stt_sell + stamp_buy + sebi_fee + gst


def test_zero_or_negative_quantity_is_zero_cost():
    assert round_trip_cost(1000.0, 1000.0, 0) == 0.0
    assert round_trip_cost(1000.0, 1000.0, -5) == 0.0


def test_small_trade_matches_manual_percentage_calculation():
    # Well below the ~66,667 notional where the ₹20 cap would ever bind.
    cost = round_trip_cost(1200.0, 1205.0, 5)
    assert cost == pytest.approx(_manual_cost(1200.0, 1205.0, 5, STANDARD_BROKERAGE_CAP_INR))


def test_one_share_trade_is_well_under_a_rupee_or_two():
    # The module docstring's own concrete claim: a 1-share, ~₹1,200
    # trade's real round-trip cost is under ₹2 -- the exact scenario
    # that made a flat ₹15/trade guess such an overestimate.
    assert round_trip_cost(1200.0, 1200.0, 1) < 2.0


def test_large_notional_trips_the_standard_brokerage_cap():
    # 100 shares @ ~1000-1010 = ~100k-101k notional -- well past where
    # 0.03% (>=30) exceeds the ₹20 cap, so both legs should be capped.
    buy_notional = 1000.0 * 100
    sell_notional = 1010.0 * 100
    assert buy_notional * BROKERAGE_PCT > STANDARD_BROKERAGE_CAP_INR
    assert sell_notional * BROKERAGE_PCT > STANDARD_BROKERAGE_CAP_INR

    cost = round_trip_cost(1000.0, 1010.0, 100)
    assert cost == pytest.approx(_manual_cost(1000.0, 1010.0, 100, STANDARD_BROKERAGE_CAP_INR))


def test_prime_uses_a_lower_cap_than_standard_for_capped_trades():
    standard = round_trip_cost(1000.0, 1010.0, 100, prime=False)
    prime = round_trip_cost(1000.0, 1010.0, 100, prime=True)
    assert prime < standard


def test_prime_matches_standard_when_neither_cap_binds():
    # Small enough that 0.03% never reaches even the lower ₹15 cap --
    # plan shouldn't matter here.
    standard = round_trip_cost(1200.0, 1205.0, 5, prime=False)
    prime = round_trip_cost(1200.0, 1205.0, 5, prime=True)
    assert standard == pytest.approx(prime)


def test_estimate_intraday_costs_sizes_like_the_risk_engines_raw_formula():
    # entry=1200, stop=1190 -> stop_distance=10; 1% of 5000 = 50 risk;
    # floor(50/10) = 5 shares, priced at entry_price for both legs
    # (exit price isn't known yet at this point in the pipeline).
    cost = estimate_intraday_costs(entry_price=1200.0, stop_loss=1190.0, account_equity=5000.0, risk_pct=1.0)
    assert cost == pytest.approx(round_trip_cost(1200.0, 1200.0, 5))


def test_estimate_intraday_costs_zero_when_stop_equals_entry():
    assert estimate_intraday_costs(entry_price=1200.0, stop_loss=1200.0, account_equity=5000.0) == 0.0


def test_estimate_intraday_costs_respects_explicit_prime_override():
    without = estimate_intraday_costs(entry_price=1000.0, stop_loss=999.99, account_equity=500_000.0, prime=False)
    with_prime = estimate_intraday_costs(entry_price=1000.0, stop_loss=999.99, account_equity=500_000.0, prime=True)
    assert with_prime < without
