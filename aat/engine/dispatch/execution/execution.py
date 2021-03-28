from typing import TYPE_CHECKING, cast, Dict, List, Optional, Tuple

from aat import AATException
from aat.core import Order, Event, Trade, ExchangeType
from aat.core.handler import EventHandler
from aat.exchange import Exchange
from ..base import ManagerBase


if TYPE_CHECKING:
    from aat.strategy import Strategy
    from ..manager import StrategyManager


class OrderManager(ManagerBase):
    def __init__(self) -> None:
        # map exchangetype to exchange instance
        self._exchanges: Dict[ExchangeType, Exchange] = {}

        # for race conditions where trade/cancel comes before acknowledgement
        self._pending_action: List[Tuple[Order, "Strategy"]] = []

        # track which strategies generated which orders
        self._pending_orders: Dict[
            str, Tuple[Order, "Strategy"]
        ] = {}  # lookup strategy by order

        # past orders
        self._past_orders: Dict[
            str, Tuple[Order, "Strategy"]
        ] = {}  # lookup strategy by order

    def addExchange(self, exchange: Exchange) -> None:
        """add an exchange"""
        self._exchanges[exchange.exchange()] = exchange

    def _setManager(self, manager: "StrategyManager") -> None:  # type: ignore
        """install manager"""
        self._manager = manager

    # *********************
    # Order Entry Methods *
    # *********************
    async def newOrder(self, strategy: Optional["Strategy"], order: Order) -> bool:
        exchange = self._exchanges.get(order.exchange)
        if not exchange:
            raise Exception("Exchange not installed: {}".format(order.exchange))

        # stash in case execution occurs before newOrder returns
        self._pending_action.append((order, cast("Strategy", strategy)))

        # tell exchange to submit
        ret = await exchange.newOrder(order)

        if ret:
            # if received, store in pending and return to caller
            self._pending_orders[order.id] = (order, cast("Strategy", strategy))

        if (order, strategy) in self._pending_action:
            # remove from pre pending
            self._pending_action.remove((order, cast("Strategy", strategy)))

            # tell manager it was received/rejected
            if ret:
                await self._manager._onReceived(cast("Strategy", strategy), order)
            else:
                await self._manager._onRejected(cast("Strategy", strategy), order)

        # return to caller
        return ret

    async def cancelOrder(self, strategy: Optional["Strategy"], order: Order) -> bool:
        exchange = self._exchanges.get(order.exchange)
        if not exchange:
            raise AATException("Exchange not installed: {}".format(order.exchange))

        # stash in case cancel occurs before cancelOrder returns
        self._pending_action.append((order, cast("Strategy", strategy)))

        # tell exchange to cancel
        ret = await exchange.cancelOrder(order)

        if ret:
            # if cancelled, remove from pending and return to caller
            self._pending_orders.pop(order.id, None)

            if (order, strategy) in self._pending_action:
                # remove from pre pending
                self._pending_action.remove((order, cast("Strategy", strategy)))

            # tell manager it was canceled/rejected
            await self._manager._onCanceled(cast("Strategy", strategy), order)

        else:
            await self._manager._onRejected(cast("Strategy", strategy), order)

        # return to caller
        return ret

    # **********************
    # EventHandler methods *
    # **********************
    async def onTrade(self, event: Event) -> None:
        """Match trade with order"""
        action: bool = False
        ooo: bool = False  # execution is out of order with receipt
        strat: Optional["Strategy"] = None
        trade: Trade = cast(Trade, event.target)

        # if it comes with the order, use that
        if trade.my_order:
            action = True

            # lookup order
            if trade.my_order.id in self._pending_orders:
                # grab order and strategy from pending orders
                order, strat = self._pending_orders[trade.my_order.id]
            elif trade.my_order.id in self._past_orders:
                # duplicate message, ignore
                return
            else:
                # execution was out of order, look which orders are pending actions
                lookup = [x for x in self._pending_action if x[0] == trade.my_order]
                ooo = True

                if not lookup:
                    # no trace of this order, so bail
                    raise AATException(
                        "Exchange did not acknowledge order before trade!"
                    )

                # TODO more than one? probably not due to setting of ID
                order, strat = lookup[0]

                # remove from pending action, processing here
                self._pending_action.remove((order, strat))

                # add to pending for future lookups
                if not order.finished():
                    self._pending_orders[order.id] = (order, strat)

            # FIXME
            trade.id = trade.my_order.id

        # otherwise derive from mapping
        else:
            for maker_order in trade.maker_orders:
                if maker_order.id in self._pending_orders:
                    action = True
                    order, strat = self._pending_orders[maker_order.id]

                    # TODO cleaner?
                    trade.my_order = order
                    # FIXME
                    trade.id = order.id
                    order.filled = maker_order.filled
                    break

            if trade.taker_order.id in self._pending_orders:
                action = True
                order, strat = self._pending_orders[trade.taker_order.id]

                # TODO cleaner?
                trade.my_order = order
                # FIXME
                trade.id = order.id
                order.filled = trade.taker_order.filled

        if action:
            if ooo:
                # execution occurred before order acknowledge,
                # so send receipt first
                await self._manager._onReceived(cast("Strategy", strat), trade.my_order)

            if order.side == Order.Sides.SELL:
                await self._manager._onSold(cast("Strategy", strat), trade)
            else:
                await self._manager._onBought(cast("Strategy", strat), trade)

            if order.finished():
                self._pending_orders.pop(order.id, None)
                self._past_orders[order.id] = (order, cast("Strategy", strat))

    async def onCancel(self, event: Event) -> None:
        canceled_order: Order = cast(Order, event.target)
        if canceled_order.id in self._pending_orders:
            order, strat = self._pending_orders[canceled_order.id]

            # TODO second look, just in case
            order.filled = canceled_order.filled

            # TODO ugly private method
            await self._manager._onCanceled(cast("Strategy", strat), order)
            self._pending_orders.pop(canceled_order.id, None)

        else:
            # cancel was out of order, look which orders are pending actions
            lookup = [x for x in self._pending_action if x[0] == order]

            if not lookup:
                # no trace of this order, so bail
                # raise AATException("Exchange did not acknowledge order before cancel!")
                ...  # TODO

            # TODO more than one? probably not due to setting of ID
            order, strat = lookup[0]

            # remove from pending action, processing here
            self._pending_action.remove((order, strat))

            await self._manager._onCanceled(cast("Strategy", strat), order)

    async def onOpen(self, event: Event) -> None:
        # TODO
        pass

    async def onFill(self, event: Event) -> None:
        # TODO
        pass

    async def onChange(self, event: Event) -> None:
        # TODO
        pass

    async def onData(self, event: Event) -> None:
        # TODO
        pass

    async def onHalt(self, event: Event) -> None:
        # TODO
        pass

    async def onContinue(self, event: Event) -> None:
        # TODO
        pass

    async def onError(self, event: Event) -> None:
        # TODO
        pass

    async def onStart(self, event: Event) -> None:
        # TODO
        pass

    async def onExit(self, event: Event) -> None:
        # TODO
        pass

    #########################
    # Order Entry Callbacks #
    #########################
    async def onTraded(  # type: ignore[override]
        self, event: Event, strategy: Optional[EventHandler]
    ) -> None:
        # TODO
        pass

    async def onReceived(  # type: ignore[override]
        self, event: Event, strategy: Optional[EventHandler]
    ) -> None:
        # TODO
        pass

    async def onRejected(  # type: ignore[override]
        self, event: Event, strategy: Optional[EventHandler]
    ) -> None:
        # TODO
        pass

    async def onCanceled(  # type: ignore[override]
        self, event: Event, strategy: Optional[EventHandler]
    ) -> None:
        # TODO
        pass
