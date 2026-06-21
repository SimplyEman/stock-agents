"""Backtesting harness with point-in-time data discipline."""

from stock_agents.backtesting.harness import BacktestResult, BacktestRow, run_backtest
from stock_agents.backtesting.point_in_time import as_of_context, forward_return

__all__ = ["BacktestResult", "BacktestRow", "run_backtest", "as_of_context", "forward_return"]
