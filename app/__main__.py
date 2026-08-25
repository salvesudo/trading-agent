"""Command-line entrypoint for a paper-mode risk evaluation."""
from __future__ import annotations

import argparse

from app.agent import build_paper_agent
from app.risk.risk_engine import TradeCandidate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate a paper trading candidate")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--side", choices=("BUY", "SELL"), required=True)
    parser.add_argument("--entry", type=float, required=True)
    parser.add_argument("--stop", type=float, required=True)
    parser.add_argument("--target", type=float, required=True)
    parser.add_argument("--equity", type=float, required=True)
    parser.add_argument("--costs", type=float, default=0.0)
    return parser


def main() -> None:
    args = _parser().parse_args()
    agent = build_paper_agent()
    result = agent.run_once(
        TradeCandidate(
            symbol=args.symbol,
            side=args.side,
            entry_price=args.entry,
            stop_loss=args.stop,
            target=args.target,
            account_equity=args.equity,
            estimated_costs=args.costs,
        )
    )
    print(f"{result.symbol}: {result.verdict.decision.value}")
    print(result.verdict.reason)
    print(f"approved_quantity={result.verdict.approved_quantity}")
    print("order_submitted=False")


if __name__ == "__main__":
    main()