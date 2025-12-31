"""
Backtest API Endpoints.

Uses Redis for job status/progress and Supabase for results storage.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
import uuid
import asyncio
import threading

from finbot.backtest.engine import BacktestEngine
from finbot.backtest.reporting import generate_report
from finbot.services.redis_service import RedisService
from finbot.database.supabase_client import get_db

router = APIRouter()


class BacktestRequest(BaseModel):
    start_date: datetime
    end_date: datetime
    capital: float = 100000.0
    symbols: Optional[List[str]] = None


class BacktestResponse(BaseModel):
    job_id: str
    status: str
    message: str


async def run_backtest_task(
    job_id: str,
    start: datetime,
    end: datetime,
    capital: float,
    symbols: Optional[List[str]] = None
):
    """Background task to run backtest and store results in Supabase."""
    redis_svc = RedisService.get_instance()
    db = get_db()
    
    # Create Supabase run record
    supabase_run_id = None
    
    try:
        await redis_svc.update_job_status(job_id, "running")
        
        # Create run record in Supabase
        supabase_run_id = await db.create_backtest_run(
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            initial_capital=capital,
            symbols=symbols or [],
        )
        
        # Store Supabase run ID in Redis job for later retrieval
        redis_svc = RedisService.get_instance()
        job = await redis_svc.get_job(job_id)
        if job:
            job["supabase_run_id"] = supabase_run_id
            await redis_svc.update_job_status(job_id, "running", extra_data={"supabase_run_id": supabase_run_id})
        
        # Login to Angel One for symbol resolution
        # IMPORTANT: Always force fresh login - cached tokens may be expired on Angel One's side
        # even if they exist in Redis (the 'Invalid Token' error AG8001)
        from finbot.broker.angel_client import get_angel_client
        client = get_angel_client()
        await client.login()  # Force fresh login, don't use cached session
        
        # Initialize Engine
        engine = BacktestEngine(start, end, capital)
        
        # Create progress tracking state (thread-safe)
        progress_lock = threading.Lock()
        last_progress = {"symbol": "", "done": 0, "total": 0}
        
        def progress_callback(symbol: str, done: int, total: int):
            """Thread-safe progress callback."""
            with progress_lock:
                last_progress["symbol"] = symbol
                last_progress["done"] = done
                last_progress["total"] = total
        
        # Run Backtest with progress callback
        def run_with_progress():
            return engine.run(progress_callback=progress_callback)
        
        # Background task to update Redis periodically with progress
        async def update_progress_periodically():
            while True:
                await asyncio.sleep(2)
                with progress_lock:
                    if last_progress["total"] > 0:
                        await redis_svc.update_job_progress(
                            job_id,
                            last_progress["symbol"],
                            last_progress["done"],
                            last_progress["total"]
                        )
                # Check if backtest completed
                job = await redis_svc.get_job(job_id)
                if job and job.get("status") in ["completed", "failed", "cancelled"]:
                    break
        
        # Start progress updater
        progress_task = asyncio.create_task(update_progress_periodically())
        
        try:
            portfolios = await asyncio.to_thread(run_with_progress)
        finally:
            progress_task.cancel()
            try:
                await progress_task
            except asyncio.CancelledError:
                pass
        
        # Check if job was cancelled during execution
        job = await redis_svc.get_job(job_id)
        if job and job.get("status") == "cancelled":
            await db.update_backtest_run(supabase_run_id, "cancelled")
            return
        
        # Generate comprehensive report
        report = await asyncio.to_thread(generate_report, portfolios)
        
        # Store results in Supabase (NOT Redis)
        await db.update_backtest_run(
            run_id=supabase_run_id,
            status="completed",
            final_capital=report["summary"]["final_capital"],
            summary=report["summary"],
            strategy_breakdown=report["strategy_breakdown"],
            symbol_breakdown=report["symbol_breakdown"],
        )
        
        # Store trades in Supabase
        await db.save_backtest_trades(supabase_run_id, report["trades"])
        
        # Update Redis with just status and summary (no full results)
        await redis_svc.update_job_status(
            job_id, 
            "completed",
            extra_data={
                "supabase_run_id": supabase_run_id,
                "summary": report["summary"],  # Just the summary, not full trades
            }
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        
        # Mark as failed in both Redis and Supabase
        await redis_svc.update_job_status(job_id, "failed", error=str(e))
        if supabase_run_id:
            await db.update_backtest_run(supabase_run_id, "failed")


@router.post("/run", response_model=BacktestResponse)
async def start_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks
):
    """Start a backtest job."""
    days_diff = (request.end_date - request.start_date).days
    
    # Validate date range
    if days_diff < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid date range: end_date must be after start_date"
        )
    
    # Warning message for long backtests (included in response)
    long_backtest_warning = None
    if days_diff > 30:
        long_backtest_warning = (
            f"Note: {days_diff}-day backtest requires significant data. "
            f"First run may be slow while data is cached. Subsequent runs will be faster."
        )
    
    job_id = str(uuid.uuid4())
    redis_svc = RedisService.get_instance()
    
    # Register job in Redis
    job_data = {
        "id": job_id,
        "submitted_at": datetime.now().isoformat(),
        "request": {
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "capital": request.capital,
            "symbols": request.symbols
        }
    }
    
    await redis_svc.register_job(job_id, job_data)
    
    # Run in background
    background_tasks.add_task(
        run_backtest_task,
        job_id,
        request.start_date,
        request.end_date,
        request.capital,
        request.symbols
    )
    
    return BacktestResponse(
        job_id=job_id,
        status="pending",
        message="Backtest submitted successfully"
    )


@router.get("/{job_id}")
async def get_backtest_status(job_id: str):
    """Get status and summary of a job."""
    redis_svc = RedisService.get_instance()
    job = await redis_svc.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job


@router.get("/{job_id}/report")
async def get_backtest_report(job_id: str):
    """
    Get full detailed report for a completed backtest.
    
    Fetches comprehensive data from Supabase including:
    - Overall summary metrics
    - Per-strategy breakdown
    - Per-symbol breakdown
    - All trades
    """
    redis_svc = RedisService.get_instance()
    db = get_db()
    
    # Get job from Redis to find Supabase run ID
    job = await redis_svc.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("status") != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Backtest not completed. Status: {job.get('status')}"
        )
    
    supabase_run_id = job.get("supabase_run_id")
    if not supabase_run_id:
        raise HTTPException(status_code=404, detail="Report data not found")
    
    # Fetch full report from Supabase
    run = await db.get_backtest_run(supabase_run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found in database")
    
    # Fetch trades
    trades = await db.get_backtest_trades(supabase_run_id)
    
    return {
        "id": supabase_run_id,
        "job_id": job_id,
        "created_at": run.get("created_at"),
        "start_date": run.get("start_date"),
        "end_date": run.get("end_date"),
        "initial_capital": run.get("initial_capital"),
        "final_capital": run.get("final_capital"),
        "status": run.get("status"),
        "summary": run.get("summary", {}),
        "strategy_breakdown": run.get("strategy_breakdown", {}),
        "symbol_breakdown": run.get("symbol_breakdown", {}),
        "trades": trades,
    }


@router.get("/history/list")
async def list_backtests():
    """List all recent backtests from Supabase."""
    db = get_db()
    
    # Get recent runs from Supabase (more persistent than Redis)
    runs = await db.get_recent_backtest_runs(limit=20)
    
    return [
        {
            "id": run.get("id"),
            "created_at": run.get("created_at"),
            "start_date": run.get("start_date"),
            "end_date": run.get("end_date"),
            "initial_capital": run.get("initial_capital"),
            "final_capital": run.get("final_capital"),
            "status": run.get("status"),
            "summary": run.get("summary", {}),
        }
        for run in runs
    ]


@router.post("/{job_id}/cancel")
async def cancel_backtest(job_id: str):
    """Cancel a running or pending backtest job."""
    redis_svc = RedisService.get_instance()
    
    success = await redis_svc.cancel_job(job_id)
    
    if not success:
        raise HTTPException(
            status_code=400,
            detail="Job not found or already completed/cancelled"
        )
    
    return {"status": "cancelled", "job_id": job_id, "message": "Job cancelled successfully"}
