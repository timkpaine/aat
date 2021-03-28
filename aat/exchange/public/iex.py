import asyncio
import os
import os.path
import pandas as pd  # type: ignore
import pyEX  # type: ignore
from collections import deque
from datetime import datetime, timedelta
from tqdm import tqdm  # type: ignore
from typing import AsyncGenerator, Any, Deque, List

from aat.exchange import Exchange
from aat.config import InstrumentType, EventType, Side, TradingType
from aat.core import ExchangeType, Instrument, Event, Trade, Order

_iex_instrument_types = {
    "ad": InstrumentType.EQUITY,  # ad - ADR
    "gdr": InstrumentType.EQUITY,  # gdr - GDR
    "re": InstrumentType.OTHER,  # re - REIT
    "ce": InstrumentType.MUTUALFUND,  # ce - Closed end fund
    "si": InstrumentType.EQUITY,  # si - Secondary Issue
    "lp": InstrumentType.OTHER,  # lp - Limited Partnerships
    "cs": InstrumentType.EQUITY,  # cs - Common Stock
    "et": InstrumentType.EQUITY,  # et - ETF
    "wt": InstrumentType.OTHER,  # wt - Warrant
    "rt": InstrumentType.OTHER,  # rt – Right
    "oef": InstrumentType.MUTUALFUND,  # oef - Open Ended Fund
    "cef": InstrumentType.MUTUALFUND,  # cef - Closed Ended Fund
    "ps": InstrumentType.EQUITY,  # ps - Preferred Stock
    "ut": InstrumentType.OTHER,  # ut - Unit
    "struct": InstrumentType.OTHER,  # struct - Structured Product
}


