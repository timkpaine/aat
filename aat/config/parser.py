import argparse
import importlib
import itertools
import os
import os.path
import pytz
from configparser import ConfigParser
from typing import Any, Dict, List, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from aat.config import TradingType


def _config_to_dict(
    filename: str,
) -> Dict[str, Dict[str, Union[str, List[str], List[List[str]]]]]:
    if not os.path.exists(filename):
        raise Exception(f"File does not exist {filename}")
    config = ConfigParser()
    config.read(filename)

    ret = {}  # type: Dict[str, Dict[str, Union[str, List[str], List[List[str]]]]]

    for s in config.sections():
        d: Dict[str, str] = dict(config.items(s))
        ret[s] = {}
        for k, v in d.items():
            if v.startswith("\n"):
                ret[s][k] = v.strip().split("\n")
                for i, item in enumerate(ret[s][k]):
                    if "," in item:
                        ret[s][k][i] = item.strip().split(",")  # type: ignore
            elif "," in v:
                ret[s][k] = v.strip().split(",")
            else:
                ret[s][k] = v
    return ret


def _args_to_dict(args: Any) -> dict:
    ret: Dict[str, Dict[str, Union[str, list, bool]]] = {}
    ret["general"] = {}
    ret["general"]["verbose"] = args.verbose
    ret["general"]["trading_type"] = args.trading_type
    ret["general"]["load_accounts"] = args.load_accounts
    ret["general"]["api"] = args.api
    ret["general"]["timezone"] = args.timezone
    ret["exchange"] = {
        "exchanges": list(
            _.split(",") for _ in itertools.chain.from_iterable(args.exchanges)
        )
    }
    ret["strategy"] = {
        "strategies": list(itertools.chain.from_iterable(args.strategies))
    }
    return ret


def getStrategies(strategies: List) -> List:
    strategy_instances = []

    if not strategies:
        raise Exception("Must provide strategies")

    for strategy in strategies:
        if isinstance(strategy, list):
            mod, clazz = strategy[0].split(":")
            args = strategy[1:]
        else:
            mod, clazz = strategy.split(":")
            if "," in clazz:
                clazz, temp_args = clazz.split(",", maxsplit=1)
                args = temp_args.split(",")
            else:
                args = []
        mod = importlib.import_module(mod)
        clazz = getattr(mod, clazz)
        strategy_instances.append(clazz(*args))
    return strategy_instances


def getExchanges(
    exchanges: List, trading_type: "TradingType", verbose: bool = False
) -> List:
    exchange_instances = []

    if not exchanges:
        raise Exception("Must provide exchanges")

    for exchange in exchanges:
        if isinstance(exchange, list):
            mod, clazz = exchange[0].split(":")
            args = exchange[1:]
        else:
            mod, clazz = exchange.split(":")
            args = []
        mod = importlib.import_module(mod)
        clazz = getattr(mod, clazz)
        exchange_instances.append(clazz(trading_type, verbose, *args))
    return exchange_instances


def parseConfig(argv: list = None) -> dict:
    from aat import TradingType

    parser = argparse.ArgumentParser()

    parser.add_argument("--config", help="Config file", default="")

    parser.add_argument(
        "--verbose", action="store_true", help="Run in verbose mode", default=False
    )

    parser.add_argument(
        "--api", action="store_true", help="Enable HTTP server", default=False
    )

    parser.add_argument(
        "--timezone", help="Timezone override", default="", choices=pytz.all_timezones
    )

    parser.add_argument(
        "--load_accounts",
        action="store_true",
        help="Load accounts from exchanges",
        default=False,
    )

    parser.add_argument(
        "--trading_type",
        help='Trading Type in ("live", "sandbox", "simulation", "backtest")',
        choices=[_.lower() for _ in TradingType.members()],
        default="simulation",
    )

    parser.add_argument(
        "--strategies",
        action="append",
        nargs="+",
        help="Strategies to run in form <path.to.module:Class,args,for,strat>",
        default=[],
    )

    parser.add_argument(
        "--exchanges",
        action="append",
        nargs="+",
        help="Exchanges to run on",
        default=[],
    )

    args = parser.parse_args(argv)

    # Every engine run requires a static config object
    if args.config:
        return _config_to_dict(args.config)

    return _args_to_dict(args)
