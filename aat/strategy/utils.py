import asyncio

from datetime import datetime
from typing import Callable, Optional, List, TYPE_CHECKING
from ..config import Side, TradingType, ExitRoutine, InstrumentType
from ..core import Trade, Instrument, ExchangeType, Order, OrderBook
from ..exchange import Exchange
from ..engine.dispatch import Periodic


if TYPE_CHECKING:
    from aat.engine import StrategyManager


class StrategyUtilsMixin(object):
    _manager: "StrategyManager"

    def orders(
        self,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ) -> List[Order]:
        """select all open orders

        Args:
            instrument (Optional[Instrument]): filter open orders by instrument
            exchange (Optional[ExchangeType]): filter open orders by exchange
            side (Optional[Side]): filter open orders by side
        Returns:
            list (Order): list of open orders
        """
        return self._manager.orders(self, instrument, exchange, side)  # type: ignore # mixin

    def pastOrders(
        self,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ) -> List[Order]:
        """select all past orders

        Args:
            instrument (Optional[Instrument]): filter past orders by instrument
            exchange (Optional[ExchangeType]): filter past orders by exchange
            side (Optional[Side]): filter past orders by side
        Returns:
            list (Order): list of open orders
        """
        return self._manager.pastOrders(self, instrument, exchange, side)  # type: ignore # mixin

    def trades(
        self,
        instrument: Instrument = None,
        exchange: ExchangeType = None,
        side: Side = None,
    ) -> List[Trade]:
        """select all past trades

        Args:
            instrument (Optional[Instrument]): filter trades by instrument
            exchange (Optional[ExchangeType]): filter trades by exchange
            side (Optional[Side]): filter trades by side
        Returns:
            list (Trade): list of trades
        """
        return self._manager.trades(self, instrument, exchange, side)  # type: ignore # mixin

    #################
    # Other Methods #
    #################
    def tradingType(self) -> TradingType:
        """Return the trading type, from TradingType enum"""
        return self._manager.tradingType()

    def loop(self) -> asyncio.AbstractEventLoop:
        """Return the event loop"""
        return self._manager.loop()

    def now(self) -> datetime:
        """Return the current datetime. Useful to avoid code changes between
        live trading and backtesting. Defaults to `datetime.now`"""
        return self._manager.now()

    def instruments(
        self, type: InstrumentType = None, exchange: ExchangeType = None
    ) -> List[Instrument]:
        """Return list of all available instruments"""
        return Instrument._instrumentdb.instruments(type=type, exchange=exchange)

    def exchanges(self, instrument_type: InstrumentType = None) -> List[Exchange]:
        """Return list of all available exchanges"""
        return list(
            set(
                __
                for _ in Instrument._instrumentdb.instruments(type=instrument_type)
                for __ in _.exchanges
            )
        )

    def accounts(
        self, type: InstrumentType = None, exchange: ExchangeType = None
    ) -> None:  # TODO
        """Return list of all accounts"""
        raise NotImplementedError()

    async def subscribe(self, instrument: Instrument) -> None:
        """Subscribe to market data for the given instrument"""
        return await self._manager.subscribe(instrument=instrument, strategy=self)  # type: ignore # mixin

    async def lookup(
        self, instrument: Optional[Instrument], exchange: ExchangeType = None
    ) -> List[Instrument]:
        """Return list of all available instruments that match the instrument given"""
        return await self._manager.lookup(instrument, exchange=exchange)

    async def book(self, instrument: Instrument) -> Optional[OrderBook]:
        """Return list of all available instruments that match the instrument given"""
        return await self._manager.book(instrument)

    def periodic(
        self,
        function: Callable,
        seconds: int = 0,
        minutes: int = None,
        hours: int = None,
    ) -> Periodic:
        """periodically run a given async function. NOTE: precise timing
        is NOT guaranteed due to event loop scheduling.

        Args:
            function (callable); function to call periodically
            second (str); second to align periodic to
            minute (str); minute to align periodic to
            hour (str); hour to align periodic to
        """
        return self._manager.periodic(function, seconds, minutes, hours)

    def at(
        self,
        function: Callable,
        second: int = 0,
        minute: int = None,
        hour: int = None,
    ) -> Periodic:
        """periodically run a given async function. NOTE: precise timing
        is NOT guaranteed due to event loop scheduling.

        Args:
            function (callable); function to call periodically
            second (str); second to align periodic to
            minute (str); minute to align periodic to
            hour (str); hour to align periodic to

                NOTE: this is a rudimentary scheme but should be sufficient. For more
                complicated scheduling, just install multiple instances of the same periodic
                e.g. for running on :00, :15, :30, and :45 install
                    periodic(0, 0)
                    periodic(0, 15)
                    periodic(0, 30)
                    periodic(0, 45)
        """
        return self._manager.at(function, second, minute, hour)

    def restrictTradingHours(
        self,
        start_second: Optional[int] = None,
        start_minute: Optional[int] = None,
        start_hour: Optional[int] = None,
        end_second: Optional[int] = None,
        end_minute: Optional[int] = None,
        end_hour: Optional[int] = None,
        on_end_of_day: ExitRoutine = ExitRoutine.NONE,
    ) -> None:
        """Restrict a strategy's trading hours to [start_hour:start_minute:start_second, end_hour:end_minute:end_second]
        NOTE: precise timing is NOT guaranteed due to event loop scheduling.

        Args:
            start_second (Optional[int]); starting second
            start_minute (Optional[int]); starting minute
            start_second (Optional[int]); starting hour
            end_second (Optional[int]); ending second
            end_second (Optional[int]); ending minute
            end_second (Optional[int]); ending hour
            on_end_of_day (ExitRoutine); what to do when you hit the end time
        """
        self._manager.restrictTradingHours(
            self,  # type: ignore # mixin
            start_second=start_second,
            start_minute=start_minute,
            start_hour=start_hour,
            end_second=end_second,
            end_minute=end_minute,
            end_hour=end_hour,
            on_end_of_day=on_end_of_day,
        )

    def slippage(self, trade: Trade) -> None:
        """method to inject slippage when backtesting

        Args:
            trade (Trade): the completed trade to adjust
        Returns:
            trade (Trade): the modified trade
        """
        pass

    def transactionCost(self, trade: Trade) -> None:
        """method to inject transaction costs when backtesting

        Args:
            trade (Trade): the completed trade to adjust
        Returns:
            trade (Trade): the modified trade
        """
        pass
