from aat.config import Side
from aat.core import Order
from collections import deque
from typing import Dict, Deque, Optional


class SpreadReconstitute(object):
    def __init__(self) -> None:
        self._orders: Dict[str, Dict[Side, Deque[Order]]] = {}

    def push(self, order: Order) -> None:
        if order.id not in self._orders:
            self._orders[order.id] = {Side.BUY: deque(), Side.SELL: deque()}

        self._orders[order.id][order.side].append(order)

    def get(self, originalOrder: Order) -> Optional[Order]:
        if originalOrder.id not in self._orders:
            return None

        if (
            self._orders[originalOrder.id][Side.BUY]
            and self._orders[originalOrder.id][Side.SELL]
        ):
            # if orders on both sides, pop out and assemble unified order
            buy = self._orders[originalOrder.id][Side.BUY].popleft()
            sell = self._orders[originalOrder.id][Side.SELL].popleft()

            # need to move in lock step for now
            assert buy.volume == sell.volume

            order = Order(
                volume=buy.volume,
                price=buy.price - sell.price,
                side=originalOrder.side,
                instrument=originalOrder.instrument,
                exchange=originalOrder.exchange,
                order_type=originalOrder.order_type,
                id=originalOrder.id,
                timestamp=originalOrder.timestamp,
            )

            return order

        return None
