# l3_engine/data/loader.py
import sqlite3
import heapq
import logging
from decimal import Decimal
from typing import List, Tuple, Optional, Iterator

from ..domain.events import Event, MarketData_TradeEvent, MarketData_DepthEvent
from ..domain.enums import EventType, Side, OrderCommand

logger = logging.getLogger(__name__)

class SQLiteDataLoader:
    """Loads, parses, merges, and sorts data from a SQLite tick.db."""
    def __init__(self, db_path: str, symbol: str, batch_size: int = 50000):
        self.db_path = db_path
        self.symbol = symbol
        self.batch_size = batch_size
        self._event_generator: Optional[Iterator[Event]] = None
        table_symbol = self.symbol.replace('-', '_')
        self.tas_table_name = f"{table_symbol}_tas"
        self.depth_table_name = f"{table_symbol}_depth"
        logger.info(f"Expecting tables: {self.tas_table_name}, {self.depth_table_name}")

    def _db_connect(self) -> sqlite3.Connection:
        """Establishes connection to the SQLite database."""
        try:
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True)
            logger.info(f"Connected to SQLite database: {self.db_path}")
            return conn
        except sqlite3.OperationalError:
            logger.warning(f"Could not connect in read-only mode, trying read-write: {self.db_path}")
            try:
                conn = sqlite3.connect(self.db_path)
                logger.info(f"Connected to SQLite database (read-write): {self.db_path}")
                return conn
            except sqlite3.Error as e:
                logger.error(f"Error connecting to database {self.db_path}: {e}")
                raise
        except sqlite3.Error as e:
            logger.error(f"Error connecting to database {self.db_path}: {e}")
            raise

    def _fetch_data_batch(self, cursor: sqlite3.Cursor) -> List[Tuple]:
        """Fetches a batch of data using the cursor."""
        return cursor.fetchmany(self.batch_size)

    def _determine_side_from_flags(self, flags: int) -> Side:
        """
        Determines if a depth update is for the BID or ASK side based on flags.
        NOTE: This is a placeholder rule based on the original script. This might
        need to be adjusted for different data sources.
        """
        return Side.SELL if flags % 2 == 1 else Side.BUY # SELL for Bid, BUY for Ask

    def _create_event_from_row(self, row: Tuple, event_type: EventType) -> Optional[Event]:
        """Converts a database row tuple into an Event object."""
        try:
            timestamp = int(row[0])

            if event_type == EventType.MARKET_TRADE:
                # TAS Table Schema: timestamp, price, qty, side (0=BuyAgg, 1=SellAgg)
                return MarketData_TradeEvent(
                    timestamp=timestamp, event_type=event_type, symbol=self.symbol,
                    price=Decimal(str(row[1])), quantity=int(row[2]), side=Side(int(row[3]))
                )

            elif event_type == EventType.MARKET_DEPTH:
                # Depth Table Schema: timestamp, command, flags, num_orders, price, qty
                try:
                    command = OrderCommand(int(row[1]))
                except ValueError:
                    logger.warning(f"Unknown depth command value {row[1]}. Treating as UPDATE.")
                    command = OrderCommand.UPDATE

                return MarketData_DepthEvent(
                    timestamp=timestamp, event_type=event_type, symbol=self.symbol,
                    price=Decimal(str(row[4])), quantity=int(row[5]),
                    side=self._determine_side_from_flags(int(row[2])),
                    command=command, flags=int(row[2]), num_orders=int(row[3])
                )
            return None
        except (IndexError, ValueError, TypeError, KeyError) as e:
            logger.warning(f"Skipping row due to parsing error: {row} - Error: {e}")
            return None

    def _stream_from_cursor(self, cursor: sqlite3.Cursor, event_type: EventType) -> Iterator[Event]:
        """Generator function to yield events from a database cursor."""
        while True:
            batch = self._fetch_data_batch(cursor)
            if not batch:
                break
            for row in batch:
                event = self._create_event_from_row(row, event_type)
                if event:
                    yield event
        logger.info(f"Finished streaming {event_type.value} events.")

    def stream_events(self) -> Iterator[Event]:
        """Returns the generator for the combined event stream from SQLite."""
        if self._event_generator is not None:
            return self._event_generator

        conn = self._db_connect()
        tas_cursor = conn.cursor()
        depth_cursor = conn.cursor()

        tas_query = f"SELECT timestamp, price, qty, side FROM {self.tas_table_name} ORDER BY timestamp ASC"
        depth_query = f"SELECT timestamp, command, flags, num_orders, price, qty FROM {self.depth_table_name} ORDER BY timestamp ASC"

        try:
            logger.info(f"Executing TAS query: {tas_query}")
            tas_cursor.execute(tas_query)
            logger.info(f"Executing Depth query: {depth_query}")
            depth_cursor.execute(depth_query)
        except sqlite3.Error as e:
            logger.error(f"Error executing initial DB query: {e}")
            conn.close()
            raise

        tas_stream = self._stream_from_cursor(tas_cursor, EventType.MARKET_TRADE)
        depth_stream = self._stream_from_cursor(depth_cursor, EventType.MARKET_DEPTH)
        logger.info("Starting heapq merge of TAS and Depth streams...")
        merged_stream = heapq.merge(tas_stream, depth_stream)

        def stream_wrapper():
            count = 0
            try:
                for event in merged_stream:
                    yield event
                    count += 1
            finally:
                logger.info(f"Closing DB connection. Total events yielded: {count}")
                conn.close()

        self._event_generator = stream_wrapper()
        return self._event_generator