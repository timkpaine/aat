import os
import os.path
from pprint import pprint
from typing import Any, Dict, Tuple

from aat import Strategy, Event


class ReadOnlyStrategy(Strategy):
    def __init__(self, *args: Tuple, **kwargs: Dict) -> None:
        super(ReadOnlyStrategy, self).__init__(*args, **kwargs)
        self.count = 0

    async def onStart(self, event: Event) -> None:
        pprint(self.instruments())
        pprint(self.positions())

        for i in self.instruments():
            await self.subscribe(i)
        self.at(self.onPeriodic, second=0, minute=0, hour=1)

    async def onTrade(self, event: Event) -> None:
        pprint(event)

    async def onOrder(self, event: Event) -> None:
        pprint(event)

    async def onExit(self, event: Event) -> None:
        print("Finishing...")

    async def onPeriodic(self, **kwargs: Any) -> None:
        print("here: {}".format(self.count))
        self.count += 1


if __name__ == "__main__":
    from aat import TradingEngine, parseConfig

    cfg = parseConfig(
        [
            "--trading_type",
            "backtest",
            "--load_accounts",
            "--timezone",
            "America/New_York",
            "--exchanges",
            "aat.exchange.generic:CSV,{}".format(
                os.path.join(os.path.dirname(__file__), "data", "aapl.csv")
            ),
            "--strategies",
            "aat.strategy.sample.csv.readonly_periodic:ReadOnlyStrategy",
        ]
    )
    print(cfg)
    t = TradingEngine(**cfg)
    t.start()
    assert t.strategies[0].count == 92
