"""
Backtest API Endpoints.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
import asyncio
import json

from finbot.backtest.engine import BacktestEngine
from finbot.backtest.reporting import generate_report
from finbot.services.redis_service import RedisService

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

async def run_backtest_task(job_id: str, start: datetime, end: datetime, capital: float, symbols: Optional[List[str]] = None):
    """Background task wrapper."""
    redis_svc = RedisService.get_instance()
    
    try:
        await redis_svc.update_job_status(job_id, "running")
        
        # Login to Angel One for symbol resolution
        from finbot.broker.angel_client import get_angel_client
        client = get_angel_client()
        if not await client.try_restore_session():
            await client.login()
        
        # Initialize Engine (must run in threadpool as it might do IO/CPU)
        engine = BacktestEngine(start, end, capital)
        if symbols:
            # Override universe if provided
            pass  # TODO: Implement symbol override in engine if needed
        
        # Create progress tracking state (thread-safe)
        import threading
        progress_lock = threading.Lock()
        last_progress = {"symbol": "", "done": 0, "total": 0}
        
        def progress_callback(symbol: str, done: int, total: int):
            """Thread-safe progress callback."""
            with progress_lock:
                last_progress["symbol"] = symbol
                last_progress["done"] = done
                last_progress["total"] = total
        
        # Run Backtest (CPU heavy) in threadpool to avoid blocking async loop
        # Run with progress callback
        def run_with_progress():
            return engine.run(progress_callback=progress_callback)
        
        # Start a background task to update Redis periodically with progress
        async def update_progress_periodically():
            while True:
                await asyncio.sleep(2)  # Update every 2 seconds
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
            return  # Don't overwrite cancelled status
        
        # Generate Report
        report = await asyncio.to_thread(generate_report, portfolios)
        
        await redis_svc.update_job_status(job_id, "completed", result=report)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        await redis_svc.update_job_status(job_id, "failed", error=str(e))

@router.post("/run", response_model=BacktestResponse)
async def start_backtest(
    request: BacktestRequest,
    background_tasks: BackgroundTasks
):
    """Start a backtest job."""
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
    """Get status and result of a job."""
    redis_svc = RedisService.get_instance()
    job = await redis_svc.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return job

@router.get("/history/list")
async def list_backtests():
    """List all recent backtests."""
    redis_svc = RedisService.get_instance()
    jobs = await redis_svc.get_recent_jobs()
    
    # Sort by submitted_at desc
    jobs.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    
    # Return minimal info
    summary = []
    for job in jobs:
        summary.append({
            "id": job["id"],
            "status": job["status"],
            "submitted_at": job["submitted_at"],
            "strategies": "All Enabled",
            "progress": job.get("progress")  # Include progress info
        })
        
    return summary

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

