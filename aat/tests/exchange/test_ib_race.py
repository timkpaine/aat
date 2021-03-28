import asyncio
from typing import List, Any, AsyncGenerator, Optional
from aat import Strategy
from aat.config import EventType, InstrumentType, Side, TradingType
from aat.core import ExchangeType, Event, Instrument, Trade, Order
from aat.exchange import Exchange


class Harness(Exchange):
    def __init__(self, trading_type: TradingType, verbose: bool) -> None:
        super().__init__(ExchangeType("testharness"))
        self._trading_type = trading_type
        self._verbose = verbose
        self._instrument = Instrument("Test.inst", InstrumentType.EQUITY)

        self._order: Optional[Order] = None
        self._done: bool = False

    async def instruments(self) -> List[Instrument]:
        """get list of available instruments"""
        return [self._instrument]

    async def connect(self) -> None:
        self._event = asyncio.Event()

    async def tick(self) -> AsyncGenerator[Any, Event]:  # type: ignore[override]
        while True:
            if self._order:
                self._order.filled = self._order.volume
                t = Trade(
                    self._order.volume,
                    self._order.price,
                    taker_order=self._order,
                    maker_orders=[],
                )
                t.my_order = self._order
                print("yielding trade")
                yield Event(type=EventType.TRADE, target=t)
                self._order = None
                self._event.set()
            yield Event(
                type=EventType.TRADE,
                target=Trade(
                    1,
                    1,
                    taker_order=Order(
                        1,
                        1,
                        Side.BUY,
                        self._instrument,
                        ExchangeType("testharness"),
                        filled=1,
                    ),
                    maker_orders=[],
                ),
            )
            if self._done:
                return

    async def newOrder(self, order: Order) -> bool:
        order.id = 1
        self._order = order
        print("waiting")
        await self._event.wait()
        self._done = True
        return True


class TestStrategy(Strategy):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(TestStrategy, self).__init__(*args, **kwargs)
        self._receivedCount = 0
        self._order: Optional[Order] = None

    async def onTrade(self, event: Event) -> None:
        if not self._order:
            self._order = Order(
                1, 1, Side.BUY, self.instruments()[0], ExchangeType("testharness")
            )
            await self.newOrder(self._order)

    async def onTraded(self, order: Order) -> None:
        print("onTraded")

    async def onReceived(self, order: Order) -> None:
        print("onReceived")
        self._receivedCount += 1

    async def onExit(self, event: Event) -> None:
        assert self._receivedCount == 1
        print("all set!")


if __name__ == "__main__":
    from aat import TradingEngine, parseConfig

    cfg = parseConfig(
        [
            "--trading_type",
            "backtest",
            "--exchanges",
            "aat.tests.exchange.test_ib_race:Harness",
            "--strategies",
            "aat.tests.exchange.test_ib_race:TestStrategy",
        ]
    )
    print(cfg)
    t = TradingEngine(**cfg)
    t.start()
