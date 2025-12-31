"""
Backtest Reporting Module.

Calculates comprehensive performance metrics for backtests.
Includes per-strategy breakdown, per-symbol analysis, and detailed trade statistics.
"""

from dataclasses import asdict
from collections import defaultdict
from datetime import datetime
import pandas as pd
import numpy as np
from finbot.backtest.engine import PortfolioState, Trade


def generate_report(portfolios: dict[str, PortfolioState]) -> dict:
    """
    Generate comprehensive report for all portfolios.
    
    Returns:
        dict with summary, strategy_breakdown, symbol_breakdown, trades
    """
    # Combine all trades from all portfolios
    all_trades: list[Trade] = []
    total_initial_capital = 0
    total_final_capital = 0
    
    for name, pf in portfolios.items():
        all_trades.extend(pf.trades)
        total_initial_capital += pf.initial_capital
        total_final_capital += pf.current_capital
    
    # Calculate overall summary
    summary = _calculate_overall_summary(all_trades, total_initial_capital, total_final_capital)
    
    # Calculate per-strategy breakdown
    strategy_breakdown = _calculate_strategy_breakdown(all_trades)
    
    # Calculate per-symbol breakdown
    symbol_breakdown = _calculate_symbol_breakdown(all_trades)
    
    # Serialize trades for storage
    trades_list = _serialize_trades(all_trades)
    
    # Generate equity curve
    equity_curve = _generate_equity_curve(all_trades, total_initial_capital)
    
    return {
        "summary": summary,
        "strategy_breakdown": strategy_breakdown,
        "symbol_breakdown": symbol_breakdown,
        "trades": trades_list,
        "equity_curve": equity_curve,
    }


