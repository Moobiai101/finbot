"""
Backtest Universe definition.

Defines the list of stocks to be used during backtesting.
Focused on high-liquidity large caps (NIFTY 30 Weighted).
"""

from dataclasses import dataclass
from typing import Optional
from loguru import logger
from finbot.broker.angel_client import get_angel_client

@dataclass
class BacktestSymbol:
    symbol: str
    exchange: str = "NSE"
    token: Optional[str] = None
    name: str = ""

# Top 30 NIFTY 50 stocks by weight (approximate)
NIFTY_30_WEIGHTED = [
    BacktestSymbol(symbol="HDFCBANK-EQ", name="HDFC Bank"),
    BacktestSymbol(symbol="RELIANCE-EQ", name="Reliance Industries"),
    BacktestSymbol(symbol="ICICIBANK-EQ", name="ICICI Bank"),
    BacktestSymbol(symbol="INFY-EQ", name="Infosys"),
    BacktestSymbol(symbol="ITC-EQ", name="ITC"),
    BacktestSymbol(symbol="TCS-EQ", name="TCS"),
    BacktestSymbol(symbol="L&T-EQ", name="Larsen & Toubro"),
    BacktestSymbol(symbol="AXISBANK-EQ", name="Axis Bank"),
    BacktestSymbol(symbol="BHARTIARTL-EQ", name="Bharti Airtel"),
    BacktestSymbol(symbol="SBIN-EQ", name="State Bank of India"),
    BacktestSymbol(symbol="HINDUNILVR-EQ", name="Hindustan Unilever"),
    BacktestSymbol(symbol="BAJFINANCE-EQ", name="Bajaj Finance"),
    BacktestSymbol(symbol="M&M-EQ", name="Mahindra & Mahindra"),
    BacktestSymbol(symbol="MARUTI-EQ", name="Maruti Suzuki"),
    BacktestSymbol(symbol="HCLTECH-EQ", name="HCL Technologies"),
    BacktestSymbol(symbol="TITAN-EQ", name="Titan"),
    BacktestSymbol(symbol="SUNPHARMA-EQ", name="Sun Pharma"),
    BacktestSymbol(symbol="TATASTEEL-EQ", name="Tata Steel"),
    BacktestSymbol(symbol="ULTRACEMCO-EQ", name="UltraTech Cement"),
    BacktestSymbol(symbol="NTPC-EQ", name="NTPC"),
    BacktestSymbol(symbol="POWERGRID-EQ", name="Power Grid"),
    BacktestSymbol(symbol="TATACOMP-EQ", name="Tata Consumer"), # Often tricky symbol, verify
    BacktestSymbol(symbol="BAJAJFINSV-EQ", name="Bajaj Finserv"),
    BacktestSymbol(symbol="ONGC-EQ", name="ONGC"),
    BacktestSymbol(symbol="WIPRO-EQ", name="Wipro"),
    BacktestSymbol(symbol="COALINDIA-EQ", name="Coal India"),
    BacktestSymbol(symbol="ASIANPAINT-EQ", name="Asian Paints"),
    BacktestSymbol(symbol="JSWSTEEL-EQ", name="JSW Steel"),
    BacktestSymbol(symbol="ADANIENT-EQ", name="Adani Enterprises"),
    BacktestSymbol(symbol="GRASIM-EQ", name="Grasim"),
]

class UniverseManager:
    """Manages symbol resolution for backtesting."""
    
    def __init__(self):
        self.client = get_angel_client()
        self.resolved_symbols: dict[str, BacktestSymbol] = {}

    def resolve_tokens(self) -> list[BacktestSymbol]:
        """
        Resolve tokens for all symbols in the universe.
        WARNING: Requires active Angel One login.
        """
        logger.info("Resolving tokens for NIFTY 30 Universe...")
        resolved = []
        
        # We can try to use client.search_symbol, but it might be faster to fetch master dump 
        # if we had it. For now, sequential search is safer for correctness.
        
        for item in NIFTY_30_WEIGHTED:
            try:
                # Remove -EQ suffix for search if needed, but searchScrip usually handles it
                query = item.symbol.replace("-EQ", "")
                results = self.client.search_symbol(item.exchange, query)
                
                found = False
                for res in results:
                    if res.get("tradingsymbol") == item.symbol:
                        item.token = res.get("symboltoken")
                        logger.info(f"✅ Resolved {item.symbol} -> {item.token}")
                        resolved.append(item)
                        found = True
                        break
                
                if not found:
                    logger.warning(f"❌ Could not resolve token for {item.symbol}")
            
            except Exception as e:
                logger.error(f"Error resolving {item.symbol}: {e}")
        
        self.resolved_symbols = {s.symbol: s for s in resolved}
        return resolved

# Singleton
_universe: Optional[UniverseManager] = None

def get_universe() -> UniverseManager:
    global _universe
    if _universe is None:
        _universe = UniverseManager()
    return _universe
