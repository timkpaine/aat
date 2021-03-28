import asyncio
from datetime import datetime
from typing import Any, Callable, List, Optional, Union, TYPE_CHECKING

from aat import AATException
from aat.config import ExitRoutine, InstrumentType, TradingType
from aat.core import Instrument, ExchangeType, Event, Order, Trade, OrderBook
from aat.exchange import Exchange

from .periodic import Periodic

if TYPE_CHECKING:
    from aat.engine import TradingEngine
    from aat.strategy import Strategy


class StrategyManagerUtilsMixin(object):
    _engine: "TradingEngine"
    _exchanges: List[Exchange]
    _periodics: List[Periodic]
    _data_subscriptions = {}  # type: ignore

    #################
    # Other Methods #
    #################

    def tradingType(self) -> TradingType:
        return self._engine.trading_type

    def loop(self) -> asyncio.AbstractEventLoop:
        return self._engine.event_loop

    def now(self) -> datetime:
        """Return the current datetime. Useful to avoid code changes between
        live trading and backtesting. Defaults to `datetime.now`"""
        return self._engine.now()

    def instruments(
        self, type: InstrumentType = None, exchange: Optional[ExchangeType] = None
    ) -> List[Instrument]:
        """Return list of all available instruments"""
        return Instrument._instrumentdb.instruments(type=type, exchange=exchange)

    def exchanges(self, type: InstrumentType = None) -> List[ExchangeType]:
        """Return list of all available exchanges"""
        if type:
            raise NotImplementedError()
        return [exc.exchange() for exc in self._exchanges]

    async def subscribe(self, instrument: Instrument, strategy: "Strategy") -> None:
        """Subscribe to market data for the given instrument"""
        if strategy not in self._data_subscriptions:
            self._data_subscriptions[strategy] = []

        self._data_subscriptions[strategy].append(instrument)

        if instrument.exchange not in self.exchanges():
            raise AATException(
                "Exchange not installed: {} (Installed are [{}]".format(
                    instrument.exchange, self.exchanges()
                )
            )

        for exc in self._exchanges:
            if instrument and instrument.exchange == exc.exchange():
                await exc.subscribe(instrument)

    def dataSubscriptions(self, handler: Callable, event: Event) -> bool:
        """does handler subscribe to the data for event"""
        if handler not in self._data_subscriptions:
            # subscribe all by default
            return True
        target: Union[Order, Trade] = event.target  # type: ignore
        return target.instrument in self._data_subscriptions[handler]

    async def lookup(
        self, instrument: Optional[Instrument], exchange: ExchangeType = None
    ) -> List[Instrument]:
        """Return list of all available instruments that match the instrument given"""
        if exchange:
            for exchange_inst in self._exchanges:
                if exchange == exchange_inst.exchange():
                    if instrument:
                        return await exchange_inst.lookup(instrument)
                    return []

        elif exchange is None:
            ret = []
            for exchange_inst in self._exchanges:
                if instrument:
                    ret.extend(await exchange_inst.lookup(instrument))
            return ret

        # None implement
        raise NotImplementedError()

    async def book(self, instrument: Instrument) -> Optional[OrderBook]:
        """Return list of all available instruments that match the instrument given"""
        if instrument.exchange not in self.exchanges():
            raise AATException("")

        for exchange_inst in self._exchanges:
            if instrument.exchange == exchange_inst.exchange():
                return await exchange_inst.book(instrument)

        return None

    def _make_async(self, function: Callable) -> Callable:
        async def _wrapper() -> Any:
            return await self.loop().run_in_executor(
                self._engine, self._engine.executor, function
            )

        return _wrapper

    def periodic(
        self,
        function: Callable,
        seconds: int = 0,
        minutes: int = None,
        hours: int = None,
    ) -> Periodic:
        """run a function periodically:
        if the amount of time between previous call and current call
        is more than `seconds` seconds + `minutes` minutes + `hours` hours,
        then reexecute
        """
        return self._periodic(function, seconds, minutes, hours, interval=True)

    def at(
        self,
        function: Callable,
        second: int = 0,
        minute: int = None,
        hour: int = None,
    ) -> Periodic:
        """run a function at a certain point in time:
        e.g. run it on every `second` second every minute of every hour
        So 2, "*", "*", would run 1:00:02, 1:01:02, etc
        """
        return self._periodic(function, second, minute, hour, interval=False)

    def _periodic(
        self,
        function: Callable,
        second: int = 0,
        minute: int = None,
        hour: int = None,
        interval: bool = False,
    ) -> Periodic:
        """periodically run a given async function. NOTE: precise timing
        is NOT guaranteed due to event loop scheduling."""
        if not self.loop().is_running():
            raise Exception("Install periodics after engine start (e.g. in `onStart`)")

        # Validation
        if not asyncio.iscoroutinefunction(function):
            function = self._make_async(function)

        if second is not None and not isinstance(second, int):
            raise Exception("`second` arg must be int")

        if minute is not None and not isinstance(minute, int):
            raise Exception("`minute` arg must be int")

        if hour is not None and not isinstance(hour, int):
            raise Exception("`hour` arg must be int")

        if second is not None and (second < 0 or second > 60):
            raise Exception("`second` must be between 0 and 60")

        if minute is not None and (minute < 0 or minute > 60):
            raise Exception("`minute` must be between 0 and 60")

        if hour is not None and (hour < 0 or hour > 24):
            raise Exception("`hour` must be between 0 and 24")
        # End Validation

        periodic = Periodic(
            self.loop(),
            self._engine._latest,
            function,
            second,
            minute,
            hour,
            interval,
        )
        self._periodics.append(periodic)
        return periodic

    def restrictTradingHours(
        self,
        strategy: "Strategy",
        start_second: Optional[int] = None,
        start_minute: Optional[int] = None,
        start_hour: Optional[int] = None,
        end_second: Optional[int] = None,
        end_minute: Optional[int] = None,
        end_hour: Optional[int] = None,
        on_end_of_day: ExitRoutine = ExitRoutine.NONE,
    ) -> None:
        pass
