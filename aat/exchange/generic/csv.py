import asyncio
import csv
from collections import deque
from datetime import datetime
from typing import List, Deque, AsyncGenerator, Any
from aat.config import EventType, InstrumentType, Side, TradingType
from aat.core import ExchangeType, Event, Instrument, Trade, Order
from aat.exchange import Exchange


class CSV(Exchange):
    """CSV File Exchange"""

    def __init__(self, trading_type: TradingType, verbose: bool, filename: str) -> None:
        super().__init__(ExchangeType("csv-{}".format(filename)))
        self._trading_type = trading_type
        self._verbose = verbose
        self._filename = filename
        self._data: List[Trade] = []

        # "Order" management
        self._queued_orders: Deque[Order] = deque()
        self._order_id = 1

    async def instruments(self) -> List[Instrument]:
        """get list of available instruments"""
        return list(set(_.instrument for _ in self._data))

    async def connect(self) -> None:
        with open(self._filename) as csvfile:
            self._reader = csv.DictReader(csvfile, delimiter=",")

            for row in self._reader:
                order = Order(
                    volume=float(row["volume"]),
                    price=float(row["close"]),
                    side=Side.BUY,
                    exchange=self.exchange(),
                    instrument=Instrument(
                        row["symbol"].split("-")[0],
                        instrument=InstrumentType(row["symbol"].split("-")[1].upper()),
                        exchange=self.exchange(),
                    ),
                    filled=float(row["volume"]),
                )
                if "time" in row:
                    order.timestamp = datetime.fromtimestamp(float(row["time"]))
                elif "date" in row:
                    order.timestamp = datetime.fromisoformat(row["date"])
                elif "datetime" in row:
                    order.timestamp = datetime.fromisoformat(row["datetime"])

                self._data.append(
                    Trade(
                        volume=float(row["volume"]),
                        price=float(row["close"]),
                        maker_orders=[],
                        taker_order=order,
                    )
                )

    async def tick(self) -> AsyncGenerator[Any, Event]:  # type: ignore[override]
        for item in self._data:
            yield Event(EventType.TRADE, item)
            await asyncio.sleep(0)

            # save timestamp
            timestamp = item.timestamp

            while self._queued_orders:
                order = self._queued_orders.popleft()
                order.timestamp = timestamp
                order.filled = order.volume

                t = Trade(
                    volume=order.volume,
                    price=order.price,
                    taker_order=order,
                    maker_orders=[],
                    my_order=order,  # FIXME this isnt technically necessary as
                    # the engine should do this automatically
                )

                yield Event(type=EventType.TRADE, target=t)

    async def cancelOrder(self, order: Order) -> bool:
        # Can't cancel, orders execute immediately
        # TODO limit orders
        return False

    async def newOrder(self, order: Order) -> bool:
        if self._trading_type == TradingType.LIVE:
            raise NotImplementedError("Live OE not available for CSV")

        order.id = str(self._order_id)
        self._order_id += 1
        self._queued_orders.append(order)
        return True
