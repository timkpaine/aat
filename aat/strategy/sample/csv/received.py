import os
import os.path
from pprint import pprint
from typing import Any

from aat import Strategy, Event, Order, Side, Trade


class ReceivedStrategy(Strategy):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(ReceivedStrategy, self).__init__(*args, **kwargs)
        self._trade = True
        self._received_count = 0

    async def onStart(self, event: Event) -> None:
        pprint(self.instruments())
        pprint(self.positions())

        for i in self.instruments():
            await self.subscribe(i)

    async def onTrade(self, event: Event) -> None:
        pprint(event)
        trade: Trade = event.target  # type: ignore
        if self._trade and trade.my_order is None:
            await self.newOrder(
                Order(
                    1,
                    trade.price,
                    Side.BUY,
                    trade.instrument,
                    trade.exchange,
                )
            )
            self._trade = False

    async def onReceived(self, event: Event) -> None:
        pprint(event)
        self._trade = True
        self._received_count += 1

    async def onExit(self, event: Event) -> None:
        print("Finishing...")


if __name__ == "__main__":
    from aat import TradingEngine, parseConfig

    cfg = parseConfig(
        [
            "--trading_type",
            "backtest",
            "--load_accounts",
            "--exchanges",
            "aat.exchange.generic:CSV,{}".format(
                os.path.join(os.path.dirname(__file__), "data", "aapl.csv")
            ),
            "--strategies",
            "aat.strategy.sample.csv.received:ReceivedStrategy",
        ]
    )
    print(cfg)
    t = TradingEngine(**cfg)
    t.start()
    print(t.strategies[0]._received_count)
    assert t.strategies[0]._received_count == 64
