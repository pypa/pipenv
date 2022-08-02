import re

from collections.abc import Mapping
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from typing import Union

from ._compat import decode


RFC_3339_LOOSE = re.compile(
    "^"
    r"(([0-9]+)-(\d{2})-(\d{2}))?"  # Date
    "("
    "([Tt ])?"  # Separator
    r"(\d{2}):(\d{2}):(\d{2})(\.([0-9]+))?"  # Time
    r"(([Zz])|([\+|\-]([01][0-9]|2[0-3]):([0-5][0-9])))?"  # Timezone
    ")?"
    "$"
)

RFC_3339_DATETIME = re.compile(
    "^"
    "([0-9]+)-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])"  # Date
    "[Tt ]"  # Separator
    r"([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9]|60)(\.([0-9]+))?"  # Time
    r"(([Zz])|([\+|\-]([01][0-9]|2[0-3]):([0-5][0-9])))?"  # Timezone
    "$"
)

RFC_3339_DATE = re.compile("^([0-9]+)-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])$")

RFC_3339_TIME = re.compile(
    r"^([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9]|60)(\.([0-9]+))?$"
)

_utc = timezone(timedelta(), "UTC")


def parse_rfc3339(string: str) -> Union[datetime, date, time]:
    m = RFC_3339_DATETIME.match(string)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        second = int(m.group(6))
        microsecond = 0

        if m.group(7):
            microsecond = int((f"{m.group(8):<06s}")[:6])

        if m.group(9):
            # Timezone
            tz = m.group(9)
            if tz.upper() == "Z":
                tzinfo = _utc
            else:
                sign = m.group(11)[0]
                hour_offset, minute_offset = int(m.group(12)), int(m.group(13))
                offset = timedelta(seconds=hour_offset * 3600 + minute_offset * 60)
                if sign == "-":
                    offset = -offset

                tzinfo = timezone(offset, f"{sign}{m.group(12)}:{m.group(13)}")

            return datetime(
                year, month, day, hour, minute, second, microsecond, tzinfo=tzinfo
            )
        else:
            return datetime(year, month, day, hour, minute, second, microsecond)

    m = RFC_3339_DATE.match(string)
    if m:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))

        return date(year, month, day)

    m = RFC_3339_TIME.match(string)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2))
        second = int(m.group(3))
        microsecond = 0

        if m.group(4):
            microsecond = int((f"{m.group(5):<06s}")[:6])

        return time(hour, minute, second, microsecond)

    raise ValueError("Invalid RFC 339 string")


_escaped = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"', "\\": "\\"}
_escapes = {v: k for k, v in _escaped.items()}


def escape_string(s: str) -> str:
    s = decode(s)

    res = []
    start = 0

    def flush():
        if start != i:
            res.append(s[start:i])

        return i + 1

    i = 0
    while i < len(s):
        c = s[i]
        if c in '"\\\n\r\t\b\f':
            start = flush()
            res.append("\\" + _escapes[c])
        elif ord(c) < 0x20:
            start = flush()
            res.append("\\u%04x" % ord(c))
        i += 1

    flush()

    return "".join(res)


def merge_dicts(d1: dict, d2: dict) -> dict:
    for k, v in d2.items():
        if k in d1 and isinstance(d1[k], dict) and isinstance(v, Mapping):
            merge_dicts(d1[k], v)
        else:
            d1[k] = d2[k]
