# l3_engine/core/order_book.py
import logging
from decimal import Decimal
from typing import Dict, Optional, Tuple, Any
from datetime import datetime

from ..domain.enums import Side
from ..domain.events import MarketData_DepthEvent, OrderCommand

try:
    from sortedcontainers import SortedDict
except ImportError:
    print("Error: 'sortedcontainers' library not found. Please install it: pip install sortedcontainers")
    SortedDict = dict
    print("Warning: Using standard dict for order book - less efficient.")

logger = logging.getLogger(__name__)

class OrderBook:
    """Maintains LOB state and provides methods for BBO and quantity estimation."""
    def __init__(self, symbol: str, tick_size: Decimal, initialize_synthetic_data: bool = False):
        self.symbol = symbol
        self.tick_size = tick_size
        self.bids: SortedDict = SortedDict(lambda k: -k)
        self.asks: SortedDict = SortedDict()
        self.last_update_time: int = 0
        self.best_bid: Optional[Decimal] = None
        self.best_ask: Optional[Decimal] = None

        if initialize_synthetic_data:
            self._initialize_synthetic_data()

    def process_depth_event(self, event: MarketData_DepthEvent):
        """Updates the order book based on a MarketData_DepthEvent."""
        if event.symbol != self.symbol or event.timestamp < self.last_update_time:
            return

        self.last_update_time = event.timestamp
        book_side = self.bids if event.side == Side.SELL else self.asks
        price = event.price

        is_bid_side = event.side == Side.SELL

        if event.command == OrderCommand.DELETE or (event.command == OrderCommand.UPDATE and event.quantity <= 0):
            if price in book_side:
                del book_side[price]
        elif event.command in [OrderCommand.INSERT, OrderCommand.UPDATE]:
            if event.quantity > 0:
                book_side[price] = {'qty': event.quantity, 'num_orders': event.num_orders}
            elif price in book_side:
                del book_side[price]

        self.best_bid = next(iter(self.bids), None)
        self.best_ask = next(iter(self.asks), None)

        if self.best_bid is not None and self.best_ask is not None and self.best_bid >= self.best_ask:
            logger.warning(f"[{self.symbol}] Book crossed at {datetime.fromtimestamp(event.timestamp/1e9)}: Bid {self.best_bid} >= Ask {self.best_ask}")

    def get_bbo(self) -> Tuple[Optional[Decimal], int, Optional[Decimal], int]:
        """Returns the current Best Bid/Offer price and quantity."""
        bid_price = self.best_bid
        bid_qty = self.bids[bid_price]['qty'] if bid_price and bid_price in self.bids else 0
        ask_price = self.best_ask
        ask_qty = self.asks[ask_price]['qty'] if ask_price and ask_price in self.asks else 0
        return bid_price, bid_qty, ask_price, ask_qty

    def get_level_data(self, price: Decimal, side: Side) -> Optional[Dict[str, Any]]:
        """Gets data for a specific price level. Side.SELL for Bids, Side.BUY for Asks."""
        book_side = self.bids if side == Side.SELL else self.asks
        return book_side.get(price)

    def estimate_quantity_ahead(self, order_price: Decimal, order_side: Side) -> Decimal:
        """Estimates quantity at levels *better* than the order price on the SAME side of the book."""
        qty_ahead = Decimal(0)
        if order_side == Side.BUY: # A Buy Limit Order sits on the BID side. Better prices are HIGHER.
            for price in self.bids.irange(minimum=order_price, inclusive=(False, False)):
                qty_ahead += self.bids[price]['qty']
        elif order_side == Side.SELL: # A Sell Limit Order sits on the ASK side. Better prices are LOWER.
            for price in self.asks.irange(maximum=order_price, inclusive=(False, False)):
                qty_ahead += self.asks[price]['qty']
        return qty_ahead

    def _initialize_synthetic_data(self):
        """Initialize the order book with synthetic data for testing scenarios."""
        logger.info("Initializing order book with synthetic data for testing.")
        base_price = Decimal('5950.00')
        for i in range(10):
            self.bids[base_price - (i * self.tick_size)] = {'qty': 100 * (10 - i), 'num_orders': 5}
            self.asks[base_price + self.tick_size + (i * self.tick_size)] = {'qty': 100 * (i + 1), 'num_orders': 5}
        self.best_bid = next(iter(self.bids), None)
        self.best_ask = next(iter(self.asks), None)