def _calculate_overall_summary(trades: list[Trade], initial_capital: float, final_capital: float) -> dict:
    """Calculate overall backtest metrics."""
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "total_return_pct": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "avg_trade_pnl": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "initial_capital": initial_capital,
            "final_capital": final_capital,
        }
    
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    
    total_trades = len(trades)
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0
    
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    total_pnl = gross_profit - gross_loss
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    if profit_factor == float('inf'):
        profit_factor = 999.0  # Cap for JSON serialization
    
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    largest_win = max((t.pnl for t in wins), default=0)
    largest_loss = min((t.pnl for t in losses), default=0)
    
    # Calculate max drawdown
    max_drawdown = _calculate_max_drawdown(trades, initial_capital)
    
    # Calculate Sharpe ratio (annualized)
    sharpe = _calculate_sharpe(trades)
    
    # Calculate win/loss streaks
    win_streak, loss_streak = _calculate_streaks(trades)
    
    return {
        "total_trades": total_trades,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "total_return_pct": round((final_capital - initial_capital) / initial_capital * 100, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "largest_win": round(largest_win, 2),
        "largest_loss": round(largest_loss, 2),
        "avg_trade_pnl": round(total_pnl / total_trades, 2) if total_trades > 0 else 0,
        "max_drawdown_pct": round(max_drawdown, 2),
        "sharpe_ratio": round(sharpe, 2),
        "max_win_streak": win_streak,
        "max_loss_streak": loss_streak,
        "initial_capital": round(initial_capital, 2),
        "final_capital": round(final_capital, 2),
    }


def _calculate_strategy_breakdown(trades: list[Trade]) -> dict:
    """Calculate metrics per strategy."""
    by_strategy = defaultdict(list)
    for trade in trades:
        by_strategy[trade.strategy].append(trade)
    
    breakdown = {}
    for strategy, strat_trades in by_strategy.items():
        wins = [t for t in strat_trades if t.pnl > 0]
        losses = [t for t in strat_trades if t.pnl <= 0]
        
        total = len(strat_trades)
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        pf = gross_profit / gross_loss if gross_loss > 0 else 999.0
        
        breakdown[strategy] = {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(len(wins) / total * 100, 2) if total > 0 else 0,
            "total_pnl": round(gross_profit - gross_loss, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(pf, 2),
            "avg_win": round(gross_profit / len(wins), 2) if wins else 0,
            "avg_loss": round(gross_loss / len(losses), 2) if losses else 0,
            "avg_confidence": round(sum(t.confidence for t in strat_trades) / total * 100, 1) if total > 0 else 0,
        }
    
    return breakdown


def _calculate_symbol_breakdown(trades: list[Trade]) -> dict:
    """Calculate metrics per symbol."""
    by_symbol = defaultdict(list)
    for trade in trades:
        by_symbol[trade.symbol].append(trade)
    
    breakdown = {}
    for symbol, sym_trades in by_symbol.items():
        wins = [t for t in sym_trades if t.pnl > 0]
        losses = [t for t in sym_trades if t.pnl <= 0]
        
        total = len(sym_trades)
        total_pnl = sum(t.pnl for t in sym_trades)
        
        breakdown[symbol] = {
            "total_trades": total,
            "winning_trades": len(wins),
            "win_rate": round(len(wins) / total * 100, 2) if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(total_pnl / total, 2) if total > 0 else 0,
        }
    
    # Sort by total P&L
    breakdown = dict(sorted(breakdown.items(), key=lambda x: x[1]["total_pnl"], reverse=True))
    
    return breakdown


def _calculate_max_drawdown(trades: list[Trade], initial_capital: float) -> float:
    """Calculate maximum drawdown percentage."""
    if not trades:
        return 0.0
    
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    
    for trade in sorted(trades, key=lambda t: t.exit_time or t.entry_time):
        equity += trade.pnl
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)
    
    return max_dd


def _calculate_sharpe(trades: list[Trade]) -> float:
    """Calculate annualized Sharpe ratio from trade returns."""
    if len(trades) < 2:
        return 0.0
    
    # Calculate returns per trade
    returns = []
    for t in trades:
        if t.entry_price and t.quantity:
            trade_value = t.entry_price * t.quantity
            ret = t.pnl / trade_value if trade_value > 0 else 0
            returns.append(ret)
    
    if len(returns) < 2:
        return 0.0
    
    avg_ret = np.mean(returns)
    std_ret = np.std(returns)
    
    # Annualize (assuming ~252 trading days)
    sharpe = (avg_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    
    return sharpe


def _calculate_streaks(trades: list[Trade]) -> tuple[int, int]:
    """Calculate max win and loss streaks."""
    if not trades:
        return 0, 0
    
    sorted_trades = sorted(trades, key=lambda t: t.exit_time or t.entry_time)
    
    max_win_streak = 0
    max_loss_streak = 0
    current_win = 0
    current_loss = 0
    
    for trade in sorted_trades:
        if trade.pnl > 0:
            current_win += 1
            current_loss = 0
            max_win_streak = max(max_win_streak, current_win)
        else:
            current_loss += 1
            current_win = 0
            max_loss_streak = max(max_loss_streak, current_loss)
    
    return max_win_streak, max_loss_streak


def _serialize_trades(trades: list[Trade]) -> list[dict]:
    """Convert trades to serializable format for storage."""
    result = []
    for t in trades:
        trade_dict = {
            "symbol": t.symbol,
            "strategy": t.strategy,
            "signal_type": t.signal_type.value if hasattr(t.signal_type, 'value') else str(t.signal_type),
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "entry_price": float(t.entry_price) if t.entry_price else 0,
            "exit_price": float(t.exit_price) if t.exit_price else 0,
            "quantity": int(t.quantity) if t.quantity else 0,
            "pnl": float(t.pnl) if t.pnl else 0,
            "pnl_percent": float(t.pnl / (t.entry_price * t.quantity) * 100) if t.entry_price and t.quantity else 0,
            "confidence": float(t.confidence) if hasattr(t, 'confidence') and t.confidence else 0,
            "reason": getattr(t, 'reason', ''),
        }
        result.append(trade_dict)
    
    return result


def _generate_equity_curve(trades: list[Trade], initial_capital: float) -> list[dict]:
    """Generate equity curve data points."""
    if not trades:
        return [{"time": datetime.now().isoformat(), "equity": initial_capital}]
    
    sorted_trades = sorted(trades, key=lambda t: t.exit_time or t.entry_time)
    
    equity = initial_capital
    curve = [{"time": sorted_trades[0].entry_time.isoformat(), "equity": initial_capital}]
    
    for trade in sorted_trades:
        equity += trade.pnl
        curve.append({
            "time": (trade.exit_time or trade.entry_time).isoformat(),
            "equity": round(equity, 2),
        })
    
    return curve
