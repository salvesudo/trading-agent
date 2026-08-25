"""
Shared stop/target sizing math -- Phase 9.

Every strategy in app/strategy/ that needs an ATR-based stop and target
uses this one function, so the risk:reward construction is consistent
across strategy families and only needs fixing in one place if it's
ever wrong. This does not decide position size (that's the Risk
Engine's job, from account equity and risk %, not from anything here)
-- it only sizes the price distance to the stop and target.
"""
from __future__ import annotations

from typing import Tuple


def atr_stop_and_target(
    entry: float, atr_value: float, side: str, stop_multiple: float, reward_multiple: float
) -> Tuple[float, float]:
    """Return (stop_loss, target) for a BUY/SELL at `entry`, with the
    stop `stop_multiple` ATRs away and the target `reward_multiple`
    times the stop distance away, on the correct side for `side`."""
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be 'BUY' or 'SELL', got {side!r}")
    stop_distance = atr_value * stop_multiple
    if side == "BUY":
        stop = entry - stop_distance
        target = entry + stop_distance * reward_multiple
    else:
        stop = entry + stop_distance
        target = entry - stop_distance * reward_multiple
    return stop, target


__all__ = ["atr_stop_and_target"]
