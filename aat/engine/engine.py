import asyncio
import inspect
import os
import os.path
import pytz

from asyncio import Future, Queue
from aiostream.stream import merge  # type: ignore
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from traitlets.config.application import Application  # type: ignore
from traitlets import (  # type: ignore
    validate,
    TraitError,
    Unicode,
    Bool,
    List,
    Instance,
)
from tornado.web import (
    StaticFileHandler,
    RedirectHandler,
    Application as TornadoApplication,
)
from typing import (
    Any,
    Awaitable,
    AsyncGenerator,
    Callable,
    Deque,
    Dict,
    List as ListType,
    Optional,
    Tuple,
)

try:
    from perspective import (  # type: ignore
        PerspectiveManager,
        PerspectiveTornadoHandler,
    )
except ImportError:
    PerspectiveManager, PerspectiveTornadoHandler = None, None  # type: ignore

from aat.core.handler import EventHandler, PrintHandler
from aat.core.data import Event, Error
from aat.core.table import TableHandler
from aat.config import TradingType, EventType, getStrategies, getExchanges
from aat.exchange import Exchange
from aat.strategy import Strategy

# from aat.strategy import Strategy
from aat.ui import ServerApplication

from .dispatch import StrategyManager, OrderManager, PortfolioManager, RiskManager

try:
    import uvloop  # type: ignore
except ImportError:
    uvloop = None


