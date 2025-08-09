# L3 Engine - Level 3 Trading Backtesting Framework

A sophisticated algorithmic trading backtesting engine with Level 3 market data processing capabilities, designed for high-performance strategy development and analysis.

## Features

- **Level 3 Market Data Processing** - Full order book depth and trade-by-trade analysis
- **Event-Driven Architecture** - Realistic event sequencing and timing simulation
- **Portfolio Management** - Comprehensive position tracking and P&L calculation  
- **Execution Simulation** - Market impact modeling with configurable latencies
- **Performance Analytics** - Detailed performance metrics and visualization
- **Strategy Framework** - Extensible base classes for custom strategy development

## Project Structure

```
l3_engine/
├── analysis/          # Performance analysis and reporting
├── core/             # Core trading engine components
│   ├── execution.py  # Order execution and fill simulation
│   ├── order_book.py # Level 3 order book management
│   └── portfolio.py  # Portfolio and position tracking
├── data/             # Data loading and management
├── domain/           # Domain models and event definitions
├── strategy/         # Trading strategy implementations
└── backtest.py       # Main backtesting controller
```

## Quick Start

### Basic Configuration

```python
config = {
    'symbol': 'ES',
    'db_path': 'path/to/your/market_data.db',
    'tick_size': 0.25,
    'tick_value': 12.50,
    'capital': 100000,
    'commission': 2.50,
    'latency_data_signal_us': 100,
    'latency_signal_order_us': 50,
    'strategy_params': {
        'lookback_periods': 20,
        'entry_threshold': 1.5
    }
}
```

### Running a Backtest

```python
from l3_engine.backtest import BacktestController

# Initialize and run backtest
controller = BacktestController(config)
controller.run()
```

### Test Scenarios

The engine supports synthetic test scenarios for strategy validation:

```python
config['test_scenario'] = 'long_target'  # Test long position hitting target
config['test_scenario'] = 'short_stop'   # Test short position hitting stop
```

## Strategy Development

Extend the base strategy class to implement custom trading logic:

```python
from l3_engine.strategy.base import BaseStrategy

class MyStrategy(BaseStrategy):
    def on_market_data(self, event):
        # Implement your trading logic here
        pass
    
    def on_fill(self, event):
        # Handle fill events
        pass
```

## Data Requirements

The engine expects SQLite databases with Level 3 market data in the following format:
- Market depth events (bid/ask levels)
- Trade-by-trade data with timestamps
- Proper event sequencing for realistic simulation

## Performance Analysis

The built-in performance analyzer provides:
- Sharpe ratio and risk metrics
- Maximum drawdown analysis
- Equity curve visualization
- Trade-by-trade analysis

## Configuration Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `symbol` | Trading instrument | `'ES'` |
| `tick_size` | Minimum price increment | `0.25` |
| `tick_value` | Dollar value per tick | `12.50` |
| `capital` | Initial capital | `100000` |
| `commission` | Per-contract commission | `2.50` |
| `latency_data_signal_us` | Data-to-signal latency (µs) | `100` |
| `latency_signal_order_us` | Signal-to-order latency (µs) | `50` |

## Dependencies

- **pandas** - Data manipulation and analysis
- **numpy** - Numerical computations  
- **matplotlib** - Performance visualization
- **scipy** - Statistical analysis (optional)

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request