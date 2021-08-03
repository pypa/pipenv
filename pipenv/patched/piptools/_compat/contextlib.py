# Ported from python 3.7 contextlib.py
from types import TracebackType
from typing import Optional, Type, TypeVar

_T = TypeVar("_T")


class nullcontext:
    """Context manager that does no additional processing.
    Used as a stand-in for a normal context manager, when a particular
    block of code is only sometimes used with a normal context manager:
    cm = optional_cm if condition else nullcontext()
    with cm:
        # Perform operation, using optional_cm if condition is True

    TODO: replace with `contextlib.nullcontext()` after Python 3.6 being dropped
    """

    def __init__(self, enter_result: _T) -> None:
        self.enter_result = enter_result

    def __enter__(self) -> _T:
        return self.enter_result

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        pass
