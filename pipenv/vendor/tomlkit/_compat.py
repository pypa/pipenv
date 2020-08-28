import re
import sys


try:
    from datetime import timezone
except ImportError:
    from datetime import datetime
    from datetime import timedelta
    from datetime import tzinfo

    class timezone(tzinfo):
        __slots__ = "_offset", "_name"

        # Sentinel value to disallow None
        _Omitted = object()

        def __new__(cls, offset, name=_Omitted):
            if not isinstance(offset, timedelta):
                raise TypeError("offset must be a timedelta")
            if name is cls._Omitted:
                if not offset:
                    return cls.utc
                name = None
            elif not isinstance(name, str):
                raise TypeError("name must be a string")
            if not cls._minoffset <= offset <= cls._maxoffset:
                raise ValueError(
                    "offset must be a timedelta "
                    "strictly between -timedelta(hours=24) and "
                    "timedelta(hours=24)."
                )
            return cls._create(offset, name)

        @classmethod
        def _create(cls, offset, name=None):
            self = tzinfo.__new__(cls)
            self._offset = offset
            self._name = name
            return self

        def __getinitargs__(self):
            """pickle support"""
            if self._name is None:
                return (self._offset,)
            return (self._offset, self._name)

        def __eq__(self, other):
            if type(other) != timezone:
                return False
            return self._offset == other._offset

        def __hash__(self):
            return hash(self._offset)

        def __repr__(self):
            """Convert to formal string, for repr().

            >>> tz = timezone.utc
            >>> repr(tz)
            'datetime.timezone.utc'
            >>> tz = timezone(timedelta(hours=-5), 'EST')
            >>> repr(tz)
            "datetime.timezone(datetime.timedelta(-1, 68400), 'EST')"
            """
            if self is self.utc:
                return "datetime.timezone.utc"
            if self._name is None:
                return "%s.%s(%r)" % (
                    self.__class__.__module__,
                    self.__class__.__name__,
                    self._offset,
                )
            return "%s.%s(%r, %r)" % (
                self.__class__.__module__,
                self.__class__.__name__,
                self._offset,
                self._name,
            )

        def __str__(self):
            return self.tzname(None)

        def utcoffset(self, dt):
            if isinstance(dt, datetime) or dt is None:
                return self._offset
            raise TypeError(
                "utcoffset() argument must be a datetime instance" " or None"
            )

        def tzname(self, dt):
            if isinstance(dt, datetime) or dt is None:
                if self._name is None:
                    return self._name_from_offset(self._offset)
                return self._name
            raise TypeError("tzname() argument must be a datetime instance" " or None")

        def dst(self, dt):
            if isinstance(dt, datetime) or dt is None:
                return None
            raise TypeError("dst() argument must be a datetime instance" " or None")

        def fromutc(self, dt):
            if isinstance(dt, datetime):
                if dt.tzinfo is not self:
                    raise ValueError("fromutc: dt.tzinfo " "is not self")
                return dt + self._offset
            raise TypeError("fromutc() argument must be a datetime instance" " or None")

        _maxoffset = timedelta(hours=23, minutes=59)
        _minoffset = -_maxoffset

        @staticmethod
        def _name_from_offset(delta):
            if not delta:
                return "UTC"
            if delta < timedelta(0):
                sign = "-"
                delta = -delta
            else:
                sign = "+"
            hours, rest = divmod(delta, timedelta(hours=1))
            minutes, rest = divmod(rest, timedelta(minutes=1))
            seconds = rest.seconds
            microseconds = rest.microseconds
            if microseconds:
                return ("UTC{}{:02d}:{:02d}:{:02d}.{:06d}").format(
                    sign, hours, minutes, seconds, microseconds
                )
            if seconds:
                return "UTC{}{:02d}:{:02d}:{:02d}".format(sign, hours, minutes, seconds)
            return "UTC{}{:02d}:{:02d}".format(sign, hours, minutes)

    timezone.utc = timezone._create(timedelta(0))
    timezone.min = timezone._create(timezone._minoffset)
    timezone.max = timezone._create(timezone._maxoffset)


PY2 = sys.version_info[0] == 2
PY36 = sys.version_info >= (3, 6)
PY38 = sys.version_info >= (3, 8)

if PY2:
    unicode = unicode
    chr = unichr
    long = long
else:
    unicode = str
    chr = chr
    long = int


if PY36:
    OrderedDict = dict
else:
    from collections import OrderedDict


def decode(string, encodings=None):
    if not PY2 and not isinstance(string, bytes):
        return string

    if PY2 and isinstance(string, unicode):
        return string

    encodings = encodings or ["utf-8", "latin1", "ascii"]

    for encoding in encodings:
        try:
            return string.decode(encoding)
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return string.decode(encodings[0], errors="ignore")
