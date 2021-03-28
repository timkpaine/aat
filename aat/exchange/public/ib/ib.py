import asyncio
import threading
from datetime import datetime
from queue import Queue
from random import randint
from typing import Any, AsyncGenerator, Dict, List, Set, Tuple, Union

from aat.config import EventType, Side, TradingType
from aat.core import Event, ExchangeType, Instrument
from aat.core import Order as AATOrder
from aat.core import Position, Trade
from aat.exchange import Exchange
from ibapi.client import EClient  # type: ignore
from ibapi.commission_report import CommissionReport  # type: ignore
from ibapi.contract import Contract  # type: ignore
from ibapi.execution import Execution, ExecutionFilter  # type: ignore
from ibapi.order import Order  # type: ignore
from ibapi.wrapper import EWrapper  # type: ignore

from .utils import _constructContract, _constructContractAndOrder, _constructInstrument


class _API(EWrapper, EClient):
    def __init__(
        self,
        account: str,
        exchange: ExchangeType,
        delayed: bool,
        order_event_queue: Queue,
        market_data_queue: Queue,
        contract_info_queue: Queue,
        account_position_queue: Queue,
    ) -> None:
        EClient.__init__(self, self)
        self.nextOrderId: int = 1
        self.nextReqId = 1

        # account # if more than one
        self._account = account

        # exchange
        self._exchange = exchange

        # delayed data?
        self._delayed = delayed

        self._mkt_data_map: Dict[int, Tuple[Contract, Instrument]] = {}
        self._mkt_data_map_rev: Dict[Contract, int] = {}

        self._order_event_queue = order_event_queue
        self._market_data_queue = market_data_queue
        self._contract_info_queue = contract_info_queue
        self._account_position_queue = account_position_queue

        self._positions: List[Position] = []

    def reqPositions(self) -> None:
        super().reqPositions()

    def nextValidId(self, orderId: int) -> None:
        super().nextValidId(orderId)
        self.nextOrderId = orderId

    def reqContractDetails(self, contract: Contract) -> None:
        super().reqContractDetails(self.nextReqId, contract)
        self.nextReqId += 1

    def placeOrder(self, contract: Contract, order: Order) -> str:
        order.account = self._account
        super().placeOrder(self.nextOrderId, contract, order)
        self.nextOrderId += 1
        return str(self.nextOrderId - 1)

    def cancelOrder(self, order: AATOrder) -> None:
        super().cancelOrder(order.id)

    def contractDetails(self, reqId: int, contractDetails: dict) -> None:
        self._contract_info_queue.put(contractDetails)

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: str,
        parentId: str,
        lastFillPrice: float,
        clientId: str,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        self._order_event_queue.put(
            dict(
                orderId=orderId,
                status=status,
                filled=filled,
                #  remaining=remaining,  # TODO not used
                avgFillPrice=avgFillPrice,
                #  permId=permId,  # TODO not used
                #  parentId=parentId,  # TODO not used
                #  lastFillPrice=lastFillPrice,  # TODO not used
                #  clientId=clientId,  # TODO not used
                #  whyHeld=whyHeld,  # TODO not used
                #  mktCapPrice=mktCapPrice  # TODO not used
            )
        )

    def subscribeMarketData(self, instrument: Instrument) -> None:
        contract = _constructContract(instrument)
        self._mkt_data_map[self.nextReqId] = (contract, instrument)
        self._mkt_data_map_rev[contract] = self.nextReqId

        if self._delayed:
            self.reqMarketDataType(3)

        self.reqMktData(self.nextReqId, contract, "", False, False, [])
        self.nextReqId += 1

    def cancelMarketData(self, contract: Contract) -> None:
        id = self._mkt_data_map_rev[contract]
        self.cancelMktData(id)
        del self._mkt_data_map_rev[contract]
        del self._mkt_data_map[id]

    def reqExecutions(self) -> None:
        super().reqExecutions(self.nextReqId, ExecutionFilter())
        self.nextReqId += 1

    def execDetails(self, reqId: int, contract: Contract, execution: Execution) -> None:
        super().execDetails(reqId, contract, execution)
        self._order_event_queue.put(
            dict(
                orderId=execution.orderId,
                status="Execution",
                filled=execution.cumQty,
                #  remaining=-1,  # TODO not available here
                avgFillPrice=execution.avgPrice,  # TODO execution.price?
                #  permId=permId,  # TODO not used
                #  parentId=parentId,  # TODO not used
                #  lastFillPrice=lastFillPrice,  # TODO not used
                #  clientId=clientId,  # TODO not used
                #  whyHeld=whyHeld,  # TODO not used
                #  mktCapPrice=mktCapPrice  # TODO not used
            )
        )

    def commissionReport(self, commissionReport: CommissionReport) -> None:
        super().commissionReport(commissionReport)
        # TODO?

    def execDetailsEnd(self, reqId: int) -> None:
        super().execDetailsEnd(reqId)
        # TODO?

    def error(self, reqId: int, errorCode: int, errorString: str) -> None:
        if errorCode in (
            110,  # The price does not conform to the minimum price variation for this contract.
            201,  # Order rejected - Reason:
        ):
            self._order_event_queue.put(
                dict(
                    orderId=reqId,
                    status="Rejected",
                )
            )
        elif errorCode in (
            136,  # This order cannot be cancelled.
            161,  # Cancel attempted when order is not in a cancellable state. Order permId =
            10148,  # OrderId <OrderId> that needs to be cancelled can not be cancelled, state:
        ):
            self._order_event_queue.put(
                dict(
                    orderId=reqId,
                    status="RejectedCancel",
                )
            )
        elif errorCode in (202,):  # Order cancelled - Reason:
            ...
            # also sends event, don't need to handle error here
            # self._order_event_queue.put(
            #     dict(
            #         orderId=reqId,
            #         status="Cancelled",
            #     )
            # )
        else:
            super().error(reqId, errorCode, errorString)

    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: str) -> None:
        # TODO implement more of order book

        if self._delayed:
            tick_type = 68  # delayed last
        else:
            tick_type = 4  # last

        if tickType == tick_type:
            self._market_data_queue.put(
                dict(
                    contract=self._mkt_data_map[reqId][0],
                    instrument=self._mkt_data_map[reqId][1],
                    price=price,
                )
            )

    def position(
        self, account: str, contract: Contract, position: float, avgCost: float
    ) -> None:
        super().position(account, contract, position, avgCost)
        self._positions.append(
            Position(
                size=position,
                price=avgCost / position,
                timestamp=datetime.now(),
                instrument=_constructInstrument(contract),
                exchange=self._exchange,
                trades=[],
            )
        )

    def accountSummaryEnd(self, reqId: int) -> None:
        self._account_position_queue.put(self._positions)
        self._positions = []


