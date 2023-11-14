# coding: utf-8

import datetime
import copy

# ToDo: at least on PY3 you could probably attach the tzinfo correctly to the object
#       a more complete datetime might be used by safe loading as well
#
#       add type information (iso8601, spaced)

from typing import Any, Dict, Optional, List  # NOQA


class TimeStamp(datetime.datetime):
    def __init__(self, *args: Any, **kw: Any) -> None:
        self._yaml: Dict[Any, Any] = dict(t=False, tz=None, delta=0)

    def __new__(cls, *args: Any, **kw: Any) -> Any:  # datetime is immutable
        return datetime.datetime.__new__(cls, *args, **kw)

    def __deepcopy__(self, memo: Any) -> Any:
        ts = TimeStamp(self.year, self.month, self.day, self.hour, self.minute, self.second)
        ts._yaml = copy.deepcopy(self._yaml)
        return ts

    def replace(
        self,
        year: Any = None,
        month: Any = None,
        day: Any = None,
        hour: Any = None,
        minute: Any = None,
        second: Any = None,
        microsecond: Any = None,
        tzinfo: Any = True,
        fold: Any = None,
    ) -> Any:
        if year is None:
            year = self.year
        if month is None:
            month = self.month
        if day is None:
            day = self.day
        if hour is None:
            hour = self.hour
        if minute is None:
            minute = self.minute
        if second is None:
            second = self.second
        if microsecond is None:
            microsecond = self.microsecond
        if tzinfo is True:
            tzinfo = self.tzinfo
        if fold is None:
            fold = self.fold
        ts = type(self)(year, month, day, hour, minute, second, microsecond, tzinfo, fold=fold)
        ts._yaml = copy.deepcopy(self._yaml)
        return ts
