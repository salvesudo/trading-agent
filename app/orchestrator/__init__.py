"""
Continuous paper-trading orchestration -- added 2026-09-06.

Every phase before this (2 through 12) is a complete, tested toolkit
with nothing tying it together into something that actually runs
unattended. This package is that missing piece: it wires market data,
regime detection, the strategy engine, live news, the Risk Engine, and
the paper trading engine into a loop that watches real symbols and
makes real (paper) decisions on a schedule.

This exists specifically *instead of* two other things that would have
been premature: more backtesting (116+ trades across multiple windows
already found no strategy with validated edge -- see
docs/PRINCIPLES.md sections 24-27, and further backtesting risks just
curve-fitting to the same historical data), and Phase 13's AI advisory
layer (which was explicitly scoped to sit on top of backtesting-
validated strategies, a bar that hasn't been cleared). Paper trading
forward, on live data the strategies have never seen, is a stronger
form of evidence than more backtesting -- there is no possibility of
look-ahead bias, and it costs nothing (TRADING_MODE=PAPER only; this
package never places a real order, same guarantee as everywhere else in
this project).
"""
