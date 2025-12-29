"""Supabase Auth middleware for FastAPI."""

from typing import Optional
from functools import wraps

from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from loguru import logger

from finbot.database import get_supabase_client


security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Verify Supabase JWT token and return user data."""
    token = credentials.credentials
    
    try:
        supabase = get_supabase_client()
        
        # Verify the JWT token with Supabase
        user_response = supabase.auth.get_user(token)
        
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        
        return {
            "id": user_response.user.id,
            "email": user_response.user.email,
            "role": user_response.user.role,
        }
    
    except Exception as e:
        logger.warning(f"Auth failed: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def optional_auth(
    request: Request,
) -> Optional[dict]:
    """Optional authentication - returns None if not authenticated."""
    auth_header = request.headers.get("Authorization")
    
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    
    try:
        supabase = get_supabase_client()
        user_response = supabase.auth.get_user(token)
        
        if user_response and user_response.user:
            return {
                "id": user_response.user.id,
                "email": user_response.user.email,
                "role": user_response.user.role,
            }
    except Exception:
        pass
    
    return None


def require_auth(func):
    """Decorator to require authentication on a route."""
    @wraps(func)
    async def wrapper(*args, user: dict = Depends(verify_token), **kwargs):
        return await func(*args, user=user, **kwargs)
    return wrapper


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware for authentication checks."""
    
    def __init__(self, app, public_paths: list[str] = None):
        super().__init__(app)
        self.public_paths = public_paths or [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
        ]
    
    async def dispatch(self, request: Request, call_next):
        # Allow OPTIONS requests for CORS preflight
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip auth for public paths
        if any(request.url.path.startswith(p) for p in self.public_paths):
            return await call_next(request)
        
        # Check for API key or JWT
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            # Allow unauthenticated access in paper mode
            from finbot.config import get_settings, TradingMode
            settings = get_settings()
            
            if settings.trading_mode == TradingMode.PAPER:
                return await call_next(request)
            
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication"}
            )
        
        return await call_next(request)
