"""Angel One broker client wrapper using SmartAPI SDK."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum

import pyotp
from loguru import logger

# Add SmartApi to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / "smartapi-python"))

from SmartApi.smartConnect import SmartConnect
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from finbot.config import get_settings
from finbot.services.redis_service import RedisService


class Exchange(str, Enum):
    """Exchange types."""
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    MCX = "MCX"


class OrderType(str, Enum):
    """Order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOPLOSS_LIMIT = "STOPLOSS_LIMIT"
    STOPLOSS_MARKET = "STOPLOSS_MARKET"


class ProductType(str, Enum):
    """Product types for orders."""
    INTRADAY = "INTRADAY"  # MIS
    DELIVERY = "DELIVERY"  # CNC
    CARRYFORWARD = "CARRYFORWARD"  # NRML
    MARGIN = "MARGIN"


class TransactionType(str, Enum):
    """Transaction types."""
    BUY = "BUY"
    SELL = "SELL"


class Variety(str, Enum):
    """Order variety."""
    NORMAL = "NORMAL"
    STOPLOSS = "STOPLOSS"
    AMO = "AMO"  # After Market Order
    ROBO = "ROBO"


@dataclass
class Candle:
    """OHLCV candle data."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @classmethod
    def from_api_response(cls, data: list) -> "Candle":
        """Create Candle from API response [timestamp, o, h, l, c, v]."""
        return cls(
            timestamp=datetime.strptime(data[0], "%Y-%m-%dT%H:%M:%S%z"),
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=int(data[5]),
        )


@dataclass
class Position:
    """Position data."""
    symbol: str
    token: str
    exchange: str
    product_type: str
    quantity: int
    average_price: float
    ltp: float
    pnl: float
    pnl_percent: float


@dataclass
class Order:
    """Order data."""
    order_id: str
    symbol: str
    exchange: str
    transaction_type: str
    quantity: int
    price: float
    status: str
    order_type: str


class AngelOneClient:
    """
    Wrapper around Angel One SmartAPI SDK.
    
    Provides clean interface for:
    - Authentication with TOTP
    - Historical data fetching
    - Live market data
    - Order management
    - Position tracking
    - Market scanning (gainers/losers)
    """
    
    # Interval mapping for getCandleData
    INTERVALS = {
        "1m": "ONE_MINUTE",
        "3m": "THREE_MINUTE",
        "5m": "FIVE_MINUTE",
        "10m": "TEN_MINUTE",
        "15m": "FIFTEEN_MINUTE",
        "30m": "THIRTY_MINUTE",
        "1h": "ONE_HOUR",
        "1d": "ONE_DAY",
    }
    
    # Exchange type mapping for WebSocket
    EXCHANGE_TYPE_MAP = {
        "NSE": 1,  # NSE Cash
        "NFO": 2,  # NSE F&O
        "BSE": 3,  # BSE Cash
        "BFO": 4,  # BSE F&O
        "MCX": 5,  # MCX
    }
    
    def __init__(self):
        """Initialize the Angel One client."""
        self.settings = get_settings()
        self.smart_api: Optional[SmartConnect] = None
        self.websocket: Optional[SmartWebSocketV2] = None
        self._is_authenticated = False
        self._user_data: dict = {}
        self._feed_token: Optional[str] = None
        self._auth_token: Optional[str] = None
    
    # ==================== AUTHENTICATION ====================
    
    async def login(self) -> dict:
        """
        Authenticate with Angel One using TOTP.
        
        Returns:
            dict: User profile data on success.
        
        Raises:
            Exception: If authentication fails.
        """
        try:
            # Initialize SmartConnect
            self.smart_api = SmartConnect(
                api_key=self.settings.angel_api_key.get_secret_value()
            )
            
            # Generate TOTP
            totp = pyotp.TOTP(self.settings.angel_totp_secret.get_secret_value())
            totp_code = totp.now()
            
            # Login
            logger.info(f"Logging in as {self.settings.angel_client_id}...")
            
            # Note: generateSession is synchronous/blocking
            data = self.smart_api.generateSession(
                clientCode=self.settings.angel_client_id,
                password=self.settings.angel_password.get_secret_value(),
                totp=totp_code,
            )
            
            if data.get("status") is False:
                error_msg = data.get("message", "Unknown error")
                logger.error(f"Login failed: {error_msg}")
                raise Exception(f"Angel One login failed: {error_msg}")
            
            # Store tokens
            self._user_data = data.get("data", {})
            self._auth_token = self._user_data.get("jwtToken", "").replace("Bearer ", "")
            self._feed_token = self._user_data.get("feedToken")
            self._is_authenticated = True
            
            # Cache in Redis
            try:
                redis_svc = RedisService.get_instance()
                await redis_svc.cache_auth_tokens(self._user_data)
            except Exception as e:
                logger.warning(f"Failed to cache tokens in Redis: {e}")
            
            logger.info(f"✅ Logged in successfully as {self._user_data.get('clientcode')}")
            
            return self._user_data
            
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            raise

    async def try_restore_session(self) -> bool:
        """
        Attempt to restore session from Redis cache.
        Returns:
            bool: True if session restored, False otherwise.
        """
        try:
            redis_svc = RedisService.get_instance()
            tokens = await redis_svc.get_auth_tokens()
            
            if not tokens:
                return False
                
            # Restore state
            self.smart_api = SmartConnect(
                api_key=self.settings.angel_api_key.get_secret_value()
            )
            
            self._auth_token = tokens["jwtToken"]
            self.smart_api.setAccessToken(self._auth_token)
            self.smart_api.setFeedToken(tokens["feedToken"])
            
            # Manually reconstruct minimal user data needed
            self._user_data = tokens["data"]
            self._feed_token = tokens["feedToken"]
            self._is_authenticated = True
            
            logger.info("✅ Session restored from Redis cache")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to restore session from Redis: {e}")
            return False
    
    def logout(self) -> bool:
        """Logout and terminate session."""
        if not self.smart_api:
            return True
        
        try:
            self.smart_api.terminateSession(self.settings.angel_client_id)
            self._is_authenticated = False
            logger.info("Logged out successfully")
            return True
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False
    
    async def refresh_token(self) -> bool:
        """Refresh the access token."""
        if not self.smart_api:
            return False
        
        try:
            refresh_token = self._user_data.get("refreshToken")
            if not refresh_token:
                logger.warning("No refresh token available")
                return False
            
            response = self.smart_api.generateToken(refresh_token)
            if response.get("status"):
                data = response["data"]
                self._auth_token = data.get("jwtToken")
                self._feed_token = data.get("feedToken")
                
                # Update stored user data
                self._user_data["jwtToken"] = self._auth_token
                self._user_data["feedToken"] = self._feed_token
                if "refreshToken" in data:
                    self._user_data["refreshToken"] = data["refreshToken"]
                
                # Update Redis
                try:
                    redis_svc = RedisService.get_instance()
                    await redis_svc.cache_auth_tokens(self._user_data)
                except Exception as e:
                    logger.warning(f"Failed to update Redis after refresh: {e}")

                logger.info("Token refreshed successfully")
                return True
            return False
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return False
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client is authenticated."""
        return self._is_authenticated
    
    # ==================== HISTORICAL DATA ====================
    
    def get_historical_data(
        self,
        symbol: str,
        token: str,
        exchange: str,
        interval: str,
        from_date: datetime,
        to_date: datetime,
    ) -> list[Candle]:
        """
        Fetch historical candle data.
        
        Args:
            symbol: Trading symbol (e.g., "RELIANCE-EQ")
            token: Symbol token (e.g., "2885")
            exchange: Exchange (NSE, BSE, NFO, MCX)
            interval: Candle interval (1m, 5m, 15m, 1h, 1d)
            from_date: Start date
            to_date: End date
            
        Returns:
            List of Candle objects
        """
        self._ensure_authenticated()
        
        # Map interval
        api_interval = self.INTERVALS.get(interval, "FIVE_MINUTE")
        
        try:
            response = self.smart_api.getCandleData({
                "exchange": exchange,
                "symboltoken": token,
                "interval": api_interval,
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": to_date.strftime("%Y-%m-%d %H:%M"),
            })
            
            if response.get("status") is False:
                logger.error(f"Historical data error: {response.get('message')}")
                return []
            
            candles = []
            for item in response.get("data", []):
                try:
                    candles.append(Candle.from_api_response(item))
                except Exception as e:
                    logger.warning(f"Failed to parse candle: {e}")
            
            logger.debug(f"Fetched {len(candles)} candles for {symbol}")
            return candles
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return []
    
    def get_previous_day_data(
        self,
        symbol: str,
        token: str,
        exchange: str = "NSE",
    ) -> Optional[Candle]:
        """Get previous trading day's OHLCV."""
        today = datetime.now()
        # Go back up to 5 days to handle weekends
        from_date = today - timedelta(days=5)
        
        candles = self.get_historical_data(
            symbol=symbol,
            token=token,
            exchange=exchange,
            interval="1d",
            from_date=from_date,
            to_date=today,
        )
        
        # Return the most recent complete day (not today)
        if len(candles) >= 2:
            return candles[-2]
        elif len(candles) == 1:
            return candles[0]
        return None
    
    # ==================== LIVE MARKET DATA ====================
    
    def get_ltp(self, exchange: str, symbol: str, token: str) -> Optional[float]:
        """Get Last Traded Price for a symbol."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.ltpData(exchange, symbol, token)
            
            if response.get("status"):
                return float(response["data"]["ltp"])
            return None
        except Exception as e:
            logger.error(f"LTP error: {e}")
            return None
    
    def get_market_data(
        self,
        exchange: str,
        tokens: list[str],
        mode: str = "FULL",
    ) -> dict:
        """
        Get market data for multiple symbols.
        
        Args:
            exchange: Exchange (NSE, BSE, NFO)
            tokens: List of symbol tokens
            mode: LTP, OHLC, or FULL
            
        Returns:
            Dict with token as key and market data as value
        """
        self._ensure_authenticated()
        
        try:
            exchange_tokens = {exchange: tokens}
            response = self.smart_api.getMarketData(mode, exchange_tokens)
            
            if response.get("status"):
                fetched = response.get("data", {}).get("fetched", [])
                return {item["symbolToken"]: item for item in fetched}
            return {}
        except Exception as e:
            logger.error(f"Market data error: {e}")
            return {}
    
    def search_symbol(
        self,
        exchange: str,
        query: str,
    ) -> list[dict]:
        """
        Search for trading symbols.
        
        Args:
            exchange: Exchange to search in
            query: Search query (e.g., "RELIANCE")
            
        Returns:
            List of matching symbols with token info
        """
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.searchScrip(exchange, query)
            
            if response.get("status") and response.get("data"):
                return response["data"]
            return []
        except Exception as e:
            logger.error(f"Symbol search error: {e}")
            return []
    
    # ==================== ORDERS ====================
    
    def place_order(
        self,
        symbol: str,
        token: str,
        exchange: str,
        transaction_type: TransactionType,
        quantity: int,
        price: float = 0,
        order_type: OrderType = OrderType.MARKET,
        product_type: ProductType = ProductType.INTRADAY,
        variety: Variety = Variety.NORMAL,
        trigger_price: float = 0,
    ) -> Optional[str]:
        """
        Place an order.
        
        Args:
            symbol: Trading symbol
            token: Symbol token
            exchange: Exchange
            transaction_type: BUY or SELL
            quantity: Number of shares
            price: Order price (0 for market orders)
            order_type: MARKET, LIMIT, etc.
            product_type: INTRADAY, DELIVERY, etc.
            variety: NORMAL, STOPLOSS, AMO, ROBO
            trigger_price: Trigger price for stop-loss orders
            
        Returns:
            Order ID if successful, None otherwise
        """
        self._ensure_authenticated()
        
        try:
            order_params = {
                "variety": variety.value,
                "tradingsymbol": symbol,
                "symboltoken": token,
                "transactiontype": transaction_type.value,
                "exchange": exchange,
                "ordertype": order_type.value,
                "producttype": product_type.value,
                "duration": "DAY",
                "quantity": str(quantity),
            }
            
            if order_type in [OrderType.LIMIT, OrderType.STOPLOSS_LIMIT]:
                order_params["price"] = str(price)
            else:
                order_params["price"] = "0"
            
            if order_type in [OrderType.STOPLOSS_LIMIT, OrderType.STOPLOSS_MARKET]:
                order_params["triggerprice"] = str(trigger_price)
            else:
                order_params["triggerprice"] = "0"
            
            logger.info(f"Placing order: {transaction_type.value} {quantity} {symbol} @ {price or 'MARKET'}")
            
            order_id = self.smart_api.placeOrder(order_params)
            
            if order_id:
                logger.info(f"✅ Order placed: {order_id}")
                return order_id
            else:
                logger.error("Order placement failed - no order ID returned")
                return None
                
        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return None
    
    def modify_order(
        self,
        order_id: str,
        variety: Variety,
        quantity: Optional[int] = None,
        price: Optional[float] = None,
        order_type: Optional[OrderType] = None,
        trigger_price: Optional[float] = None,
    ) -> bool:
        """Modify an existing order."""
        self._ensure_authenticated()
        
        try:
            modify_params = {
                "variety": variety.value,
                "orderid": order_id,
            }
            
            if quantity:
                modify_params["quantity"] = str(quantity)
            if price is not None:
                modify_params["price"] = str(price)
            if order_type:
                modify_params["ordertype"] = order_type.value
            if trigger_price is not None:
                modify_params["triggerprice"] = str(trigger_price)
            
            response = self.smart_api.modifyOrder(modify_params)
            
            if response.get("status"):
                logger.info(f"Order {order_id} modified successfully")
                return True
            return False
        except Exception as e:
            logger.error(f"Order modification error: {e}")
            return False
    
    def cancel_order(self, order_id: str, variety: Variety = Variety.NORMAL) -> bool:
        """Cancel an order."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.cancelOrder(order_id, variety.value)
            
            if response.get("status"):
                logger.info(f"Order {order_id} cancelled")
                return True
            return False
        except Exception as e:
            logger.error(f"Order cancellation error: {e}")
            return False
    
    def get_order_book(self) -> list[Order]:
        """Get all orders for the day."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.orderBook()
            
            if response.get("status") and response.get("data"):
                orders = []
                for item in response["data"]:
                    orders.append(Order(
                        order_id=item.get("orderid", ""),
                        symbol=item.get("tradingsymbol", ""),
                        exchange=item.get("exchange", ""),
                        transaction_type=item.get("transactiontype", ""),
                        quantity=int(item.get("quantity", 0)),
                        price=float(item.get("price", 0)),
                        status=item.get("orderstatus", ""),
                        order_type=item.get("ordertype", ""),
                    ))
                return orders
            return []
        except Exception as e:
            logger.error(f"Order book error: {e}")
            return []
    
    # ==================== POSITIONS ====================
    
    def get_positions(self) -> list[Position]:
        """Get current open positions."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.position()
            
            if response.get("status") and response.get("data"):
                positions = []
                for item in response["data"]:
                    net_qty = int(item.get("netqty", 0))
                    if net_qty == 0:
                        continue
                    
                    avg_price = float(item.get("averageprice", 0))
                    ltp = float(item.get("ltp", 0))
                    pnl = float(item.get("pnl", 0))
                    
                    # Calculate P&L percent
                    pnl_percent = 0.0
                    if avg_price > 0:
                        pnl_percent = ((ltp - avg_price) / avg_price) * 100
                    
                    positions.append(Position(
                        symbol=item.get("tradingsymbol", ""),
                        token=item.get("symboltoken", ""),
                        exchange=item.get("exchange", ""),
                        product_type=item.get("producttype", ""),
                        quantity=net_qty,
                        average_price=avg_price,
                        ltp=ltp,
                        pnl=pnl,
                        pnl_percent=pnl_percent,
                    ))
                return positions
            return []
        except Exception as e:
            logger.error(f"Position error: {e}")
            return []
    
    def get_holdings(self) -> list[dict]:
        """Get all holdings."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.allholding()
            
            if response.get("status") and response.get("data"):
                return response["data"].get("holdings", [])
            return []
        except Exception as e:
            logger.error(f"Holdings error: {e}")
            return []
    
    # ==================== MARKET SCANNING ====================
    
    def get_gainers_losers(
        self,
        data_type: str = "PercOIGainers",
        expiry_type: str = "NEAR",
    ) -> list[dict]:
        """
        Get market gainers/losers.
        
        Args:
            data_type: One of:
                - PercPriceGainers / PercPriceLosers
                - PercOIGainers / PercOILosers
                - LongBuildUp / ShortBuildUp
                - LongUnwinding / ShortCovering
            expiry_type: NEAR or FAR
            
        Returns:
            List of gainers/losers data
        """
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.gainersLosers({
                "datatype": data_type,
                "expirytype": expiry_type,
            })
            
            if response.get("status") and response.get("data"):
                return response["data"]
            return []
        except Exception as e:
            logger.error(f"Gainers/Losers error: {e}")
            return []
    
    def get_nse_intraday_movers(self) -> list[dict]:
        """Get NSE intraday top movers."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.nseIntraday()
            
            if response.get("status") and response.get("data"):
                return response["data"]
            return []
        except Exception as e:
            logger.error(f"NSE Intraday error: {e}")
            return []
    
    def get_bse_intraday_movers(self) -> list[dict]:
        """Get BSE intraday top movers."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.bseIntraday()
            
            if response.get("status") and response.get("data"):
                return response["data"]
            return []
        except Exception as e:
            logger.error(f"BSE Intraday error: {e}")
            return []
    
    # ==================== MARGIN ====================
    
    def get_rms_limits(self) -> dict:
        """Get RMS limits and margins."""
        self._ensure_authenticated()
        
        try:
            response = self.smart_api.rmsLimit()
            
            if response.get("status") and response.get("data"):
                return response["data"]
            return {}
        except Exception as e:
            logger.error(f"RMS limits error: {e}")
            return {}
    
    def get_available_margin(self) -> float:
        """Get available margin for trading."""
        limits = self.get_rms_limits()
        return float(limits.get("availablecash", 0)) + float(limits.get("collateral", 0))
    
    # ==================== WEBSOCKET ====================
    
    def create_websocket(
        self,
        on_data: callable,
        on_open: callable = None,
        on_error: callable = None,
        on_close: callable = None,
    ) -> SmartWebSocketV2:
        """
        Create a WebSocket connection for live streaming.
        
        Args:
            on_data: Callback for tick data
            on_open: Callback when connection opens
            on_error: Callback for errors
            on_close: Callback when connection closes
            
        Returns:
            SmartWebSocketV2 instance
        """
        self._ensure_authenticated()
        
        ws = SmartWebSocketV2(
            auth_token=self._auth_token,
            api_key=self.settings.angel_api_key.get_secret_value(),
            client_code=self.settings.angel_client_id,
            feed_token=self._feed_token,
            max_retry_attempt=3,
        )
        
        ws.on_data = on_data
        if on_open:
            ws.on_open = on_open
        if on_error:
            ws.on_error = on_error
        if on_close:
            ws.on_close = on_close
        
        return ws
    
    def subscribe_symbols(
        self,
        ws: SmartWebSocketV2,
        exchange: str,
        tokens: list[str],
        mode: int = 2,  # 1=LTP, 2=Quote, 3=SnapQuote
    ) -> None:
        """Subscribe to live data for symbols."""
        exchange_type = self.EXCHANGE_TYPE_MAP.get(exchange, 1)
        
        token_list = [{
            "exchangeType": exchange_type,
            "tokens": tokens,
        }]
        
        ws.subscribe("finbot_sub", mode, token_list)
        logger.info(f"Subscribed to {len(tokens)} symbols on {exchange}")
    
    # ==================== HELPERS ====================
    
    def _ensure_authenticated(self) -> None:
        """Ensure the client is authenticated."""
        if not self._is_authenticated:
            raise Exception("Not authenticated. Call login() first.")


# Singleton instance
_client: Optional[AngelOneClient] = None


def get_angel_client() -> AngelOneClient:
    """Get or create Angel One client singleton."""
    global _client
    if _client is None:
        _client = AngelOneClient()
    return _client
