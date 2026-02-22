import sys
import os

# Add root dir to sys.path
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from src.utils.helpers import load_config
from src.core.order_executor import OrderExecutor

def reset_all():
    config = load_config()
    print(f"Running reset in mode: {config['trading']['mode']}")
    executor = OrderExecutor(config)
    
    print("Canceling all pending orders...")
    executor.cancel_all_orders()
    
    print("Fetching open positions...")
    positions = executor.get_all_positions_standardized()
    
    if not positions:
        print("No open positions found.")
    else:
        for pos in positions:
            print(f"Closing position: {pos['pair']} | Side: {pos['side']} | Qty: {pos['qty']}")
            executor.close_position(pos["pair"], pos["qty"], pos["side"])
            
    print("Reset Binance exchange complete.")

if __name__ == "__main__":
    reset_all()
