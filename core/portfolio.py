# l3_engine/core/portfolio.py
import collections
import logging
from decimal import Decimal
from typing import Dict, List, Tuple, Any
from datetime import datetime

from ..domain.events import FillEvent, MarketData_TradeEvent, OrderEvent
from ..domain.enums import Side

logger = logging.getLogger(__name__)

class Portfolio:
    """Tracks cash, positions, P&L, and equity."""
    def __init__(self, initial_capital: Decimal, commission_per_contract: Decimal, tick_value: Decimal, tick_size: Decimal):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_per_contract = commission_per_contract
        self.tick_value = tick_value
        self.tick_size = tick_size
        self.holdings: Dict[str, int] = collections.defaultdict(int)
        self.positions_avg_price: Dict[str, Decimal] = {}
        self.realized_pnl: Decimal = Decimal(0)
        self.equity_curve: List[Tuple[int, Decimal]] = [(0, initial_capital)]
        self.last_market_price: Dict[str, Decimal] = {}
        self.trade_log: List[Dict[str, Any]] = []
        self.open_positions: Dict[str, Dict[str, Any]] = {}

    def update_market_price(self, event: MarketData_TradeEvent):
        """Updates the last known market price for a symbol."""
        self.last_market_price[event.symbol] = event.price

    def _update_equity(self, timestamp: int):
        """Calculates and records current total equity (cash + unrealized PNL)."""
        unrealized_pnl = Decimal(0)
        for symbol, quantity in self.holdings.items():
            if quantity != 0 and symbol in self.last_market_price and symbol in self.positions_avg_price:
                price_diff = self.last_market_price[symbol] - self.positions_avg_price[symbol]
                pnl_per_contract = (price_diff / self.tick_size) * self.tick_value
                unrealized_pnl += pnl_per_contract * quantity
        
        current_equity = self.cash + unrealized_pnl
        if not self.equity_curve or self.equity_curve[-1][0] < timestamp:
            self.equity_curve.append((timestamp, current_equity))
        elif current_equity != self.equity_curve[-1][1]:
            self.equity_curve[-1] = (timestamp, current_equity)

    def update_fill(self, event: FillEvent):
        """Updates portfolio state based on a fill, managing positions and PNL."""
        symbol, qty, price, comm = event.symbol, event.quantity_filled, event.fill_price, event.commission
        direction = 1 if event.direction == Side.BUY else -1
        pos_change = qty * direction

        self.cash -= (price * Decimal(qty) * Decimal(direction)) + comm
        current_pos = self.holdings[symbol]
        new_pos = current_pos + pos_change

        if current_pos != 0 and new_pos * current_pos <= 0: # Closing or flipping
            qty_closed = min(abs(current_pos), qty)
            entry_details = self.open_positions.get(symbol)
            if entry_details:
                avg_entry_price = entry_details['entry_price']
                pnl_dir = 1 if entry_details['direction'] == 'LONG' else -1
                pnl = (price - avg_entry_price) * pnl_dir * qty_closed
                self.realized_pnl += (pnl / self.tick_size) * self.tick_value
                
                self.trade_log.append({
                    'symbol': symbol, 'entry_time': datetime.fromtimestamp(entry_details['entry_time'] / 1e9),
                    'exit_time': datetime.fromtimestamp(event.fill_time / 1e9),
                    'direction': entry_details['direction'], 'entry_price': avg_entry_price, 'exit_price': price,
                    'quantity': qty_closed, 'pnl': (pnl / self.tick_size) * self.tick_value,
                    'commission': entry_details['commission'] + comm,
                })
                if new_pos == 0:
                    del self.open_positions[symbol]
                    del self.positions_avg_price[symbol]
                else: # Flipped
                    self.positions_avg_price[symbol] = price
                    self.open_positions[symbol] = {'entry_time': event.fill_time, 'entry_price': price,
                                                   'quantity': new_pos, 'direction': 'LONG' if new_pos > 0 else 'SHORT',
                                                   'commission': comm}
        
        elif new_pos != 0: # Opening or adding
            if current_pos == 0: # Opening
                self.positions_avg_price[symbol] = price
                self.open_positions[symbol] = {'entry_time': event.fill_time, 'entry_price': price,
                                               'quantity': new_pos, 'direction': 'LONG' if new_pos > 0 else 'SHORT',
                                               'commission': comm}
            else: # Adding
                old_val = self.positions_avg_price[symbol] * current_pos
                new_val = price * pos_change
                self.positions_avg_price[symbol] = (old_val + new_val) / new_pos
                self.open_positions[symbol]['quantity'] = new_pos
                self.open_positions[symbol]['commission'] += comm

        self.holdings[symbol] = new_pos
        if new_pos == 0: del self.holdings[symbol]
        self._update_equity(event.timestamp)

    def on_order_status(self, event: OrderEvent):
        """Handles non-fill order status updates for logging purposes."""
        logger.debug(f"Portfolio noted Order Status: {event.order_id} -> {event.status.name}")