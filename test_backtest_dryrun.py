import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'src'))

from datetime import datetime, timedelta
from loguru import logger
from finbot.backtest.engine import BacktestEngine
from finbot.backtest.universe import get_universe, BacktestSymbol

def test_dry_run():
    logger.info("Starting Dry Run Test...")
    
    # Mocking data loader to avoid API calls or assuming cache presence
    # Actually, we can just instantiate the Engine and check imports.
    
    start = datetime.now() - timedelta(days=5)
    end = datetime.now()
    
    engine = BacktestEngine(start, end)
    logger.info("Engine instantiated successfully")
    
    # Check Universe
    universe = get_universe()
    logger.info(f"Universe loaded with {len(universe.resolved_symbols)} resolved symbols (initially empty)")
    
    # We won't call run() because it requires Angel API creds which might fail in this env,
    # or it will try to make network calls.
    # But we verified the code structure.
    
    logger.info("Test Passed: Modules import correctly and classes instantiate.")

if __name__ == "__main__":
    test_dry_run()
