from __future__ import annotations

import re

from collections.abc import Collection
from collections.abc import Mapping
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import timezone
from typing import Any

from pipenv.vendor.tomlkit._compat import decode


RFC_3339_LOOSE = re.compile(
    "^"
    r"(?P<date>(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}))?"  # Date
    "("
    "(?P<sep>[Tt ])?"  # Separator
    r"(?P<time>(?P<hour>\d{2}):(?P<minute>\d{2})(:(?P<second>\d{2})(\.(?P<fraction>[0-9]+))?)?)"  # Time
    r"(?P<tz>([Zz])|([\+\-]([01][0-9]|2[0-3]):([0-5][0-9])))?"  # Timezone
    ")?"
    "$"
)

RFC_3339_DATETIME = re.compile(
    "^"
    r"(?P<year>\d{4})-(?P<month>0[1-9]|1[012])-(?P<day>0[1-9]|[12][0-9]|3[01])"  # Date
    "[Tt ]"  # Separator
    r"(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9])"  # Time
    r"(:(?P<second>[0-5][0-9]|60)(\.(?P<fraction>[0-9]+))?)?"
    r"(?P<tz>([Zz])|([\+\-]([01][0-9]|2[0-3]):([0-5][0-9])))?"  # Timezone
    "$"
)

RFC_3339_DATE = re.compile("^([0-9]+)-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01])$")

RFC_3339_TIME = re.compile(
    r"^(?P<hour>[01][0-9]|2[0-3]):(?P<minute>[0-5][0-9])"
    r"(:(?P<second>[0-5][0-9]|60)(\.(?P<fraction>[0-9]+))?)?$"
)

_utc = timezone(timedelta(), "UTC")


def parse_rfc3339(string: str) -> datetime | date | time:
    m = RFC_3339_DATETIME.match(string)
    if m:
        year = int(m.group("year"))
        month = int(m.group("month"))
        day = int(m.group("day"))
        hour = int(m.group("hour"))
        minute = int(m.group("minute"))
        second = int(m.group("second") or 0)
        microsecond = 0

        if m.group("fraction"):
            microsecond = int((f"{m.group('fraction'):<06s}")[:6])

        if m.group("tz"):
            # Timezone
            tz = m.group("tz")
            if tz.upper() == "Z":
                tzinfo = _utc
            else:
                sign = tz[0]
                hour_offset, minute_offset = map(int, tz[1:].split(":"))
                offset = timedelta(seconds=hour_offset * 3600 + minute_offset * 60)
                if sign == "-":
                    offset = -offset

                tzinfo = timezone(offset, tz)

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
        hour = int(m.group("hour"))
        minute = int(m.group("minute"))
        second = int(m.group("second") or 0)
        microsecond = 0

        if m.group("fraction"):
            microsecond = int((f"{m.group('fraction'):<06s}")[:6])

        return time(hour, minute, second, microsecond)

    raise ValueError("Invalid RFC 3339 string")


# https://toml.io/en/v1.0.0#string
CONTROL_CHARS = frozenset(chr(c) for c in range(0x20)) | {chr(0x7F)}
_escaped = {
    "b": "\b",
    "t": "\t",
    "n": "\n",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    '"': '"',
    "\\": "\\",
}
_compact_escapes = {
    **{v: f"\\{k}" for k, v in _escaped.items()},
    '"""': '""\\"',
}
_basic_escapes = CONTROL_CHARS | {'"', "\\"}


def _unicode_escape(seq: str) -> str:
    return "".join(f"\\u{ord(c):04x}" for c in seq)


def escape_string(s: str, escape_sequences: Collection[str] = _basic_escapes) -> str:
    s = decode(s)

    res = []
    start = 0

    def flush(inc: int = 1) -> int:
        if start != i:
            res.append(s[start:i])

        return i + inc

    found_sequences = {seq for seq in escape_sequences if seq in s}

    i = 0
    while i < len(s):
        for seq in found_sequences:
            seq_len = len(seq)
            if s[i:].startswith(seq):
                start = flush(seq_len)
                res.append(_compact_escapes.get(seq) or _unicode_escape(seq))
                i += seq_len - 1  # fast-forward escape sequence
        i += 1

    flush()

    return "".join(res)


def merge_dicts(d1: dict[str, Any], d2: dict[str, Any]) -> None:
    for k, v in d2.items():
        if k in d1 and isinstance(d1[k], dict) and isinstance(v, Mapping):
            merge_dicts(d1[k], dict(v))
        else:
            d1[k] = d2[k]
