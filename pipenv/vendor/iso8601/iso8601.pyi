import datetime
import sys
from typing import Any, Mapping, Optional, Pattern, TypeVar


__all__ = ["parse_date", "ParseError", "UTC", "FixedOffset"]


if sys.version_info >= (3, 0, 0):
    basestring = str

if sys.version_info >= (3, 2):
    UTC: datetime.timezone = ...

    def FixedOffset(
        offset_hours: float, offset_minutes: float, name: str
    ) -> datetime.timezone:
        ...


else:
    ZERO: datetime.timedelta = ...

    class Utc(datetime.tzinfo):
        ...

    UTC: Utc = ...

    class FixedOffset(datetime.tzinfo):
        def __init__(
            self, offset_hours: float, offset_minutes: float, name: str
        ) -> None:
            ...


ISO8601_REGEX: Pattern[basestring] = ...


class ParseError(ValueError):

    ...


_T = TypeVar("_T")


def to_int(
    d: Mapping[_T, Any],
    key: _T,
    default_to_zero: bool = ...,
    default: Any = ...,
    required: bool = ...,
) -> int:
    ...


def parse_timezone(
    matches: Mapping[basestring, basestring],
    default_timezone: Optional[datetime.tzinfo] = ...,
) -> datetime.tzinfo:
    ...


def parse_date(
    datestring: basestring, default_timezone: Optional[datetime.tzinfo] = ...
) -> datetime.datetime:
    ...
