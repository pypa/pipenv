# Copyright 2012 (C) Daniel Richman, Adam Greig
#
# This file is part of strict_rfc3339.
#
# strict_rfc3339 is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# strict_rfc3339 is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with strict_rfc3339.  If not, see <http://www.gnu.org/licenses/>.

"""
Super simple lightweight RFC3339 functions
"""

import re
import time
import calendar

__all__ = ["validate_rfc3339",
           "InvalidRFC3339Error",
           "rfc3339_to_timestamp",
           "timestamp_to_rfc3339_utcoffset",
           "timestamp_to_rfc3339_localoffset",
           "now_to_rfc3339_utcoffset",
           "now_to_rfc3339_localoffset"]

rfc3339_regex = re.compile(
    r"^(\d\d\d\d)\-(\d\d)\-(\d\d)T"
    r"(\d\d):(\d\d):(\d\d)(\.\d+)?(Z|([+\-])(\d\d):(\d\d))$")


def validate_rfc3339(datestring):
    """Check an RFC3339 string is valid via a regex and some range checks"""

    m = rfc3339_regex.match(datestring)
    if m is None:
        return False

    groups = m.groups()

    year, month, day, hour, minute, second = [int(i) for i in groups[:6]]

    if not 1 <= year <= 9999:
        # Have to reject this, unfortunately (despite it being OK by rfc3339):
        # calendar.timegm/calendar.monthrange can't cope (since datetime can't)
        return False

    if not 1 <= month <= 12:
        return False

    (_, max_day) = calendar.monthrange(year, month)
    if not 1 <= day <= max_day:
        return False

    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        # forbid leap seconds :-(. See README
        return False

    if groups[7] != "Z":
        (offset_sign, offset_hours, offset_mins) = groups[8:]
        if not (0 <= int(offset_hours) <= 23 and 0 <= int(offset_mins) <= 59):
            return False

    # all OK
    return True


class InvalidRFC3339Error(ValueError):
    """Subclass of ValueError thrown by rfc3339_to_timestamp"""
    pass


def rfc3339_to_timestamp(datestring):
    """Convert an RFC3339 date-time string to a UTC UNIX timestamp"""

    if not validate_rfc3339(datestring):
        raise InvalidRFC3339Error

    groups = rfc3339_regex.match(datestring).groups()

    time_tuple = [int(p) for p in groups[:6]]
    timestamp = calendar.timegm(time_tuple)

    seconds_part = groups[6]
    if seconds_part is not None:
        timestamp += float("0" + seconds_part)

    if groups[7] != "Z":
        (offset_sign, offset_hours, offset_mins) = groups[8:]
        offset_seconds = int(offset_hours) * 3600 + int(offset_mins) * 60
        if offset_sign == '-':
            offset_seconds = -offset_seconds
        timestamp -= offset_seconds

    return timestamp


def _seconds_and_microseconds(timestamp):
    """
    Split a floating point timestamp into an integer number of seconds since
    the epoch, and an integer number of microseconds (having rounded to the
    nearest microsecond).

    If `_seconds_and_microseconds(x) = (y, z)` then the following holds (up to
    the error introduced by floating point operations):

    * `x = y + z / 1_000_000.`
    * `0 <= z < 1_000_000.`
    """

    if isinstance(timestamp, int):
        return (timestamp, 0)
    else:
        timestamp_us = int(round(timestamp * 1e6))
        return divmod(timestamp_us, 1000000)

def _make_datestring_start(time_tuple, microseconds):
    ds_format = "{0:04d}-{1:02d}-{2:02d}T{3:02d}:{4:02d}:{5:02d}"
    datestring = ds_format.format(*time_tuple)

    seconds_part_str = "{0:06d}".format(microseconds)
    # There used to be a bug here where it could be 1000000
    assert len(seconds_part_str) == 6 and seconds_part_str[0] != '-'
    seconds_part_str = seconds_part_str.rstrip("0")
    if seconds_part_str != "":
        datestring += "." + seconds_part_str

    return datestring


def timestamp_to_rfc3339_utcoffset(timestamp):
    """Convert a UTC UNIX timestamp to RFC3339, with the offset as 'Z'"""

    seconds, microseconds = _seconds_and_microseconds(timestamp)

    time_tuple = time.gmtime(seconds)
    datestring = _make_datestring_start(time_tuple, microseconds)
    datestring += "Z"

    assert abs(rfc3339_to_timestamp(datestring) - timestamp) < 0.000001
    return datestring


def timestamp_to_rfc3339_localoffset(timestamp):
    """
    Convert a UTC UNIX timestamp to RFC3339, using the local offset.

    localtime() provides the time parts. The difference between gmtime and
    localtime tells us the offset.
    """

    seconds, microseconds = _seconds_and_microseconds(timestamp)

    time_tuple = time.localtime(seconds)
    datestring = _make_datestring_start(time_tuple, microseconds)

    gm_time_tuple = time.gmtime(seconds)
    offset = calendar.timegm(time_tuple) - calendar.timegm(gm_time_tuple)

    if abs(offset) % 60 != 0:
        raise ValueError("Your local offset is not a whole minute")

    offset_minutes = abs(offset) // 60
    offset_hours = offset_minutes // 60
    offset_minutes %= 60

    offset_string = "{0:02d}:{1:02d}".format(offset_hours, offset_minutes)

    if offset < 0:
        datestring += "-"
    else:
        datestring += "+"

    datestring += offset_string
    assert abs(rfc3339_to_timestamp(datestring) - timestamp) < 0.000001

    return datestring


def now_to_rfc3339_utcoffset(integer=True):
    """Convert the current time to RFC3339, with the offset as 'Z'"""

    timestamp = time.time()
    if integer:
        timestamp = int(timestamp)
    return timestamp_to_rfc3339_utcoffset(timestamp)


def now_to_rfc3339_localoffset(integer=True):
    """Convert the current time to RFC3339, using the local offset."""

    timestamp = time.time()
    if integer:
        timestamp = int(timestamp)
    return timestamp_to_rfc3339_localoffset(timestamp)
