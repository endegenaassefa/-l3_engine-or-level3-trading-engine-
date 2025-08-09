# l3_engine/core/execution.py
import logging
import time
from decimal import Decimal
from typing import Deque, Dict, Any, Optional
from datetime import datetime

from .order_book import OrderBook
from ..domain.events import SignalEvent, OrderEvent, FillEvent, MarketData_TradeEvent, Event
from ..domain.enums import EventType, OrderType, OrderStatus, Side

logger = logging.getLogger(__name__)

class ExecutionHandler:
    """
    Simulates execution with latency, slippage, and order management.
    Handles market, limit, and stop orders, including OCO logic for exits.
    """
    def __init__(self, event_queue: Deque[Event], order_book: OrderBook, params: dict):
        self.event_queue = event_queue
        self.order_book = order_book
        self.tick_size = params['tick_size']
        self.latency_data_signal_ns = params.get('latency_data_signal_ns', 100 * 1000)
        self.latency_signal_order_ns = params.get('latency_signal_order_ns', 500 * 1000)
        self.commission_per_contract = params['commission_per_contract']
        self.order_counter = 0
        self.submitted_orders: Dict[str, OrderEvent] = {}
        self.pending_limit_orders: Dict[str, Dict[str, Any]] = {}
        self.pending_stop_orders: Dict[str, OrderEvent] = {}
        self.linked_exit_orders: Dict[str, Dict[str, Optional[str]]] = {}

    def _generate_order_id(self, prefix="SIM") -> str:
        self.order_counter += 1
        return f"{prefix}_{self.order_counter}_{int(time.time_ns())}"

    def _update_order_status(self, order_id: str, status: OrderStatus, timestamp: int, filled_qty: Optional[int] = None):
        """Helper to create and queue an OrderEvent for status updates."""
        original_order = self.submitted_orders.get(order_id)
        if not original_order:
            logger.warning(f"Could not find original order {order_id} to update status to {status.name}.")
            return

        current_filled = filled_qty if filled_qty is not None else original_order.filled_quantity
        if status == OrderStatus.PARTIALLY_FILLED:
            original_order.filled_quantity = current_filled
        elif status == OrderStatus.FILLED:
            original_order.filled_quantity = original_order.quantity

        status_event = OrderEvent(
            timestamp=timestamp, event_type=EventType.ORDER, order_id=order_id,
            status=status, strategy_id=original_order.strategy_id,
            symbol=original_order.symbol, quantity=original_order.quantity,
            order_type=original_order.order_type, direction=original_order.direction,
            limit_price=original_order.limit_price, stop_price=original_order.stop_price,
            filled_quantity=current_filled, linked_stop_price=original_order.linked_stop_price,
            linked_target_price=original_order.linked_target_price,
            parent_order_id=original_order.parent_order_id
        )
        self.event_queue.append(status_event)
        if status in [OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.CANCELLED]:
            if order_id in self.submitted_orders:
                del self.submitted_orders[order_id]

    def _reject_order(self, order: OrderEvent, reason: str):
        """Generates a rejected order status event."""
        logger.warning(f"Order {order.order_id} Rejected: {reason}")
        self._update_order_status(order.order_id, OrderStatus.REJECTED, order.timestamp)

    def process_signal(self, event: SignalEvent):
        """Receives a signal, applies latency, and creates an OrderEvent."""
        simulated_arrival_time = event.timestamp + self.latency_data_signal_ns + self.latency_signal_order_ns
        entry_order_id = self._generate_order_id("ENTRY")

        entry_order = OrderEvent(
            timestamp=simulated_arrival_time, event_type=EventType.ORDER,
            order_id=entry_order_id, strategy_id=event.strategy_id,
            symbol=event.symbol, quantity=event.quantity,
            order_type=event.order_type, direction=event.direction,
            limit_price=event.limit_price, stop_price=event.stop_price,
            linked_stop_price=event.signal_stop_price,
            linked_target_price=event.signal_target_price,
            status=OrderStatus.PENDING_SUBMIT
        )
        self.submitted_orders[entry_order_id] = entry_order
        self.event_queue.append(entry_order)
        logger.debug(f"ExecHdlr: Received Signal. Entry Order {entry_order_id} scheduled.")

        if event.signal_stop_price or event.signal_target_price:
            self.linked_exit_orders[entry_order_id] = {'stop_id': None, 'target_id': None}

    def execute_order(self, order_event: OrderEvent):
        """Processes an order, either executing or placing it on the book."""
        logger.debug(f"ExecHdlr: Processing Order {order_event.order_id} ({order_event.order_type.name})")
        self._update_order_status(order_event.order_id, OrderStatus.ACCEPTED, order_event.timestamp)

        if order_event.order_type == OrderType.MARKET:
            self._execute_market_order(order_event)
        elif order_event.order_type == OrderType.LIMIT:
            self._handle_limit_order_placement(order_event)
        elif order_event.order_type == OrderType.STOP_MARKET:
            self._handle_stop_order_placement(order_event)
        else:
            self._reject_order(order_event, "Unsupported order type")

    def _execute_market_order(self, order: OrderEvent):
        """Simulates market order fill with slippage by walking the book."""
        symbol, order_qty, book = order.symbol, order.quantity, self.order_book
        filled_qty, total_value = 0, Decimal(0)
        
        qty_to_fill = order_qty
        if order.direction == Side.BUY:
            book_side = list(book.asks.items())
        else: # SELL
            book_side = list(book.bids.items())
        
        if not book_side:
            self._reject_order(order, f"No liquidity on {order.direction.name} side")
            return

        for price, level_data in book_side:
            available_qty = level_data['qty']
            fill_on_this_level = min(qty_to_fill, available_qty)
            
            filled_qty += fill_on_this_level
            total_value += Decimal(fill_on_this_level) * price
            qty_to_fill -= fill_on_this_level
            
            level_data['qty'] -= fill_on_this_level
            if level_data['qty'] <= 0:
                if order.direction == Side.BUY: del book.asks[price]
                else: del book.bids[price]

            if qty_to_fill == 0: break
        
        book.best_bid = next(iter(book.bids), None)
        book.best_ask = next(iter(book.asks), None)

        if filled_qty > 0:
            avg_fill_price = total_value / Decimal(filled_qty)
            commission = self.commission_per_contract * filled_qty
            fill = FillEvent(
                timestamp=order.timestamp, event_type=EventType.FILL, order_id=order.order_id,
                strategy_id=order.strategy_id, symbol=symbol, direction=order.direction,
                quantity_filled=filled_qty, fill_price=avg_fill_price, commission=commission,
                linked_stop_price=order.linked_stop_price, linked_target_price=order.linked_target_price
            )
            self.event_queue.append(fill)
            final_status = OrderStatus.FILLED if filled_qty == order_qty else OrderStatus.PARTIALLY_FILLED
            self._update_order_status(order.order_id, final_status, order.timestamp, filled_qty=filled_qty)
        else:
            self._reject_order(order, "No liquidity consumed")

    def _handle_limit_order_placement(self, order: OrderEvent):
        """Places limit order conceptually; checks for immediate fill."""
        book, bbo_bid, bbo_ask = self.order_book, *self.order_book.get_bbo()[::2]
        immediate_fill = False

        if order.direction == Side.BUY and order.limit_price and bbo_ask and order.limit_price >= bbo_ask:
            immediate_fill = True
        elif order.direction == Side.SELL and order.limit_price and bbo_bid and order.limit_price <= bbo_bid:
            immediate_fill = True

        if immediate_fill:
            logger.info(f"Limit Order {order.order_id} crosses market. Treating as Market.")
            self._execute_market_order(order)
            return

        qty_better = book.estimate_quantity_ahead(order.limit_price, order.direction)
        book_side_for_order = Side.SELL if order.direction == Side.BUY else Side.BUY
        qty_at_level_data = book.get_level_data(order.limit_price, book_side_for_order)
        qty_at_level = qty_at_level_data['qty'] if qty_at_level_data else 0

        self.pending_limit_orders[order.order_id] = {
            'order': order, 
            'qty_ahead': qty_better + qty_at_level, 
            'qty_filled': 0
        }
        logger.debug(f"Limit Order {order.order_id} added. Est. Qty Ahead: {qty_better + qty_at_level}")

    def check_limit_fills(self, trade_event: MarketData_TradeEvent):
        """Checks pending limit orders against trade using queue heuristic."""
        if not self.pending_limit_orders: return
        
        for order_id, data in list(self.pending_limit_orders.items()):
            order, trade_price, trade_qty, trade_side = data['order'], trade_event.price, trade_event.quantity, trade_event.side
            if order.symbol != trade_event.symbol: continue

            can_fill_buy = order.direction == Side.BUY and trade_side == Side.SELL and trade_price <= order.limit_price
            can_fill_sell = order.direction == Side.SELL and trade_side == Side.BUY and trade_price >= order.limit_price

            if can_fill_buy or can_fill_sell:
                qty_ahead, qty_rem = data['qty_ahead'], order.quantity - data['qty_filled']
                
                trade_consumes = Decimal(trade_qty) if trade_price == order.limit_price else Decimal('inf')
                fill_after_queue = max(Decimal(0), trade_consumes - qty_ahead)
                fill_qty = int(min(fill_after_queue, qty_rem))
                data['qty_ahead'] = max(Decimal(0), qty_ahead - trade_consumes)

                if fill_qty > 0:
                    data['qty_filled'] += fill_qty
                    commission = self.commission_per_contract * fill_qty
                    fill = FillEvent(
                        timestamp=trade_event.timestamp, event_type=EventType.FILL, order_id=order_id,
                        strategy_id=order.strategy_id, symbol=order.symbol, direction=order.direction,
                        quantity_filled=fill_qty, fill_price=order.limit_price, commission=commission
                    )
                    self.event_queue.append(fill)
                    
                    if data['qty_filled'] >= order.quantity:
                        del self.pending_limit_orders[order_id]
                        self._update_order_status(order_id, OrderStatus.FILLED, trade_event.timestamp, data['qty_filled'])
                        self._cancel_linked_stop(order_id, trade_event.timestamp)
                    else:
                        self._update_order_status(order_id, OrderStatus.PARTIALLY_FILLED, trade_event.timestamp, data['qty_filled'])

    def _handle_stop_order_placement(self, order: OrderEvent):
        """Conceptually places a stop order, waiting for a trigger."""
        if order.stop_price is None:
            self._reject_order(order, "Stop price not specified")
            return
        self.pending_stop_orders[order.order_id] = order

    def check_stop_triggers(self, trade_event: MarketData_TradeEvent):
        """Checks if the last trade price triggers any active stop orders."""
        if not self.pending_stop_orders: return
        
        for order_id, order in list(self.pending_stop_orders.items()):
            if order.symbol != trade_event.symbol: continue
            
            triggered = False
            if order.direction == Side.SELL and trade_event.price <= order.stop_price: triggered = True
            elif order.direction == Side.BUY and trade_event.price >= order.stop_price: triggered = True

            if triggered:
                del self.pending_stop_orders[order_id]
                self._update_order_status(order_id, OrderStatus.TRIGGERED, trade_event.timestamp)
                self._cancel_linked_target(order_id, trade_event.timestamp)
                
                market_order = OrderEvent(
                    timestamp=trade_event.timestamp + self.latency_signal_order_ns,
                    event_type=EventType.ORDER, order_id=f"{order_id}_MKT",
                    strategy_id=order.strategy_id, symbol=order.symbol,
                    quantity=order.quantity - order.filled_quantity,
                    order_type=OrderType.MARKET, direction=order.direction,
                    status=OrderStatus.PENDING_SUBMIT, parent_order_id=order_id
                )
                if market_order.quantity > 0:
                    self.submitted_orders[market_order.order_id] = market_order
                    self.event_queue.append(market_order)

    def _activate_linked_exits(self, entry_order_id: str, entry_fill_event: FillEvent):
        """Creates and submits linked stop/target orders after an entry fill."""
        if entry_order_id not in self.linked_exit_orders: return

        exits, now = self.linked_exit_orders[entry_order_id], entry_fill_event.timestamp
        exit_dir = Side.SELL if entry_fill_event.direction == Side.BUY else Side.BUY
        exit_qty = entry_fill_event.quantity_filled

        if entry_fill_event.linked_stop_price and not exits.get('stop_id'):
            stop_id = self._generate_order_id("STOP")
            exits['stop_id'] = stop_id
            stop_order = OrderEvent(
                timestamp=now + self.latency_signal_order_ns, event_type=EventType.ORDER, order_id=stop_id,
                strategy_id=entry_fill_event.strategy_id, symbol=entry_fill_event.symbol, quantity=exit_qty,
                order_type=OrderType.STOP_MARKET, direction=exit_dir, stop_price=entry_fill_event.linked_stop_price,
                status=OrderStatus.PENDING_SUBMIT, parent_order_id=entry_order_id
            )
            self.submitted_orders[stop_id] = stop_order
            self.event_queue.append(stop_order)

        if entry_fill_event.linked_target_price and not exits.get('target_id'):
            target_id = self._generate_order_id("TARGET")
            exits['target_id'] = target_id
            target_order = OrderEvent(
                timestamp=now + self.latency_signal_order_ns, event_type=EventType.ORDER, order_id=target_id,
                strategy_id=entry_fill_event.strategy_id, symbol=entry_fill_event.symbol, quantity=exit_qty,
                order_type=OrderType.LIMIT, direction=exit_dir, limit_price=entry_fill_event.linked_target_price,
                status=OrderStatus.PENDING_SUBMIT, parent_order_id=entry_order_id
            )
            self.submitted_orders[target_id] = target_order
            self.event_queue.append(target_order)

    def _cancel_linked_stop(self, filled_target_order_id: str, timestamp: int):
        """Finds and cancels the stop order linked to a filled target order (OCO)."""
        target_order = self.submitted_orders.get(filled_target_order_id)
        entry_id = target_order.parent_order_id if target_order else None
        
        if entry_id and entry_id in self.linked_exit_orders:
            stop_id = self.linked_exit_orders[entry_id].get('stop_id')
            if stop_id and stop_id in self.pending_stop_orders:
                del self.pending_stop_orders[stop_id]
                self._update_order_status(stop_id, OrderStatus.CANCELLED, timestamp)
                del self.linked_exit_orders[entry_id]

    def _cancel_linked_target(self, triggered_stop_order_id: str, timestamp: int):
        """Finds and cancels the target order linked to a triggered stop order (OCO)."""
        stop_order = self.submitted_orders.get(triggered_stop_order_id)
        entry_id = stop_order.parent_order_id if stop_order else None

        if entry_id and entry_id in self.linked_exit_orders:
            target_id = self.linked_exit_orders[entry_id].get('target_id')
            if target_id and target_id in self.pending_limit_orders:
                del self.pending_limit_orders[target_id]
                self._update_order_status(target_id, OrderStatus.CANCELLED, timestamp)
                del self.linked_exit_orders[entry_id]