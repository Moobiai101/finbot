"""API routes for the trading bot."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from finbot.config import get_settings, TradingMode
from finbot.database import get_db, SupabaseDB


router = APIRouter(tags=["trading"])


# ==================== REQUEST/RESPONSE MODELS ====================

class TradingModeRequest(BaseModel):
    """Request to change trading mode."""
    mode: TradingMode


class TradingModeResponse(BaseModel):
    """Response with current trading mode."""
    mode: str
    capital: float
    max_position_value: float
    max_daily_loss: float


class TradeResponse(BaseModel):
    """Trade record response."""
    id: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: Optional[float]
    pnl: Optional[float]
    strategy: str
    mode: str
    created_at: str


class SystemStatusResponse(BaseModel):
    """System status response."""
    mode: str
    is_market_open: bool
    current_time: str
    capital: float
    today_pnl: float
    open_positions: int
    trades_today: int


class DashboardResponse(BaseModel):
    """Dashboard data response."""
    status: SystemStatusResponse
    recent_trades: list[TradeResponse]
    strategies: list[dict]


# ==================== DEPENDENCIES ====================

def get_database() -> SupabaseDB:
    """Dependency for database access."""
    return get_db()


# ==================== ROUTES ====================

@router.get("/status", response_model=SystemStatusResponse)
async def get_system_status(db: SupabaseDB = Depends(get_database)):
    """Get current system status."""
    settings = get_settings()
    
    # Get current trading mode from DB or fallback to config
    current_mode = await db.get_trading_mode()
    
    # Get today's trades
    today_trades = await db.get_today_trades(mode=current_mode)
    
    # Calculate today's P&L
    today_pnl = sum(t.get("pnl", 0) or 0 for t in today_trades)
    
    # Count open positions (trades without exit_price)
    open_positions = len([t for t in today_trades if t.get("exit_price") is None])
    
    # Check if market is open (9:15 AM - 3:30 PM IST)
    now = datetime.now(timezone.utc)
    ist_hour = (now.hour + 5) % 24 + (30 // 60)  # Approximate IST
    is_market_open = 9 <= ist_hour < 16  # Simplified check
    
    return SystemStatusResponse(
        mode=current_mode,
        is_market_open=is_market_open,
        current_time=now.isoformat(),
        capital=settings.trading_capital,
        today_pnl=today_pnl,
        open_positions=open_positions,
        trades_today=len(today_trades),
    )


@router.get("/mode", response_model=TradingModeResponse)
async def get_trading_mode(db: SupabaseDB = Depends(get_database)):
    """Get current trading mode and parameters."""
    settings = get_settings()
    current_mode = await db.get_trading_mode()
    
    return TradingModeResponse(
        mode=current_mode,
        capital=settings.trading_capital,
        max_position_value=settings.max_position_value,
        max_daily_loss=settings.max_daily_loss_amount,
    )


@router.post("/mode", response_model=TradingModeResponse)
async def set_trading_mode(
    request: TradingModeRequest,
    db: SupabaseDB = Depends(get_database),
):
    """Set trading mode (paper/live/backtest)."""
    settings = get_settings()
    
    # Log the mode change
    await db.log_action(
        action="MODE_CHANGE",
        details={
            "old_mode": await db.get_trading_mode(),
            "new_mode": request.mode.value,
        },
    )
    
    # Update mode
    await db.set_trading_mode(request.mode.value)
    logger.info(f"Trading mode changed to: {request.mode.value}")
    
    return TradingModeResponse(
        mode=request.mode.value,
        capital=settings.trading_capital,
        max_position_value=settings.max_position_value,
        max_daily_loss=settings.max_daily_loss_amount,
    )


@router.get("/trades", response_model=list[TradeResponse])
async def get_trades(
    mode: Optional[str] = Query(None, description="Filter by mode"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: SupabaseDB = Depends(get_database),
):
    """Get trade history."""
    trades = await db.get_trades(mode=mode, limit=limit, offset=offset)
    
    return [
        TradeResponse(
            id=t["id"],
            symbol=t["symbol"],
            side=t["side"],
            quantity=t["quantity"],
            entry_price=t["entry_price"],
            exit_price=t.get("exit_price"),
            pnl=t.get("pnl"),
            strategy=t["strategy"],
            mode=t["mode"],
            created_at=t["created_at"],
        )
        for t in trades
    ]


@router.get("/trades/today", response_model=list[TradeResponse])
async def get_today_trades(db: SupabaseDB = Depends(get_database)):
    """Get today's trades."""
    current_mode = await db.get_trading_mode()
    trades = await db.get_today_trades(mode=current_mode)
    
    return [
        TradeResponse(
            id=t["id"],
            symbol=t["symbol"],
            side=t["side"],
            quantity=t["quantity"],
            entry_price=t["entry_price"],
            exit_price=t.get("exit_price"),
            pnl=t.get("pnl"),
            strategy=t["strategy"],
            mode=t["mode"],
            created_at=t["created_at"],
        )
        for t in trades
    ]


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: SupabaseDB = Depends(get_database)):
    """Get dashboard data."""
    status = await get_system_status(db)
    trades = await get_trades(limit=10, db=db)
    
    # Get enabled strategies
    strategies_config = await db.get_config("strategies") or {}
    strategies = [
        {"name": "ORB", "enabled": strategies_config.get("orb", True)},
        {"name": "VWAP Bounce", "enabled": strategies_config.get("vwap_bounce", True)},
        {"name": "Engulfing at Levels", "enabled": strategies_config.get("engulfing", True)},
        {"name": "EMA Pullback", "enabled": strategies_config.get("ema_pullback", True)},
        {"name": "Break & Retest", "enabled": strategies_config.get("break_retest", True)},
    ]
    
    return DashboardResponse(
        status=status,
        recent_trades=trades,
        strategies=strategies,
    )


