# l3_engine/domain/enums.py
import enum

class EventType(enum.Enum):
    """Defines the types of events that can be processed in the system."""
    MARKET_TRADE = 'MARKET_TRADE'
    MARKET_DEPTH = 'MARKET_DEPTH'
    SIGNAL = 'SIGNAL'
    ORDER = 'ORDER'
    FILL = 'FILL'

class Side(enum.Enum):
    """Represents the side of a trade or order book update."""
    BUY = 0  # Represents Ask side in OrderBook, Buy Aggressor in Trade
    SELL = 1 # Represents Bid side in OrderBook, Sell Aggressor in Trade

class OrderCommand(enum.Enum):
    """
    Represents the type of modification in a depth update.
    NOTE: You must verify what the unknown command values from your
    database truly represent and rename them accordingly.
    """
    # Standard Commands
    DELETE = 3
    INSERT = 1
    UPDATE = 2

    # --- Placeholder values discovered from logs ---
    # TODO: Replace these placeholder names with the correct terms for your data source.
    UNKNOWN_4 = 4
    UNKNOWN_5 = 5
    UNKNOWN_6 = 6
    UNKNOWN_7 = 7


class OrderType(enum.Enum):
    """Defines the supported types of orders."""
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'
    STOP_MARKET = 'STOP_MARKET'

class OrderStatus(enum.Enum):
    """Represents the lifecycle status of an order."""
    PENDING_SUBMIT = 'PENDING_SUBMIT'
    ACCEPTED = 'ACCEPTED'
    REJECTED = 'REJECTED'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    PENDING_CANCEL = 'PENDING_CANCEL'
    CANCELLED = 'CANCELLED'
    TRIGGERED = 'TRIGGERED'

class ZeroCompareAction(enum.Enum):
    """Defines the action to take in the strategy when a zero denominator is encountered."""
    SET_0_TO_1 = 0
    SET_PERC_1000 = 1