class InteractiveBrokersExchange(Exchange):
    """Interactive Brokers Exchange"""

    def __init__(
        self,
        trading_type: TradingType,
        verbose: bool,
        account: str = "",
        delayed: bool = True,
        **kwargs: dict
    ) -> None:
        self._trading_type = trading_type
        self._verbose = verbose

        if self._trading_type == TradingType.LIVE:
            super().__init__(ExchangeType("interactivebrokers"))
        else:
            super().__init__(ExchangeType("interactivebrokerspaper"))

        # map order.id to order
        self._orders: Dict[str, Order] = {}

        # map order id to received event
        self._order_received_map_set: Dict[str, asyncio.Event] = {}
        self._order_received_map_get: Dict[str, asyncio.Event] = {}
        self._order_received_res: Dict[str, bool] = {}

        # map order id to cancelled event
        self._order_cancelled_map_set: Dict[str, asyncio.Event] = {}
        self._order_cancelled_map_get: Dict[str, asyncio.Event] = {}
        self._order_cancelled_res: Dict[str, bool] = {}

        # track "finished" orders so we can ignore them
        self._finished_orders: Set[str] = set()

        # IB TWS gateway
        self._order_event_queue: Queue[Dict[str, Union[str, int, float]]] = Queue()
        self._market_data_queue: Queue[
            Dict[str, Union[str, int, float, Instrument]]
        ] = Queue()
        self._contract_lookup_queue: Queue[Contract] = Queue()
        self._account_position_queue: Queue[Position] = Queue()
        self._api = _API(
            account,
            self.exchange(),
            delayed,
            self._order_event_queue,
            self._market_data_queue,
            self._contract_lookup_queue,
            self._account_position_queue,
        )

    # *************** #
    # General methods #
    # *************** #
    async def instruments(self) -> List[Instrument]:
        """get list of available instruments"""
        return []

    async def connect(self) -> None:
        """connect to exchange. should be asynchronous.

        For OrderEntry-only, can just return None
        """
        if self._trading_type == TradingType.LIVE:
            print("*" * 100)
            print("*" * 100)
            print("WARNING: LIVE TRADING")
            print("*" * 100)
            print("*" * 100)
            self._api.connect("127.0.0.1", 7496, randint(0, 10000))
            self._api_thread = threading.Thread(target=self._api.run, daemon=True)
            self._api_thread.start()

        else:
            self._api.connect("127.0.0.1", 7497, randint(0, 10000))
            self._api_thread = threading.Thread(target=self._api.run, daemon=True)
            self._api_thread.start()

        while self._api.nextOrderId is None:
            print("waiting for IB connect...")
            await asyncio.sleep(1)

        print("IB connected!")

    async def lookup(self, instrument: Instrument) -> List[Instrument]:
        self._api.reqContractDetails(_constructContract(instrument))
        i = 0
        while i < 5:
            if self._contract_lookup_queue.qsize() > 0:
                ret = []
                while self._contract_lookup_queue.qsize() > 0:
                    contract_details = self._contract_lookup_queue.get()
                    ret.append(_constructInstrument(contract_details.contract))
                return ret
            else:
                await asyncio.sleep(1)
                i += 1
        return []

    # ******************* #
    # Market Data Methods #
    # ******************* #
    async def subscribe(self, instrument: Instrument) -> None:
        self._api.subscribeMarketData(instrument)

    def _create_order_received(self, orderId: str) -> None:
        # create initial event
        self._order_received_map_get[orderId] = asyncio.Event()
        self._order_received_map_set[orderId] = asyncio.Event()

    async def _send_order_received(
        self, orderId: str, ret: bool, waitfor: bool = True
    ) -> None:
        # set result
        self._order_received_res[orderId] = ret

        # if setter exists, set it
        if orderId in self._order_received_map_set:
            self._order_received_map_set[orderId].set()

            # let the event be consumed
            await asyncio.sleep(0)

            # wait for result to be consumed
            await self._order_received_map_get[orderId].wait()

    async def _send_cancel_received(
        self, orderId: str, ret: bool, waitfor: bool = True
    ) -> None:
        # set result
        self._order_cancelled_res[orderId] = ret

        # if setter exists, set it
        if orderId in self._order_cancelled_map_set:
            self._order_cancelled_map_set[orderId].set()

            # let the event be consumed
            await asyncio.sleep(0)

            # wait for result to be consumed
            await self._order_cancelled_map_get[orderId].wait()

    async def _consume_order_received(self, orderId: str) -> bool:
        # if already received result
        if orderId in self._order_received_res:
            return self._order_received_res.pop(orderId)

        # if already waiting for result, reject
        if orderId in self._order_received_map_set:
            return False

        # initialize events
        self._order_received_map_get[orderId] = asyncio.Event()
        self._order_received_map_set[orderId] = asyncio.Event()

        # wait for it to be set
        await self._order_received_map_set[orderId].wait()

        # trigger getter
        self._order_received_map_get[orderId].set()

        # let setter finish
        return self._order_received_res.pop(orderId)

    async def _consume_cancel_received(self, orderId: str) -> bool:
        # if already received result
        if orderId in self._order_cancelled_res:
            return self._order_cancelled_res.pop(orderId)

        # if already waiting for result, reject
        if orderId in self._order_cancelled_map_set:
            return False

        # initialize events
        self._order_cancelled_map_get[orderId] = asyncio.Event()
        self._order_cancelled_map_set[orderId] = asyncio.Event()

        # wait for it to be set
        await self._order_cancelled_map_set[orderId].wait()

        # trigger getter
        self._order_cancelled_map_get[orderId].set()

        # if finished, add to finished
        if self._order_cancelled_res[orderId]:
            self._finished_orders.add(orderId)

        # let setter finish
        return self._order_cancelled_res.pop(orderId)

    async def tick(self) -> AsyncGenerator[Any, Event]:  # type: ignore[override]
        """return data from exchange"""
        while True:
            # clear order events
            while self._order_event_queue.qsize() > 0:
                order_data = self._order_event_queue.get()
                status = order_data["status"]
                order = self._orders[str(order_data["orderId"])]
                if status in (
                    "ApiPending",
                    "PendingSubmit",
                    "PendingCancel",
                    "PreSubmitted",
                    "ApiCancelled",
                ):
                    # ignore
                    continue

                elif status in ("Inactive",):
                    self._finished_orders.add(order.id)

                elif status in ("Rejected",):
                    self._finished_orders.add(order.id)
                    await self._send_order_received(order.id, False)

                elif status in ("RejectedCancel",):
                    await self._send_cancel_received(order.id, False)

                elif status in ("Submitted",):
                    await self._send_order_received(order.id, True)

                elif status in ("Cancelled",):
                    self._finished_orders.add(order.id)
                    await self._send_cancel_received(order.id, True)

                elif status in ("Filled",):
                    # this is the filled from orderStatus, but we
                    # want to use the one from execDetails

                    # From the IB Docs:
                    # "There are not guaranteed to be orderStatus
                    # callbacks for every change in order status"
                    # It is recommended to use execDetails

                    # ignore
                    pass

                elif status in ("Execution",):
                    # set filled
                    order.filled = order_data["filled"]

                    # finish order if fully filled
                    if order.finished():
                        self._finished_orders.add(order.id)

                        # create trade object
                    t = Trade(
                        volume=order_data["filled"],  # type: ignore
                        price=order_data["avgFillPrice"],  # type: ignore
                        maker_orders=[],
                        taker_order=order,
                    )

                    # set my order
                    # FIXME this isnt technically necessary as
                    # the engine should do this automatically
                    t.my_order = order

                    e = Event(type=EventType.TRADE, target=t)

                    # if submitted was skipped, clear out the wait
                    await self._send_order_received(order.id, True)
                    yield e

            # clear market data events
            while self._market_data_queue.qsize() > 0:
                market_data = self._market_data_queue.get()
                instrument: Instrument = market_data["instrument"]  # type: ignore
                price: float = market_data["price"]  # type: ignore
                o = AATOrder(
                    volume=1,
                    price=price,
                    side=Side.BUY,
                    instrument=instrument,
                    exchange=self.exchange(),
                    filled=1,
                )
                t = Trade(volume=1, price=float(price), taker_order=o, maker_orders=[])
                yield Event(type=EventType.TRADE, target=t)

            await asyncio.sleep(0)

        # clear market data events
        # TODO

    # ******************* #
    # Order Entry Methods #
    # ******************* #
    async def accounts(self) -> List[Position]:  # TODO account
        """get accounts from source"""
        self._api.reqPositions()
        i = 0
        while i < 5:
            if self._account_position_queue.qsize() > 0:
                return [self._account_position_queue.get()]
            else:
                await asyncio.sleep(1)
                i += 1
        return []

    async def newOrder(self, order: AATOrder) -> bool:
        """submit a new order to the exchange. should set the given order's `id` field to exchange-assigned id

        For MarketData-only, can just return None
        """
        # ignore if already finished
        if order.id and order.id in self._finished_orders:
            return False

        # construct IB contract and order
        ibcontract, iborder = _constructContractAndOrder(order)

        _temp_id = str(self._api.nextOrderId)

        # pre update order id since ib runs on thread
        order.id = _temp_id
        self._orders[order.id] = order

        # send to IB
        self._api.placeOrder(ibcontract, iborder)

        # update order id
        return await self._consume_order_received(_temp_id)

    async def cancelOrder(self, order: AATOrder) -> bool:
        """cancel a previously submitted order to the exchange.

        For MarketData-only, can just return None
        """
        # ignore if order not submitted yet
        if not order.id:
            return False

        # ignore if already finished
        if order.id in self._finished_orders:
            return False

        # send to IB
        self._api.cancelOrder(order)

        # wait for IB to respond
        return await self._consume_cancel_received(order.id)
