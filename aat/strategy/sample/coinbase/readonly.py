from pprint import pprint
from typing import Any, cast
from aat import Strategy, Event, Instrument, InstrumentType, Trade


class ReadOnlyStrategy(Strategy):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(ReadOnlyStrategy, self).__init__(*args, **kwargs)

    async def onStart(self, event: Event) -> None:
        pprint(self.instruments())
        pprint(self.positions())

        await self.subscribe(Instrument("BTC-USD", InstrumentType.PAIR))

    async def onTrade(self, event: Event) -> None:
        pprint(event)
        pprint(await self.book(cast(Trade, event.target).instrument))

    async def onExit(self, event: Event) -> None:
        print("Finishing...")


if __name__ == "__main__":
    from aat import TradingEngine, parseConfig

    cfg = parseConfig(
        [
            "--trading_type",
            "sandbox",
            "--load_accounts",
            "--exchanges",
            "aat.exchange.crypto.coinbase:CoinbaseProExchange,,,,l2",
            "--strategies",
            "aat.strategy.sample.coinbase.readonly:ReadOnlyStrategy",
        ]
    )

    # or via config file
    """
        [general]
        verbose=0
        trading_type=sandbox
        load_accounts=1

        [exchange]
        exchanges=
            aat.exchange.crypto.coinbase:CoinbaseProExchange,,,,l2

        [strategy]
        strategies =
            aat.strategy.sample.coinbase.readonly:ReadOnlyStrategy
    """
    print(cfg)
    t = TradingEngine(**cfg)
    t.start()
