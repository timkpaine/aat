from datetime import datetime
from traceback import format_exception
from typing import Any, Callable, Dict, Union
from ...config import DataType


class Error(object):
    __slots__ = [
        "__target",
        "__exception",
        "__callback",
        "__handler",
        "__timestamp",
        "__type",
    ]

    def __init__(
        self,
        target: Any,
        exception: BaseException,
        callback: Callable,
        handler: Callable,
        **kwargs: Any,
    ) -> None:
        self.__timestamp = kwargs.get("timestamp", datetime.now())
        self.__type = DataType.ERROR
        self.__target = target
        self.__exception = exception
        self.__callback = callback
        self.__handler = handler

    # ******** #
    # Readonly #
    # ******** #
    @property
    def timestamp(self) -> int:
        return self.__timestamp

    @timestamp.setter
    def timestamp(self, timestamp: datetime) -> None:
        assert isinstance(timestamp, datetime)
        self.__timestamp = timestamp

    @property
    def type(self) -> DataType:
        return self.__type

    @property
    def target(self) -> Any:
        return self.__target

    @property
    def exception(self) -> BaseException:
        return self.__exception

    @property
    def callback(self) -> Callable:
        return self.__callback

    @property
    def handler(self) -> Callable:
        return self.__handler

    def json(self, flat: bool = False) -> Dict[str, Union[str, int, float, dict]]:
        # TODO
        raise NotImplementedError()

    def __repr__(self) -> str:
        return f"Error( timestamp={self.timestamp}, callback={self.callback}, handler={self.handler}, exception={format_exception(type(self.exception), self.exception, self.exception.__traceback__)})"
