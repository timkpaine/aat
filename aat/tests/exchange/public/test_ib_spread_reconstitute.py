import sys
from mock import MagicMock
from aat.core import Order, Instrument
from aat.config import InstrumentType, Side

leg1 = Instrument(name="LEG1", type=InstrumentType.FUTURE)
leg2 = Instrument(name="LEG2", type=InstrumentType.FUTURE)
spread = Instrument(name="LEG1_LEG2", type=InstrumentType.SPREAD, leg1=leg1, leg2=leg2)


class Wrapper:
    ...


sys.modules["ibapi"] = MagicMock()
sys.modules["ibapi.client"] = MagicMock()
sys.modules["ibapi.client"].EClient = object  # type: ignore
sys.modules["ibapi.commission_report"] = MagicMock()
sys.modules["ibapi.contract"] = MagicMock()
sys.modules["ibapi.execution"] = MagicMock()
sys.modules["ibapi.order"] = MagicMock()
sys.modules["ibapi.wrapper"] = MagicMock()
sys.modules["ibapi.wrapper"].EWrapper = Wrapper  # type: ignore

from aat.exchange.public.ib.spread import SpreadReconstitute  # noqa: E402


class TestIBReconstituteSpread:
    def test_spread(self) -> None:

        sr = SpreadReconstitute()

        original_order = Order(10, 7, Side.BUY, spread)

        order1_l1 = Order(3, 10, Side.BUY, instrument=leg1)
        order1_l2 = Order(3, 2, Side.SELL, instrument=leg1)
        order1 = Order(3, 8, Side.BUY, instrument=spread)

        sr.push(order1_l1)

        assert sr.get(original_order) == None  # noqa: E711

        sr.push(order1_l2)

        assert sr.get(original_order) == order1

        order2_l1 = Order(7, 11, Side.BUY, instrument=leg1)
        order2_l2 = Order(7, 3, Side.SELL, instrument=leg1)
        order2 = Order(7, 8, Side.SELL, instrument=spread)

        sr.push(order2_l1)

        assert sr.get(original_order) == None  # noqa: E711

        sr.push(order2_l2)

        assert sr.get(original_order) == order2