@router.get("/config/strategies")
async def get_strategy_config(db: SupabaseDB = Depends(get_database)):
    """Get strategy configuration."""
    config = await db.get_config("strategies") or {
        "orb": True,
        "vwap_bounce": True,
        "engulfing": True,
        "ema_pullback": True,
        "break_retest": True,
    }
    
    return {"strategies": config}


@router.post("/config/strategies")
async def update_strategy_config(
    config: dict,
    db: SupabaseDB = Depends(get_database),
):
    """Update strategy configuration."""
    await db.set_config("strategies", config)
    await db.log_action("STRATEGY_CONFIG_UPDATE", details=config)
    
    # Sync with live strategy registry
    try:
        from finbot.strategies import get_strategy_registry
        registry = get_strategy_registry()
        
        strategy_map = {
            "orb": "ORB",
            "vwap_bounce": "VWAP_BOUNCE",
            "engulfing": "ENGULFING_LEVELS",
            "ema_pullback": "EMA_PULLBACK",
            "break_retest": "BREAK_RETEST",
        }
        
        for config_key, strategy_name in strategy_map.items():
            if config_key in config:
                if config[config_key]:
                    registry.enable(strategy_name)
                else:
                    registry.disable(strategy_name)
    except Exception as e:
        logger.warning(f"Could not sync strategy config: {e}")
    
    return {"message": "Strategy configuration updated", "strategies": config}


# ==================== EXECUTOR CONTROL ====================

@router.get("/executor/status")
async def get_executor_status():
    """Get trading executor status."""
    try:
        from finbot.execution import get_executor
        executor = get_executor()
        return executor.get_status()
    except Exception as e:
        logger.error(f"Executor status error: {e}")
        return {"error": str(e), "is_running": False}


@router.post("/executor/start")
async def start_executor(db: SupabaseDB = Depends(get_database)):
    """Start the trading executor."""
    try:
        from finbot.execution import get_executor
        executor = get_executor()
        
        success = await executor.initialize()
        
        if success:
            await db.log_action("EXECUTOR_START", details={"mode": executor.settings.trading_mode.value})
            executor.is_running = True
            executor.run_pre_market()
            
            return {
                "message": "Executor started successfully",
                "mode": executor.settings.trading_mode.value,
                "watchlist_count": len(executor.watchlist),
            }
        else:
            return {"error": "Failed to initialize executor"}
            
    except Exception as e:
        logger.error(f"Executor start error: {e}")
        return {"error": str(e)}


@router.post("/executor/stop")
async def stop_executor(db: SupabaseDB = Depends(get_database)):
    """Stop the trading executor."""
    try:
        from finbot.execution import get_executor
        executor = get_executor()
        
        # Square off all positions
        executor._square_off_all()
        executor.is_running = False
        
        await db.log_action("EXECUTOR_STOP", details=executor.get_status())
        
        return {"message": "Executor stopped", "status": executor.get_status()}
        
    except Exception as e:
        logger.error(f"Executor stop error: {e}")
        return {"error": str(e)}


@router.get("/strategies/live")
async def get_live_strategies():
    """Get live strategy registry status."""
    try:
        from finbot.strategies import get_strategy_registry
        registry = get_strategy_registry()
        
        return {
            "strategies": registry.get_strategy_stats(),
            "enabled_count": len(registry.get_enabled_strategies()),
        }
    except Exception as e:
        logger.error(f"Live strategies error: {e}")
        return {"error": str(e)}


@router.get("/risk/status")
async def get_risk_status():
    """Get risk engine status."""
    try:
        from finbot.risk import get_risk_engine
        risk_engine = get_risk_engine()
        
        return risk_engine.get_status()
    except Exception as e:
        logger.error(f"Risk status error: {e}")
        return {"error": str(e)}


@router.post("/risk/reset")
async def reset_risk_daily(db: SupabaseDB = Depends(get_database)):
    """Reset risk engine daily counters."""
    try:
        from finbot.risk import get_risk_engine
        risk_engine = get_risk_engine()
        
        risk_engine.reset_daily()
        
        await db.log_action("RISK_RESET", details={"action": "daily_reset"})
        
        return {"message": "Risk counters reset", "status": risk_engine.get_status()}
    except Exception as e:
        logger.error(f"Risk reset error: {e}")
        return {"error": str(e)}


# Include Backtest Router
from finbot.api.endpoints.backtest import router as backtest_router
router.include_router(backtest_router, prefix="/backtest", tags=["backtest"])
