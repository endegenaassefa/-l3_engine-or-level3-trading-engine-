# l3_engine/strategy/footprint_diagonal.py
import collections
import logging
from decimal import Decimal
from typing import Deque, Dict, Union, Optional
from datetime import datetime

from .base import Strategy
from ..core.order_book import OrderBook
from ..domain.events import Event, FillEvent, OrderEvent, MarketData_TradeEvent, MarketData_DepthEvent
from ..domain.enums import Side, OrderType, ZeroCompareAction, EventType, OrderStatus

logger = logging.getLogger(__name__)

class FootprintDiagonalRatioStrategy(Strategy):
    """
    Calculates Ask/Bid Diagonal Ratio based on a Volume-at-Price profile
    within time-based bars.
    """
    def __init__(self, symbol: str, event_queue: Deque[Event], params: dict, order_book_ref: OrderBook):
        super().__init__(symbol, event_queue, params, order_book_ref)
        self.tick_size = params['tick_size']
        self.percentage_threshold = Decimal(str(params.get('percentage_threshold', 150.0)))
        self.enable_zero_compares = params.get('enable_zero_compares', False)
        self.zero_compare_action = ZeroCompareAction(params.get('zero_compare_action', 0))
        self.stop_ticks = params.get('stop_ticks', 11)
        self.risk_reward = Decimal(str(params.get('risk_reward', 2.5)))
        self.bar_interval_minutes = params.get('bar_interval_minutes', 1)
        self.bar_interval_ns = int(self.bar_interval_minutes * 60 * 1e9)
        self.min_liquidity_check = params.get('min_liquidity_check', 0)
        self.current_bar_start_time: Optional[int] = None
        self.volume_profile: Dict[Decimal, Dict[str, int]] = collections.defaultdict(lambda: {'bid_vol': 0, 'ask_vol': 0})

    def _reset_bar_state(self, timestamp: int):
        """Resets the volume profile and aligns the bar start time."""
        self.volume_profile.clear()
        dt_object = datetime.fromtimestamp(timestamp / 1e9)
        bar_minute = (dt_object.minute // self.bar_interval_minutes) * self.bar_interval_minutes
        aligned_dt = dt_object.replace(minute=bar_minute, second=0, microsecond=0)
        self.current_bar_start_time = int(aligned_dt.timestamp() * 1e9)

    def on_market_data(self, event: Union[MarketData_TradeEvent, MarketData_DepthEvent]):
        """Processes tick data to build Volume-at-Price profile for the current bar."""
        if not isinstance(event, MarketData_TradeEvent) or event.symbol != self.symbol:
            return

        if self.current_bar_start_time is None:
            self._reset_bar_state(event.timestamp)

        if event.timestamp >= self.current_bar_start_time + self.bar_interval_ns:
            if self.volume_profile:
                self._calculate_and_signal(self.current_bar_start_time + self.bar_interval_ns - 1)
            self._reset_bar_state(event.timestamp)

        if event.side == Side.SELL: self.volume_profile[event.price]['bid_vol'] += event.quantity
        elif event.side == Side.BUY: self.volume_profile[event.price]['ask_vol'] += event.quantity

    def _calculate_and_signal(self, timestamp: int):
        """Calculates diagonal ratio for all relevant price levels and generates signals."""
        if not self.volume_profile or self.active_order_id: return

        prices_with_bids = sorted([p for p, v in self.volume_profile.items() if v['bid_vol'] > 0])
        for price_bid in prices_with_bids:
            bid_vol = Decimal(self.volume_profile[price_bid]['bid_vol'])
            price_ask_diag = price_bid + self.tick_size
            ask_vol_diag = Decimal(self.volume_profile.get(price_ask_diag, {}).get('ask_vol', 0))

            perc_ratio, skip_calc = Decimal(0), False
            d_bid, d_ask = bid_vol, ask_vol_diag
            
            if d_bid == 0 or d_ask == 0:
                if not self.enable_zero_compares: continue
                if self.zero_compare_action == ZeroCompareAction.SET_0_TO_1:
                    if d_bid == 0: d_bid = Decimal(1)
                    if d_ask == 0: d_ask = Decimal(1)
                elif self.zero_compare_action == ZeroCompareAction.SET_PERC_1000:
                    perc_ratio = Decimal(1000) if d_bid == 0 else Decimal(-1000)
                    skip_calc = True
            
            if not skip_calc:
                if ask_vol_diag >= bid_vol:
                    perc_ratio = (d_ask / d_bid) * 100 if d_bid > 0 else Decimal(1000)
                else:
                    perc_ratio = (d_bid / d_ask) * -100 if d_ask > 0 else Decimal(-1000)
            
            signal_dir, trigger_price = None, None
            if perc_ratio > 0 and perc_ratio >= self.percentage_threshold:
                signal_dir, trigger_price = Side.BUY, price_ask_diag
            elif perc_ratio < 0 and perc_ratio <= -self.percentage_threshold:
                signal_dir, trigger_price = Side.SELL, price_bid

            if signal_dir is not None and self.current_position == 0:
                if self.min_liquidity_check > 0:
                    _, bbo_bid_q, _, bbo_ask_q = self.order_book.get_bbo()
                    if (signal_dir == Side.BUY and bbo_ask_q < self.min_liquidity_check) or \
                       (signal_dir == Side.SELL and bbo_bid_q < self.min_liquidity_check):
                        continue

                stop_dist = Decimal(self.stop_ticks) * self.tick_size
                target_dist = stop_dist * self.risk_reward
                stop_price = trigger_price - stop_dist if signal_dir == Side.BUY else trigger_price + stop_dist
                target_price = trigger_price + target_dist if signal_dir == Side.BUY else trigger_price - target_dist
                
                self._generate_signal(
                    direction=signal_dir, order_type=OrderType.MARKET, quantity=1,
                    signal_trigger_price=trigger_price, signal_stop_price=stop_price, signal_target_price=target_price,
                    timestamp=timestamp
                )
                return

    def on_fill(self, event: FillEvent):
        """Updates strategy position based on fills."""
        if event.strategy_id != self.strategy_id: return
        direction_multiplier = 1 if event.direction == Side.BUY else -1
        self.current_position += (event.quantity_filled * direction_multiplier)
        if self.current_position == 0:
            self.active_order_id = None # Position closed, ready for new entry
        logger.info(f"[{self.strategy_id}] Position updated to: {self.current_position}")

    def on_order_status(self, event: OrderEvent):
        """Updates internal state based on order status changes."""
        if event.strategy_id != self.strategy_id: return
        if event.status in [OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED]:
            if not event.parent_order_id: # Only release lock on terminal status of top-level orders
                self.active_order_id = None