class TradingEngine(Application):
    """A configureable trading application"""

    name = "AAT"
    description = "async algorithmic trading engine"

    # Configureable parameters
    verbose = Bool(default_value=True)
    api = Bool(default_value=False)
    port = Unicode(default_value="8080", help="Port to run on").tag(config=True)
    tz = Instance(
        klass=pytz.BaseTzInfo,
        default_value=None,
        allow_none=True,
        help="Timezone to localize to",
    ).tag(config=True)
    event_loop = Instance(klass=asyncio.events.AbstractEventLoop)
    executor = Instance(klass=ThreadPoolExecutor, args=(4,), kwargs={})

    # Core components
    trading_type = Instance(klass=TradingType, default_value=TradingType.SIMULATION)
    order_manager = Instance(OrderManager, args=(), kwargs={})
    risk_manager = Instance(RiskManager, args=(), kwargs={})
    portfolio_manager = Instance(PortfolioManager, args=(), kwargs={})
    exchanges = List(trait=Instance(klass=Exchange))
    event_handlers = List(trait=Instance(EventHandler), default_value=[])
    strategies = List(trait=Instance(Strategy), default_value=[])

    # API application
    api_application = Instance(klass=TornadoApplication)
    api_handlers = List(default_value=[])

    table_manager = Instance(
        klass=PerspectiveManager or object, args=(), kwargs={}
    )  # failover to object

    aliases = {"port": "AAT.port", "trading_type": "AAT.trading_type"}

    @validate("trading_type")
    def _validate_trading_type(self, proposal: dict) -> TradingType:
        if proposal["value"] not in (
            TradingType.LIVE,
            TradingType.SIMULATION,
            TradingType.SANDBOX,
            TradingType.BACKTEST,
        ):
            raise TraitError(f'Invalid trading type: {proposal["value"]}')
        return proposal["value"]

    @validate("exchanges")
    def _validate_exchanges(self, proposal: dict) -> ListType[Exchange]:
        for exch in proposal["value"]:
            if not isinstance(exch, Exchange):
                raise TraitError(f"Invalid exchange type: {exch}")
        return proposal["value"]

    def __init__(self, **config: dict) -> None:
        # get port for API access
        self.port = config.get("general", {}).get("port", self.port)

        # run in verbose mode (print all events)
        self.verbose = bool(int(config.get("general", {}).get("verbose", self.verbose)))

        # enable API access?
        self.api = bool(int(config.get("general", {}).get("api", self.api)))

        # override timezome
        self.tz = (
            pytz.timezone(config.get("general", {}).get("timezone", None))
            if config.get("general", {}).get("timezone", None)
            else None
        )

        # Trading type
        self.trading_type = TradingType(
            config.get("general", {}).get("trading_type", "simulation").upper()
        )

        # Load account information from exchanges
        self._load_accounts = config.get("general", {}).get("load_accounts", False)

        # Load exchange instances
        self.exchanges = getExchanges(
            config.get("exchange", {}).get("exchanges", []),
            trading_type=self.trading_type,
            verbose=self.verbose,
        )

        # instantiate the Strategy Manager
        self.manager = StrategyManager(
            self, self.trading_type, self.exchanges, self._load_accounts
        )

        # set event loop to use uvloop
        if uvloop:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

        # install event loop
        self.event_loop = asyncio.get_event_loop()

        # setup subscriptions
        self._handler_subscriptions: Dict[EventType, ListType] = {
            m: [] for m in EventType.__members__.values()
        }

        # setup `now` handler for backtest
        self._latest = (
            datetime.fromtimestamp(0, tz=self.tz) if self._offline() else datetime.now()
        )

        # register internal management event handler before all strategy handlers
        self.registerHandler(self.manager)

        # install event handlers
        self.strategies = getStrategies(
            config.get("strategy", {}).get("strategies", [])
        )

        for strategy in self.strategies:
            self.log.critical("Installing strategy: {}".format(strategy))
            self.registerHandler(strategy)

        # warn if no event handlers installed
        if not self.event_handlers:
            self.log.critical("Warning! No event handlers set")

        # install print handler if verbose
        if self.verbose:
            self.log.critical("Installing print handler")
            self.registerHandler(PrintHandler())

        # install webserver
        if self.api:
            self.log.critical("Installing API handlers")

            if PerspectiveManager is not None:
                table_handler = TableHandler()
                table_handler.installTables(self.table_manager)
                self.registerHandler(table_handler)

            self.api_handlers.append((r"/", RedirectHandler, {"url": "index.html"}))
            self.api_handlers.append(
                (
                    r"/api/v1/ws",
                    PerspectiveTornadoHandler,
                    {"manager": self.table_manager, "check_origin": True},
                )
            )
            self.api_handlers.append(
                (
                    r"/static/js/(.*)",
                    StaticFileHandler,
                    {
                        "path": os.path.join(
                            os.path.dirname(__file__),
                            "..",
                            "ui",
                            "assets",
                            "static",
                            "js",
                        )
                    },
                )
            )
            self.api_handlers.append(
                (
                    r"/static/css/(.*)",
                    StaticFileHandler,
                    {
                        "path": os.path.join(
                            os.path.dirname(__file__),
                            "..",
                            "ui",
                            "assets",
                            "static",
                            "css",
                        )
                    },
                )
            )
            self.api_handlers.append(
                (
                    r"/static/fonts/(.*)",
                    StaticFileHandler,
                    {
                        "path": os.path.join(
                            os.path.dirname(__file__),
                            "..",
                            "ui",
                            "assets",
                            "static",
                            "fonts",
                        )
                    },
                )
            )
            self.api_handlers.append(
                (
                    r"/(.*)",
                    StaticFileHandler,
                    {
                        "path": os.path.join(
                            os.path.dirname(__file__),
                            "..",
                            "ui",
                            "assets",
                            "static",
                            "html",
                        )
                    },
                )
            )

            self.api_application = ServerApplication(handlers=self.api_handlers)  # type: ignore

            self.log.critical(".......")
            self.log.critical(f"listening on 0.0.0.0:{self.port}")
            self.log.critical(".......")

            self.api_application.listen(self.port)

    def _offline(self) -> bool:
        return self.trading_type in (TradingType.BACKTEST, TradingType.SIMULATION)

    def registerHandler(self, handler: EventHandler) -> Optional[EventHandler]:
        """register a handler and all callbacks that handler implements

        Args:
            handler (EventHandler): the event handler to register
        Returns:
            value (EventHandler or None): event handler if its new, else None
        """
        if handler not in self.event_handlers:
            # append to handler list
            self.event_handlers.append(handler)

            # register callbacks for event types
            for type in EventType.__members__.values():
                # get callback or callback tuple
                # could be none if not implemented
                cbs = handler.callback(type)

                for cb in cbs:
                    if cb:
                        self.registerCallback(type, cb, handler)
            handler._setManager(self.manager)
            return handler
        return None

    def _make_async(self, function: Callable) -> Callable[..., Awaitable]:
        async def _wrapper(event: Event) -> Any:
            return await self.event_loop.run_in_executor(self.executor, function, event)

        return _wrapper

    def registerCallback(
        self, event_type: EventType, callback: Callable, handler: EventHandler = None
    ) -> bool:
        """register a callback for a given event type

        Args:
            event_type (EventType): event type enum value to register
            callback (function): function to call on events of `event_type`
            handler (EventHandler): class holding the callback (optional)
        Returns:
            value (bool): True if registered (new), else False
        """
        if (callback, handler) not in self._handler_subscriptions[event_type]:
            if not asyncio.iscoroutinefunction(callback):
                callback = self._make_async(callback)
            self._handler_subscriptions[event_type].append((callback, handler))
            return True
        return False

    async def pushEvent(self, event: Event) -> None:
        """push non-exchange event into the queue"""
        await self._queued_events.put(event)

    async def pushTargetedEvent(self, strategy: Strategy, event: Event) -> None:
        """push non-exchange event targeted to a specific strat into the queue"""
        await self._queued_targeted_events.put((event, strategy))

    async def _wraptick(self, ticker) -> Event:  # type: ignore
        async for ev in ticker:
            yield ev
        yield Event(type=EventType.EXIT, target=None)

    async def run(self) -> None:
        """run the engine"""
        # setup future queue
        self._queued_events: Queue[Event] = Queue()
        self._queued_targeted_events: Queue[Tuple[Event, Strategy]] = Queue()
        self._futures: Deque[Future] = deque()

        # await all connections
        await asyncio.gather(
            *(asyncio.ensure_future(exch.connect()) for exch in self.exchanges)
        )
        await asyncio.gather(
            *(asyncio.ensure_future(exch.instruments()) for exch in self.exchanges)
        )

        # send start event to all callbacks
        await self.processEvent(Event(type=EventType.START, target=None))

        # **************** #
        # Main event loop
        # **************** #
        async with merge(
            self._tick_queued_events(),
            self._tick_queued_targeted_events(),
            *(
                self._wraptick(exch.tick())
                for exch in self.exchanges + [self]
                if inspect.isasyncgenfunction(exch.tick)
            ),
        ).stream() as stream:
            # stream through all events
            async for event in stream:
                # unpack targetted events
                if isinstance(event, tuple):
                    event, strategy = event
                else:
                    strategy = None

                # if done event
                if event.type == EventType.EXIT:
                    break

                # TODO move out of critical path
                if self._offline():
                    # handle timezone
                    if (
                        hasattr(event, "target")
                        and hasattr(event.target, "timestamp")
                        and self._latest.tzinfo
                        and not event.target.timestamp.tzinfo
                    ):
                        # assume in local time
                        event.target.timestamp = event.target.timestamp.replace(
                            tzinfo=self._latest.tzinfo
                        )

                    # inject periodics
                    # TODO optimize
                    # Manager should keep track of the intervals for its periodics,
                    # then we don't need to go through seconds (which is what the
                    # live engine's `tick` method does below). Instead we can just
                    # calculate exactly the intervals
                    if (
                        self._latest != datetime.fromtimestamp(0, tz=self.tz)
                        and hasattr(event, "target")
                        and hasattr(event.target, "timestamp")
                    ):
                        # TODO in progress optimization
                        intervals = self.manager.periodicIntervals()

                        # not the first tick
                        for _ in range(
                            int(
                                (event.target.timestamp - self._latest).total_seconds()
                                / intervals
                            )
                        ):
                            print(
                                "{} - {}".format(event.target.timestamp, self._latest)
                            )
                            self._latest = self._latest + timedelta(
                                seconds=1 * intervals
                            )
                            if any(
                                p.expires(self._latest)
                                for p in self.manager.periodics()
                            ):
                                await asyncio.gather(
                                    *(
                                        asyncio.create_task(p.execute(self._latest))
                                        for p in self.manager.periodics()
                                        if p.expires(self._latest)
                                    )
                                )

                # tick exchange event to handlers
                self._futures.extend(await self.processEvent(event, strategy))

                # TODO move out of critical path
                if self._offline():
                    # use time of last event
                    self._latest = (
                        event.target.timestamp
                        if hasattr(event, "target")
                        and hasattr(event.target, "timestamp")
                        else self._latest
                    )
                else:
                    # use now
                    self._latest = datetime.now(tz=self.tz)

                # process any periodics
                self._futures.extend(
                    [
                        asyncio.create_task(p.execute(self._latest))
                        for p in self.manager.periodics()
                        if p.expires(self._latest)
                    ]
                )

                remaining_futures: Deque[Future] = deque()
                for fut in self._futures:
                    if fut.done():
                        # trigger exception if necessary
                        fut.result()
                    else:
                        remaining_futures.append(fut)
                self._futures = remaining_futures

        # Before engine shutdown, send an exit event
        await self.processEvent(Event(type=EventType.EXIT, target=None))

    async def _tick_queued_events(self) -> AsyncGenerator[Event, None]:
        while True:
            yield await self._queued_events.get()

    async def _tick_queued_targeted_events(
        self,
    ) -> AsyncGenerator[Tuple[Event, Strategy], None]:
        while True:
            yield await self._queued_targeted_events.get()

    async def processEvent(
        self, event: Event, strategy: Strategy = None
    ) -> ListType[Future]:
        """send an event to all registered event handlers

        Arguments:
            event (Event): event to send
        """
        ret: ListType[Future] = []
        if event.type == EventType.HEARTBEAT:
            # ignore heartbeat
            return ret

        for callback, handler in self._handler_subscriptions[event.type]:
            # TODO make cleaner? move to somewhere not in critical path?
            if strategy is not None and (handler not in (strategy, self.manager)):
                continue

            # TODO make cleaner? move to somewhere not in critical path?
            if (
                event.type
                in (
                    EventType.TRADE,
                    EventType.OPEN,
                    EventType.CHANGE,
                    EventType.CANCEL,
                    EventType.DATA,
                )
                and not self.manager.dataSubscriptions(handler, event)
            ):
                continue

            try:
                ret.append(asyncio.ensure_future(callback(event)))
            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                if event.type == EventType.ERROR:
                    # don't infinite error
                    raise
                await asyncio.sleep(1)
                return [
                    asyncio.ensure_future(
                        self.processEvent(
                            Event(
                                type=EventType.ERROR,
                                target=Error(
                                    target=event,
                                    handler=handler,
                                    callback=callback,
                                    exception=e,
                                ),
                            )
                        )
                    )
                ]
        return ret

    async def tick(self) -> AsyncGenerator:
        """helper method to ensure periodic methods execute periodically in absence
        of market data"""

        if self._offline():
            # periodics injected manually, see main event loop above
            while True:
                yield Event(type=EventType.HEARTBEAT, target=None)
                await asyncio.sleep(0)
            return

        while True:
            yield Event(type=EventType.HEARTBEAT, target=None)
            await asyncio.sleep(1)

    def now(self) -> datetime:
        """Return the current datetime. Useful to avoid code changes between
        live trading and backtesting. Defaults to `datetime.now`"""
        return (
            self._latest
            if self.trading_type == TradingType.BACKTEST
            else datetime.now(tz=self.tz)
        )

    def start(self) -> None:
        try:
            # if self.event_loop.is_running():
            #     # return future
            #     return asyncio.create_task(self.run())
            # block until done
            self.event_loop.run_until_complete(self.run())
        except KeyboardInterrupt:
            pass

        # FIXME double sending due to wraptick
        # send exit event to all callbacks
        # self.event_loop.run_until_complete(self.processEvent(Event(type=EventType.EXIT, target=None)))
