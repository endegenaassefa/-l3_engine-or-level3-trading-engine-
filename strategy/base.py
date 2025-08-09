# l3_engine/strategy/base.py
import abc
from decimal import Decimal
from typing import Deque, Union, Optional
import logging

from ..domain.events import Event, FillEvent, OrderEvent, SignalEvent, MarketData_TradeEvent, MarketData_DepthEvent
from ..domain.enums import Side, OrderType
from ..core.order_book import OrderBook

logger = logging.getLogger(__name__)

class Strategy(abc.ABC):
    """Abstract base class for all trading strategies."""
    def __init__(self, symbol: str, event_queue: Deque[Event], params: dict, order_book_ref: OrderBook):
        self.symbol = symbol
        self.event_queue = event_queue
        self.params = params
        self.order_book = order_book_ref
        self.strategy_id = f"{self.__class__.__name__}_{symbol}"
        self.active_order_id: Optional[str] = None
        self.current_position: int = 0

    def _generate_signal(self, direction: Side, order_type: OrderType, quantity: int,
                         limit_price: Optional[Decimal] = None, stop_price: Optional[Decimal] = None,
                         signal_trigger_price: Optional[Decimal] = None,
                         signal_stop_price: Optional[Decimal] = None,
                         signal_target_price: Optional[Decimal] = None,
                         timestamp: Optional[int] = None):
        """Helper method to create and queue SignalEvents."""
        if self.active_order_id is not None:
            logger.debug(f"[{self.strategy_id}] Signal blocked: Active order exists.")
            return

        signal_time = timestamp if timestamp is not None else self.order_book.last_update_time
        sig = SignalEvent(
            timestamp=signal_time, event_type=EventType.SIGNAL,
            strategy_id=self.strategy_id, symbol=self.symbol,
            direction=direction, order_type=order_type, quantity=quantity,
            limit_price=limit_price, stop_price=stop_price,
            signal_trigger_price=signal_trigger_price,
            signal_stop_price=signal_stop_price,
            signal_target_price=signal_target_price
        )
        self.event_queue.append(sig)
        logger.info(f"[{self.strategy_id}] Generated Signal: {sig.direction.name} {sig.quantity} at {sig.signal_trigger_price}")
        self.active_order_id = "PENDING_ENTRY" # Mark that a signal is out

    @abc.abstractmethod
    def on_market_data(self, event: Union[MarketData_TradeEvent, MarketData_DepthEvent]):
        """Called on every market data event."""
        raise NotImplementedError

    @abc.abstractmethod
    def on_fill(self, event: FillEvent):
        """Called when one of the strategy's orders is filled."""
        raise NotImplementedError

    @abc.abstractmethod
    def on_order_status(self, event: OrderEvent):
        """Called on any status update for one of the strategy's orders."""
        raise NotImplementedError