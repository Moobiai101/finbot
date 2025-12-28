"""Stock scanner for identifying trading opportunities."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from loguru import logger

from finbot.broker.angel_client import get_angel_client, AngelOneClient


@dataclass
class HotStock:
    """A stock identified by the scanner."""
    symbol: str
    token: str
    exchange: str
    ltp: float
    change_percent: float
    volume: int
    reason: str  # Why it was selected
    score: float = 0.0  # Ranking score


class StockScanner:
    """
    Scan for trading opportunities.
    
    Identifies stocks based on:
    - Price gainers/losers
    - Volume spikes
    - Opening gaps
    - Intraday movers
    """
    
    def __init__(self, client: Optional[AngelOneClient] = None):
        """Initialize scanner."""
        self.client = client or get_angel_client()
        self._watchlist_cache: dict[str, HotStock] = {}
        self._last_scan: Optional[datetime] = None
    
    def scan_gainers(self, top_n: int = 10) -> list[HotStock]:
        """Get top price gainers."""
        try:
            data = self.client.get_gainers_losers(
                data_type="PercPriceGainers",
                expiry_type="NEAR",
            )
            
            stocks = []
            for item in data[:top_n]:
                stocks.append(HotStock(
                    symbol=item.get("tradingSymbol", ""),
                    token=str(item.get("symbolToken", "")),
                    exchange=item.get("exchange", "NSE"),
                    ltp=float(item.get("ltp", 0)),
                    change_percent=float(item.get("percentChange", 0)),
                    volume=int(item.get("volume", 0)),
                    reason="price_gainer",
                    score=float(item.get("percentChange", 0)),
                ))
            
            return stocks
            
        except Exception as e:
            logger.error(f"Scanner gainers error: {e}")
            return []
    
    def scan_losers(self, top_n: int = 10) -> list[HotStock]:
        """Get top price losers (for short opportunities)."""
        try:
            data = self.client.get_gainers_losers(
                data_type="PercPriceLosers",
                expiry_type="NEAR",
            )
            
            stocks = []
            for item in data[:top_n]:
                stocks.append(HotStock(
                    symbol=item.get("tradingSymbol", ""),
                    token=str(item.get("symbolToken", "")),
                    exchange=item.get("exchange", "NSE"),
                    ltp=float(item.get("ltp", 0)),
                    change_percent=float(item.get("percentChange", 0)),
                    volume=int(item.get("volume", 0)),
                    reason="price_loser",
                    score=abs(float(item.get("percentChange", 0))),
                ))
            
            return stocks
            
        except Exception as e:
            logger.error(f"Scanner losers error: {e}")
            return []
    
    def scan_nse_movers(self) -> list[HotStock]:
        """Get NSE intraday movers."""
        try:
            data = self.client.get_nse_intraday_movers()
            
            stocks = []
            for item in data:
                stocks.append(HotStock(
                    symbol=item.get("tradingSymbol", ""),
                    token=str(item.get("symbolToken", "")),
                    exchange="NSE",
                    ltp=float(item.get("ltp", 0)),
                    change_percent=float(item.get("percentChange", 0)),
                    volume=int(item.get("volume", 0)),
                    reason="nse_mover",
                    score=abs(float(item.get("percentChange", 0))),
                ))
            
            return stocks
            
        except Exception as e:
            logger.error(f"Scanner NSE movers error: {e}")
            return []
    
    def scan_bse_movers(self) -> list[HotStock]:
        """Get BSE intraday movers."""
        try:
            data = self.client.get_bse_intraday_movers()
            
            stocks = []
            for item in data:
                stocks.append(HotStock(
                    symbol=item.get("tradingSymbol", ""),
                    token=str(item.get("symbolToken", "")),
                    exchange="BSE",
                    ltp=float(item.get("ltp", 0)),
                    change_percent=float(item.get("percentChange", 0)),
                    volume=int(item.get("volume", 0)),
                    reason="bse_mover",
                    score=abs(float(item.get("percentChange", 0))),
                ))
            
            return stocks
            
        except Exception as e:
            logger.error(f"Scanner BSE movers error: {e}")
            return []
    
    def scan_all(self, top_n: int = 20) -> list[HotStock]:
        """
        Run comprehensive scan and return top opportunities.
        
        Combines multiple scans and ranks by score.
        """
        all_stocks: dict[str, HotStock] = {}
        
        # Collect from all sources
        for stock in self.scan_gainers(top_n):
            key = f"{stock.exchange}:{stock.symbol}"
            if key not in all_stocks or stock.score > all_stocks[key].score:
                all_stocks[key] = stock
        
        for stock in self.scan_losers(top_n):
            key = f"{stock.exchange}:{stock.symbol}"
            if key not in all_stocks or stock.score > all_stocks[key].score:
                all_stocks[key] = stock
        
        for stock in self.scan_nse_movers():
            key = f"{stock.exchange}:{stock.symbol}"
            if key not in all_stocks or stock.score > all_stocks[key].score:
                all_stocks[key] = stock
        
        # Sort by score and return top N
        sorted_stocks = sorted(all_stocks.values(), key=lambda x: x.score, reverse=True)
        
        self._watchlist_cache = {f"{s.exchange}:{s.symbol}": s for s in sorted_stocks[:top_n]}
        self._last_scan = datetime.now()
        
        logger.info(f"Scanner found {len(sorted_stocks)} stocks, returning top {top_n}")
        
        return sorted_stocks[:top_n]
    
    def get_watchlist(self) -> list[HotStock]:
        """Get current watchlist from last scan."""
        return list(self._watchlist_cache.values())
    
    def filter_by_price(
        self,
        stocks: list[HotStock],
        min_price: float = 50,
        max_price: float = 5000,
    ) -> list[HotStock]:
        """Filter stocks by price range (for capital constraints)."""
        return [s for s in stocks if min_price <= s.ltp <= max_price]
    
    def filter_by_change(
        self,
        stocks: list[HotStock],
        min_change: float = 1.0,
        max_change: float = 10.0,
    ) -> list[HotStock]:
        """Filter by change percent (avoid too volatile)."""
        return [
            s for s in stocks
            if min_change <= abs(s.change_percent) <= max_change
        ]


# Singleton
_scanner: Optional[StockScanner] = None


def get_scanner() -> StockScanner:
    """Get or create scanner singleton."""
    global _scanner
    if _scanner is None:
        _scanner = StockScanner()
    return _scanner
