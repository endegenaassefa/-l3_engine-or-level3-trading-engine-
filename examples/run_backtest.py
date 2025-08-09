# examples/run_backtest.py
import argparse
import logging
import os
import sys

# Add project root to the Python path to allow importing the 'l3_engine' package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from l3_engine.backtest import BacktestController

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - [%(module)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def main():
    """Parses arguments, configures, and runs the backtest."""
    parser = argparse.ArgumentParser(description="L3 Backtester with Footprint Diagonal Ratio Strategy")
    # --- Data Args ---
    parser.add_argument('--db_path', type=str, default="tick.db", help="Path to SQLite database file")
    parser.add_argument('--symbol', type=str, default="ESM25_FUT_CME", help="Symbol to backtest")
    # --- Core Params ---
    parser.add_argument('--capital', type=float, default=100000, help="Initial capital")
    parser.add_argument('--commission', type=float, default=2.50, help="Commission per contract (one side)")
    parser.add_argument('--tick_size', type=float, default=0.25, help="Instrument tick size")
    parser.add_argument('--tick_value', type=float, default=12.50, help="Instrument tick value ($)")
    # --- Latency Args ---
    parser.add_argument('--latency_data_signal_us', type=int, default=100, help="Latency from data to signal decision (us)")
    parser.add_argument('--latency_signal_order_us', type=int, default=500, help="Latency from signal decision to order arrival (us)")
    # --- Strategy Args ---
    parser.add_argument('--percentage_threshold', type=float, default=150.0, help='Diagonal ratio percentage threshold')
    parser.add_argument('--stop_ticks', type=int, default=11, help='Number of ticks for stop loss')
    parser.add_argument('--risk_reward', type=float, default=2.5, help='Risk-reward ratio for target price')
    parser.add_argument('--bar_minutes', type=int, default=1, help='Bar interval in minutes for VAP calculation')
    parser.add_argument('--enable_zero_compares', action='store_true', help='Allow ratio calculation when denominator is zero')
    parser.add_argument('--zero_action', type=int, default=0, choices=[0, 1], help='Action if zero compare enabled: 0=Set 0 to 1, 1=Set Perc to +/-1000')
    parser.add_argument('--min_liq_check', type=int, default=0, help='Min liquidity on opposite side for signal (0 to disable)')
    # --- Other Args ---
    parser.add_argument('--debug', action='store_true', help="Enable debug logging")
    parser.add_argument('--max_events', type=int, default=None, help="Maximum number of events to process")
    parser.add_argument('--test_scenario', type=str, default=None,
                        choices=['short_target', 'short_stop', 'long_target', 'long_stop'],
                        help="Run a specific synthetic test scenario instead of from DB")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled.")

    config = {
        'db_path': args.db_path, 'symbol': args.symbol, 'capital': args.capital,
        'commission': args.commission, 'tick_size': args.tick_size, 'tick_value': args.tick_value,
        'latency_data_signal_us': args.latency_data_signal_us,
        'latency_signal_order_us': args.latency_signal_order_us,
        'max_events': args.max_events, 'test_scenario': args.test_scenario,
        'strategy_params': {
            'percentage_threshold': args.percentage_threshold, 'stop_ticks': args.stop_ticks,
            'risk_reward': args.risk_reward, 'bar_interval_minutes': args.bar_minutes,
            'enable_zero_compares': args.enable_zero_compares, 'zero_compare_action': args.zero_action,
            'min_liquidity_check': args.min_liq_check,
        }
    }

    if not args.test_scenario and not os.path.exists(config['db_path']):
        logger.error(f"Error: Database file not found at {config['db_path']}")
        sys.exit(1)

    try:
        backtester = BacktestController(config)
        backtester.run()
    except Exception as e:
        logger.critical(f"A critical error occurred: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()