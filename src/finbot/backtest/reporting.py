"""
Backtest Reporting Module.

Calculates performance metrics for portfolios.
"""

from dataclasses import asdict
import pandas as pd
import numpy as np
from finbot.backtest.engine import PortfolioState, Trade

def generate_report(portfolios: dict[str, PortfolioState]) -> dict:
    """Generate comparative report for all portfolios."""
    
    report = {}
    
    for name, pf in portfolios.items():
        metrics = _calculate_metrics(pf)
        
        # Convert trades to dict for JSON
        trades_list = []
        for t in pf.trades:
            t_dict = asdict(t)
            # Serialize datetimes
            t_dict['entry_time'] = t.entry_time.isoformat()
            if t.exit_time:
                t_dict['exit_time'] = t.exit_time.isoformat()
            trades_list.append(t_dict)
            
        report[name] = {
            "metrics": metrics,
            "trades": trades_list,
            "equity_curve": [
                {"time": e["time"].isoformat(), "equity": e["equity"]}
                for e in pf.equity_curve
            ]
        }
        
    return report

def _calculate_metrics(pf: PortfolioState) -> dict:
    """Calculate CAGR, Sharpe, DD, etc."""
    
    total_trades = len(pf.trades)
    if total_trades == 0:
        return {
            "total_trades": 0,
            "net_pnl": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "sharpe_ratio": 0.0,
            "final_capital": pf.current_capital
        }

    wins = [t for t in pf.trades if t.pnl > 0]
    losses = [t for t in pf.trades if t.pnl <= 0]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    net_pnl = gross_profit - gross_loss
    
    # Drawdown
    equity_curve = [e['equity'] for e in pf.equity_curve]
    if not equity_curve:
        equity_curve = [pf.initial_capital, pf.current_capital]
        
    equity_series = pd.Series(equity_curve)
    rolling_max = equity_series.cummax()
    drawdown = (equity_series - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    # Sharpe (approximate assuming daily/per-trade returns)
    # Correct way: Calculate daily returns from equity curve
    # but we might not have daily points if we only record on trade exit.
    # We will use Trade Returns for now. 
    trade_returns = [t.pnl / (t.entry_price * t.quantity) for t in pf.trades]
    if len(trade_returns) > 1:
        avg_ret = np.mean(trade_returns)
        std_ret = np.std(trade_returns)
        sharpe = (avg_ret / std_ret) * np.sqrt(252) if std_ret > 0 else 0
    else:
        sharpe = 0
        
    return {
        "total_trades": total_trades,
        "net_pnl": round(net_pnl, 2),
        "win_rate": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "final_capital": round(pf.current_capital, 2),
        "total_return_pct": round(((pf.current_capital - pf.initial_capital) / pf.initial_capital) * 100, 2)
    }