class IEX(Exchange):
    """Investor's Exchange"""

    def __init__(
        self,
        trading_type: TradingType,
        verbose: bool,
        api_key: str,
        is_sandbox: bool,
        timeframe: str = "1y",
        start_date: str = "",
        end_date: str = "",
        cache_data: bool = True,
        preload_instruments: bool = True,
    ) -> None:
        super().__init__(ExchangeType("iex"))
        self._trading_type = trading_type
        self._verbose = verbose
        self._api_key = api_key
        self._is_sandbox = is_sandbox
        self._cache_data = cache_data
        self._preload_instruments = preload_instruments

        if trading_type == TradingType.LIVE:
            assert not is_sandbox

        self._timeframe = timeframe

        if timeframe == "live":
            assert trading_type != TradingType.BACKTEST

        if timeframe == "1d":
            # intraday testing
            # TODO if today is weekend/holiday, pick last day with data
            self._start_date = (
                datetime.strptime(start_date, "%Y%m%d")
                if start_date
                else datetime.today()
            )
            self._end_date = (
                datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.today()
            )

        self._subscriptions: List[Instrument] = []

        # "Order" management
        self._queued_orders: Deque[Order] = deque()
        self._order_id = 1

    # *************** #
    # General methods #
    # *************** #
    async def connect(self) -> None:
        """connect to exchange. should be asynchronous.

        For OrderEntry-only, can just return None
        """
        self._client = pyEX.Client(
            self._api_key, "sandbox" if self._is_sandbox else "stable"
        )

    # ******************* #
    # Market Data Methods #
    # ******************* #
    async def instruments(self) -> List[Instrument]:
        """get list of available instruments"""
        if self._preload_instruments:
            instruments = []
            symbols = self._client.symbols()

            for record in tqdm(symbols, desc="Fetching instruments..."):
                if (
                    not record["isEnabled"]
                    or not record["type"]
                    or record["type"] == "temp"
                ):
                    continue
                symbol = record["symbol"]
                brokerExchange = record["exchange"]
                type = _iex_instrument_types[record["type"]]
                currency = Instrument(
                    type=InstrumentType.CURRENCY, name=record["currency"]
                )

                try:
                    inst = Instrument(
                        name=symbol,
                        type=type,
                        exchange=self.exchange(),
                        brokerExchange=brokerExchange,
                        currency=currency,
                    )
                except (AssertionError, KeyError):
                    # Happens sometimes on sandbox
                    continue
                instruments.append(inst)
            return instruments
        return []

    async def subscribe(self, instrument: Instrument) -> None:
        self._subscriptions.append(instrument)

    async def tick(self) -> AsyncGenerator[Any, Event]:  # type: ignore[override]
        """return data from exchange"""
        if self._timeframe == "live":
            data: Deque[dict] = deque()

            def _callback(record: dict) -> None:
                data.append(record)

            self._client.tradesSSE(
                symbols=",".join([i.name for i in self._subscriptions]),
                on_data=_callback,
            )

            while True:
                while data:
                    record = data.popleft()
                    volume = record["volume"]
                    price = record["price"]
                    instrument = Instrument(record["symbol"], InstrumentType.EQUITY)

                    o = Order(
                        volume=volume,
                        price=price,
                        side=Side.BUY,
                        instrument=instrument,
                        exchange=self.exchange(),
                    )
                    t = Trade(
                        volume=volume, price=price, taker_order=o, maker_orders=[]
                    )
                    yield Event(type=EventType.TRADE, target=t)

                await asyncio.sleep(0)

        else:
            dfs = []
            insts = set()

            if self._timeframe != "1d":
                for i in tqdm(self._subscriptions, desc="Fetching data..."):
                    if i.name in insts:
                        # already fetched the data, multiple subscriptions
                        continue

                    if self._cache_data:
                        # first, check if we have this data and its cached already
                        os.makedirs("_aat_data", exist_ok=True)
                        data_filename = os.path.join(
                            "_aat_data",
                            "iex_{}_{}_{}_{}.pkl".format(
                                i.name,
                                self._timeframe,
                                datetime.now().strftime("%Y%m%d"),
                                "sand" if self._is_sandbox else "",
                            ),
                        )

                        if os.path.exists(data_filename):
                            print("using cached IEX data for {}".format(i.name))
                            df = pd.read_pickle(data_filename)
                        else:
                            df = self._client.chartDF(i.name, timeframe=self._timeframe)
                            df.to_pickle(data_filename)

                    else:
                        df = self._client.chartDF(i.name, timeframe=self._timeframe)

                    df = df[["close", "volume"]]
                    df.columns = ["close:{}".format(i.name), "volume:{}".format(i.name)]
                    dfs.append(df)
                    insts.add(i.name)

                data_frame = pd.concat(dfs, axis=1)
                data_frame.sort_index(inplace=True)
                data_frame = data_frame.groupby(data_frame.index).last()
                data_frame.drop_duplicates(inplace=True)
                data_frame.fillna(method="ffill", inplace=True)

            else:
                for i in tqdm(self._subscriptions, desc="Fetching data..."):
                    if i.name in insts:
                        # already fetched the data, multiple subscriptions
                        continue

                    date = self._start_date
                    subdfs = []
                    while date <= self._end_date:
                        if self._cache_data:
                            # first, check if we have this data and its cached already
                            os.makedirs("_aat_data", exist_ok=True)
                            data_filename = os.path.join(
                                "_aat_data",
                                "iex_{}_{}_{}_{}.pkl".format(
                                    i.name,
                                    self._timeframe,
                                    date,
                                    "sand" if self._is_sandbox else "",
                                ),
                            )

                            if os.path.exists(data_filename):
                                print(
                                    "using cached IEX data for {} - {}".format(
                                        i.name, date
                                    )
                                )
                                df = pd.read_pickle(data_filename)
                            else:
                                df = self._client.chartDF(
                                    i.name, timeframe="1d", date=date.strftime("%Y%m%d")
                                )
                                df.to_pickle(data_filename)
                        else:
                            df = self._client.chartDF(
                                i.name, timeframe="1d", date=date.strftime("%Y%m%d")
                            )

                        if not df.empty:
                            df = df[["average", "volume"]]
                            df.columns = [
                                "close:{}".format(i.name),
                                "volume:{}".format(i.name),
                            ]
                            subdfs.append(df)

                        date += timedelta(days=1)

                    dfs.append(pd.concat(subdfs))
                    insts.add(i.name)

                data_frame = pd.concat(dfs, axis=1)
                data_frame.index = [
                    x
                    + timedelta(
                        hours=int(y.split(":")[0]), minutes=int(y.split(":")[1])
                    )
                    for x, y in data_frame.index
                ]
                data_frame = data_frame.groupby(data_frame.index).last()
                data_frame.drop_duplicates(inplace=True)
                data_frame.fillna(method="ffill", inplace=True)

            for index in data_frame.index:
                for i in self._subscriptions:
                    volume = data_frame.loc[index]["volume:{}".format(i.name)]
                    price = data_frame.loc[index]["close:{}".format(i.name)]
                    if volume == 0:
                        continue

                    o = Order(
                        volume=volume,
                        price=price,
                        side=Side.BUY,
                        instrument=i,
                        exchange=self.exchange(),
                        filled=volume,
                        timestamp=index.to_pydatetime(),
                    )
                    t = Trade(
                        volume=volume, price=price, taker_order=o, maker_orders=[]
                    )

                    yield Event(type=EventType.TRADE, target=t)
                    await asyncio.sleep(0)

                while self._queued_orders:
                    order = self._queued_orders.popleft()
                    order.timestamp = index
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
                    await asyncio.sleep(0)

    # ******************* #
    # Order Entry Methods #
    # ******************* #
    async def newOrder(self, order: Order) -> bool:
        """submit a new order to the exchange. should set the given order's `id` field to exchange-assigned id

        For MarketData-only, can just return None
        """
        if self._trading_type == TradingType.LIVE:
            raise NotImplementedError("Live OE not available for IEX")

        order.id = str(self._order_id)
        self._order_id += 1
        self._queued_orders.append(order)
        return True

    async def cancelOrder(self, order: Order) -> bool:
        # Can't cancel, orders execute immediately
        # TODO limit orders
        return False
