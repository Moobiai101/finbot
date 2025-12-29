"""FastAPI main application entry point."""

import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from finbot.config import get_settings
from finbot.api.routes import router as api_router
from finbot.database.supabase_client import get_supabase_client


def setup_logging() -> None:
    """Configure loguru logging."""
    settings = get_settings()
    
    # Remove default handler
    logger.remove()
    
    # Add console handler with custom format
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        colorize=True,
    )
    
    # Add file handler for production
    logger.add(
        "logs/finbot_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management."""
    settings = get_settings()
    
    # Startup
    logger.info("🚀 Starting Finbot Trading Engine...")
    logger.info(f"Trading Mode: {settings.trading_mode.value}")
    logger.info(f"Capital: ₹{settings.trading_capital:,.2f}")
    logger.info(f"Max Position Value: ₹{settings.max_position_value:,.2f}")
    
    # Initialize Supabase connection
    try:
        supabase = get_supabase_client()
        logger.info("✅ Supabase connected")
    except Exception as e:
        logger.warning(f"⚠️ Supabase connection failed: {e}")
    
    # Start background trading loop
    import asyncio
    from fastapi.concurrency import run_in_threadpool
    from finbot.execution import get_executor
    
    async def trading_loop():
        logger.info("🔄 Background trading loop started")
        while True:
            try:
                executor = get_executor()
                if executor.is_running:
                    # Run potentially blocking trading logic in threadpool
                    await run_in_threadpool(executor.run_trading_loop)
                await asyncio.sleep(5)  # 5 second interval
            except Exception as e:
                logger.error(f"Error in trading loop: {e}")
                await asyncio.sleep(5)  # Prevent tight loop on error
                
    task = asyncio.create_task(trading_loop())
    
    yield
    
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("🛑 Shutting down Finbot Trading Engine...")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    setup_logging()
    settings = get_settings()
    
    app = FastAPI(
        title="Finbot Trading API",
        description="Production-grade algorithmic trading bot for Indian stock markets",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.trading_mode != "live" else None,
        redoc_url="/redoc" if settings.trading_mode != "live" else None,
    )
    
    # Auth Middleware - added FIRST so it runs AFTER CORS
    from finbot.api.auth import AuthMiddleware
    app.add_middleware(AuthMiddleware)
    
    # CORS middleware - added SECOND so it runs FIRST (handles OPTIONS preflight)
    # Using ["*"] for origins since FastAPI doesn't support wildcard patterns
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://ac956692.finbotfrontend.pages.dev",  # Production Frontend
            "http://localhost:5173",  # Local Dev
            "http://localhost:4173",  # Local Preview
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Security Headers
    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
    
    # Root endpoint
    @app.get("/")
    async def root():
        return {"message": "Finbot Trading API", "version": "0.1.0", "status": "running"}

    # Include API routes
    app.include_router(api_router, prefix="/api/v1")
    
    return app


# Create app instance
app = create_app()


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    settings = get_settings()
    return {
        "status": "healthy",
        "mode": settings.trading_mode.value,
        "version": "0.1.0",
    }
