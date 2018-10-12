from __future__ import unicode_literals

import re
import string

from datetime import date
from datetime import datetime
from datetime import time
import sys
if sys.version_info >= (3, 4):
    from enum import Enum
else:
    from pipenv.vendor.backports.enum import Enum

from ._compat import PY2
from ._compat import decode
from ._compat import unicode
from ._utils import escape_string


def item(value, _parent=None):
    from .container import Container

    if isinstance(value, Item):
        return value

    if isinstance(value, bool):
        return Bool(value, Trivia())
    elif isinstance(value, int):
        return Integer(value, Trivia(), str(value))
    elif isinstance(value, float):
        return Float(value, Trivia(), str(value))
    elif isinstance(value, dict):
        val = Table(Container(), Trivia(), False)
        for k, v in sorted(value.items(), key=lambda i: (isinstance(i[1], dict), i[0])):
            val[k] = item(v, _parent=val)

        return val
    elif isinstance(value, list):
        if value and isinstance(value[0], dict):
            a = AoT([])
        else:
            a = Array([], Trivia())

        for v in value:
            if isinstance(v, dict):
                table = Table(Container(), Trivia(), True)

                for k, _v in sorted(
                    v.items(), key=lambda i: (isinstance(i[1], dict), i[0])
                ):
                    i = item(_v)
                    if isinstance(table, InlineTable):
                        i.trivia.trail = ""

                    table[k] = item(i)

                v = table

            a.append(v)

        return a
    elif isinstance(value, (str, unicode)):
        escaped = escape_string(value)

        return String(StringType.SLB, value, escaped, Trivia())
    elif isinstance(value, datetime):
        return DateTime(value, Trivia(), value.isoformat().replace("+00:00", "Z"))
    elif isinstance(value, date):
        return Date(value, Trivia(), value.isoformat())
    elif isinstance(value, time):
        return Time(value, Trivia(), value.isoformat())

    raise ValueError("Invalid type {}".format(type(value)))


class StringType(Enum):

    SLB = '"'
    MLB = '"""'
    SLL = "'"
    MLL = "'''"

    def is_literal(self):  # type: () -> bool
        return self in {StringType.SLL, StringType.MLL}

    def is_multiline(self):  # type: () -> bool
        return self in {StringType.MLB, StringType.MLL}


class Trivia:
    """
    Trivia information (aka metadata).
    """

    def __init__(
        self, indent=None, comment_ws=None, comment=None, trail=None
    ):  # type: (str, str, str, str) -> None
        # Whitespace before a value.
        self.indent = indent or ""
        # Whitespace after a value, but before a comment.
        self.comment_ws = comment_ws or ""
        # Comment, starting with # character, or empty string if no comment.
        self.comment = comment or ""
        # Trailing newline.
        if trail is None:
            trail = "\n"

        self.trail = trail


class KeyType(Enum):
    """
    The type of a Key.

    Keys can be bare (unquoted), or quoted using basic ("), or literal (')
    quotes following the same escaping rules as single-line StringType.
    """

    Bare = ""
    Basic = '"'
    Literal = "'"


class Key:
    """
    A key value.
    """

    def __init__(self, k, t=None, sep=None, dotted=False):  # type: (str) -> None
        if t is None:
            if any(
                [c not in string.ascii_letters + string.digits + "-" + "_" for c in k]
            ):
                t = KeyType.Basic
            else:
                t = KeyType.Bare

        self.t = t
        if sep is None:
            sep = " = "

        self.sep = sep
        self.key = k
        self._dotted = dotted

    @property
    def delimiter(self):  # type: () -> str
        return self.t.value

    def is_dotted(self):  # type: () -> bool
        return self._dotted

    def as_string(self):  # type: () -> str
        return "{}{}{}".format(self.delimiter, self.key, self.delimiter)

    def __hash__(self):  # type: () -> int
        return hash(self.key)

    def __eq__(self, other):  # type: (Key) -> bool
        return self.key == other.key

    def __str__(self):  # type: () -> str
        return self.as_string()

    def __repr__(self):  # type: () -> str
        return "<Key {}>".format(self.as_string())


class Item(object):
    """
    An item within a TOML document.
    """

    def __init__(self, trivia):  # type: (Trivia) -> None
        self._trivia = trivia

    @property
    def trivia(self):  # type: () -> Trivia
        return self._trivia

    @property
    def discriminant(self):  # type: () -> int
        raise NotImplementedError()

    def as_string(self):  # type: () -> str
        raise NotImplementedError()

    # Helpers

    def comment(self, comment):  # type: (str) -> Item
        if not comment.strip().startswith("#"):
            comment = "# " + comment

        self._trivia.comment_ws = " "
        self._trivia.comment = comment

        return self

    def indent(self, indent):  # type: (int) -> Item
        if self._trivia.indent.startswith("\n"):
            self._trivia.indent = "\n" + " " * indent
        else:
            self._trivia.indent = " " * indent

        return self


class Whitespace(Item):
    """
    A whitespace literal.
    """

    def __init__(self, s, fixed=False):  # type: (str, bool) -> None
        self._s = s
        self._fixed = fixed

    @property
    def s(self):  # type: () -> str
        return self._s

    @property
    def value(self):  # type: () -> str
        return self._s

    @property
    def trivia(self):  # type: () -> Trivia
        raise RuntimeError("Called trivia on a Whitespace variant.")

    @property
    def discriminant(self):  # type: () -> int
        return 0

    def is_fixed(self):  # type: () -> bool
        return self._fixed

    def as_string(self):  # type: () -> str
        return self._s

    def __repr__(self):  # type: () -> str
        return "<{} {}>".format(self.__class__.__name__, repr(self._s))


class Comment(Item):
    """
    A comment literal.
    """

    @property
    def discriminant(self):  # type: () -> int
        return 1

    def as_string(self):  # type: () -> str
        return "{}{}{}".format(
            self._trivia.indent, decode(self._trivia.comment), self._trivia.trail
        )

    def __str__(self):  # type: () -> str
        return "{}{}".format(self._trivia.indent, decode(self._trivia.comment))


class Integer(int, Item):
    """
    An integer literal.
    """

    def __new__(cls, value, trivia, raw):  # type: (int, Trivia, str) -> Integer
        return super(Integer, cls).__new__(cls, value)

    def __init__(self, _, trivia, raw):  # type: (int, Trivia, str) -> None
        super(Integer, self).__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match("^[+\-]\d+$", raw):
            self._sign = True

    @property
    def discriminant(self):  # type: () -> int
        return 2

    @property
    def value(self):  # type: () -> int
        return self

    def as_string(self):  # type: () -> str
        return self._raw

    def __add__(self, other):
        result = super(Integer, self).__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super(Integer, self).__radd__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super(Integer, self).__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super(Integer, self).__rsub__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Integer(result, self._trivia, raw)


class Float(float, Item):
    """
    A float literal.
    """

    def __new__(cls, value, trivia, raw):  # type: (float, Trivia, str) -> Integer
        return super(Float, cls).__new__(cls, value)

    def __init__(self, _, trivia, raw):  # type: (float, Trivia, str) -> None
        super(Float, self).__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match("^[+\-].+$", raw):
            self._sign = True

    @property
    def discriminant(self):  # type: () -> int
        return 3

    @property
    def value(self):  # type: () -> float
        return self

    def as_string(self):  # type: () -> str
        return self._raw

    def __add__(self, other):
        result = super(Float, self).__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super(Float, self).__radd__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super(Float, self).__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super(Float, self).__rsub__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Float(result, self._trivia, raw)


class Bool(Item):
    """
    A boolean literal.
    """

    def __init__(self, value, trivia):  # type: (float, Trivia) -> None
        super(Bool, self).__init__(trivia)

        self._value = value

    @property
    def discriminant(self):  # type: () -> int
        return 4

    @property
    def value(self):  # type: () -> bool
        return self._value

    def as_string(self):  # type: () -> str
        return str(self._value).lower()


class DateTime(datetime, Item):
    """
    A datetime literal.
    """

    def __new__(cls, value, *_):  # type: (datetime, ...) -> datetime
        return datetime.__new__(
            cls,
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=value.tzinfo,
        )

    def __init__(self, _, trivia, raw):  # type: (datetime, Trivia, str) -> None
        super(DateTime, self).__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self):  # type: () -> int
        return 5

    @property
    def value(self):  # type: () -> datetime
        return self

    def as_string(self):  # type: () -> str
        return self._raw

    def __add__(self, other):
        result = super(DateTime, self).__add__(other)

        return self._new(result)

    def __sub__(self, other):
        result = super(DateTime, self).__sub__(other)

        return self._new(result)

    def _new(self, result):
        raw = result.isoformat()

        return DateTime(result, self._trivia, raw)


class Date(date, Item):
    """
    A date literal.
    """

    def __new__(cls, value, *_):  # type: (date, ...) -> date
        return date.__new__(cls, value.year, value.month, value.day)

    def __init__(self, _, trivia, raw):  # type: (date, Trivia, str) -> None
        super(Date, self).__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self):  # type: () -> int
        return 6

    @property
    def value(self):  # type: () -> date
        return self

    def as_string(self):  # type: () -> str
        return self._raw

    def __add__(self, other):
        result = super(Date, self).__add__(other)

        return self._new(result)

    def __sub__(self, other):
        result = super(Date, self).__sub__(other)

        return self._new(result)

    def _new(self, result):
        raw = result.isoformat()

        return Date(result, self._trivia, raw)


class Time(time, Item):
    """
    A time literal.
    """

    def __new__(cls, value, *_):  # type: (time, ...) -> time
        return time.__new__(
            cls, value.hour, value.minute, value.second, value.microsecond
        )

    def __init__(self, _, trivia, raw):  # type: (time, Trivia, str) -> None
        super(Time, self).__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self):  # type: () -> int
        return 7

    @property
    def value(self):  # type: () -> time
        return self

    def as_string(self):  # type: () -> str
        return self._raw


class Array(Item, list):
    """
    An array literal
    """

    def __init__(self, value, trivia):  # type: (list, Trivia) -> None
        super(Array, self).__init__(trivia)

        list.__init__(
            self, [v.value for v in value if not isinstance(v, (Whitespace, Comment))]
        )

        self._value = value

    @property
    def discriminant(self):  # type: () -> int
        return 8

    @property
    def value(self):  # type: () -> list
        return self

    def is_homogeneous(self):  # type: () -> bool
        if not self:
            return True

        discriminants = [
            i.discriminant
            for i in self._value
            if not isinstance(i, (Whitespace, Comment))
        ]

        return len(set(discriminants)) == 1

    def as_string(self):  # type: () -> str
        return "[{}]".format("".join(v.as_string() for v in self._value))

    def append(self, _item):  # type: () -> None
        if self._value:
            self._value.append(Whitespace(", "))

        it = item(_item)
        super(Array, self).append(it.value)

        self._value.append(it)

        if not self.is_homogeneous():
            raise ValueError("Array has mixed types elements")

    if not PY2:

        def clear(self):
            super(Array, self).clear()

            self._value.clear()

    def __iadd__(self, other):  # type: (list) -> Array
        if not isinstance(other, list):
            return NotImplemented

        for v in other:
            self.append(v)

        return self

    def __delitem__(self, key):
        super(Array, self).__delitem__(key)

        j = 0 if key >= 0 else -1
        for i, v in enumerate(self._value if key >= 0 else reversed(self._value)):
            if key < 0:
                i = -i - 1

            if isinstance(v, (Comment, Whitespace)):
                continue

            if j == key:
                del self._value[i]

                if i < 0 and abs(i) > len(self._value):
                    i += 1

                if i < len(self._value) - 1 and isinstance(self._value[i], Whitespace):
                    del self._value[i]

                break

            j += 1 if key >= 0 else -1

    def __str__(self):
        return str(
            [v.value for v in self._value if not isinstance(v, (Whitespace, Comment))]
        )

    def __repr__(self):
        return str(self)


class Table(Item, dict):
    """
    A table literal.
    """

    def __init__(
        self,
        value,
        trivia,
        is_aot_element,
        is_super_table=False,
        name=None,
        display_name=None,
    ):  # type: (tomlkit.container.Container, Trivia, bool) -> None
        super(Table, self).__init__(trivia)

        self.name = name
        self.display_name = display_name
        self._value = value
        self._is_aot_element = is_aot_element
        self._is_super_table = is_super_table

        for k, v in self._value.body:
            if k is not None:
                super(Table, self).__setitem__(k.key, v)

    @property
    def value(self):  # type: () -> tomlkit.container.Container
        return self._value

    @property
    def discriminant(self):  # type: () -> int
        return 9

    @property
    def value(self):  # type: () -> tomlkit.container.Container
        return self._value

    def add(self, key, item=None):  # type: (Union[Key, Item, str], Any) -> Item
        if item is None:
            if not isinstance(key, (Comment, Whitespace)):
                raise ValueError(
                    "Non comment/whitespace items must have an associated key"
                )

            key, item = None, key

        return self.append(key, item)

    def append(self, key, _item):  # type: (Union[Key, str], Any) -> Table
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            super(Table, self).__setitem__(key, _item)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return self

        indent = m.group(1)

        if not isinstance(_item, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", _item.trivia.indent)
            if not m:
                _item.trivia.indent = indent
            else:
                _item.trivia.indent = m.group(1) + indent + m.group(2)

        return self

    def remove(self, key):  # type: (Union[Key, str]) -> Table
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            super(Table, self).__delitem__(key)

        return self

    def is_aot_element(self):  # type: () -> bool
        return self._is_aot_element

    def is_super_table(self):  # type: () -> bool
        return self._is_super_table

    def as_string(self, prefix=None):  # type: () -> str
        return self._value.as_string(prefix=prefix)

    # Helpers

    def indent(self, indent):  # type: (int) -> Table
        super(Table, self).indent(indent)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            indent = ""
        else:
            indent = m.group(1)

        for k, item in self._value.body:
            if not isinstance(item, Whitespace):
                item.trivia.indent = indent + item.trivia.indent

        return self

    def keys(self):  # type: () -> Generator[str]
        for k in self._value.keys():
            yield k

    def values(self):  # type: () -> Generator[Item]
        for v in self._value.values():
            yield v

    def items(self):  # type: () -> Generator[Item]
        for k, v in self._value.items():
            yield k, v

    def update(self, other):  # type: (Dict) -> None
        for k, v in other.items():
            self[k] = v

    def __contains__(self, key):  # type: (Union[Key, str]) -> bool
        return key in self._value

    def __getitem__(self, key):  # type: (Union[Key, str]) -> Item
        return self._value[key]

    def __setitem__(self, key, value):  # type: (Union[Key, str], Any) -> None
        if not isinstance(value, Item):
            value = item(value)

        self._value[key] = value

        if key is not None:
            super(Table, self).__setitem__(key, value)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return

        indent = m.group(1)

        if not isinstance(value, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)

    def __delitem__(self, key):  # type: (Union[Key, str]) -> None
        self.remove(key)

    def __repr__(self):
        return super(Table, self).__repr__()


class InlineTable(Item, dict):
    """
    An inline table literal.
    """

    def __init__(
        self, value, trivia
    ):  # type: (tomlkit.container.Container, Trivia) -> None
        super(InlineTable, self).__init__(trivia)

        self._value = value

        for k, v in self._value.body:
            if k is not None:
                super(InlineTable, self).__setitem__(k.key, v)

    @property
    def discriminant(self):  # type: () -> int
        return 10

    @property
    def value(self):  # type: () -> Dict
        return self._value

    def append(self, key, _item):  # type: (Union[Key, str], Any) -> InlineTable
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        if not isinstance(_item, (Whitespace, Comment)):
            if not _item.trivia.indent and len(self._value) > 0:
                _item.trivia.indent = " "

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            super(InlineTable, self).__setitem__(key, _item)

        return self

    def remove(self, key):  # type: (Union[Key, str]) -> InlineTable
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            super(InlineTable, self).__delitem__(key)

        return self

    def as_string(self):  # type: () -> str
        buf = "{"
        for i, (k, v) in enumerate(self._value.body):
            if k is None:
                if i == len(self._value.body) - 1:
                    buf = buf.rstrip(",")

                buf += v.as_string()

                continue

            buf += "{}{}{}{}{}{}".format(
                v.trivia.indent,
                k.as_string(),
                k.sep,
                v.as_string(),
                v.trivia.comment,
                v.trivia.trail.replace("\n", ""),
            )

            if i != len(self._value.body) - 1:
                buf += ","

        buf += "}"

        return buf

    def keys(self):  # type: () -> Generator[str]
        for k in self._value.keys():
            yield k

    def values(self):  # type: () -> Generator[Item]
        for v in self._value.values():
            yield v

    def items(self):  # type: () -> Generator[Item]
        for k, v in self._value.items():
            yield k, v

    def update(self, other):  # type: (Dict) -> None
        for k, v in other.items():
            self[k] = v

    def __contains__(self, key):  # type: (Union[Key, str]) -> bool
        return key in self._value

    def __getitem__(self, key):  # type: (Union[Key, str]) -> Item
        return self._value[key]

    def __setitem__(self, key, value):  # type: (Union[Key, str], Any) -> None
        if not isinstance(value, Item):
            value = item(value)

        self._value[key] = value

        if key is not None:
            super(InlineTable, self).__setitem__(key, value)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            return

        indent = m.group(1)

        if not isinstance(value, Whitespace):
            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)

    def __delitem__(self, key):  # type: (Union[Key, str]) -> None
        self.remove(key)

    def __repr__(self):
        return super(InlineTable, self).__repr__()


class String(unicode, Item):
    """
    A string literal.
    """

    def __new__(cls, t, value, original, trivia):
        return super(String, cls).__new__(cls, value)

    def __init__(
        self, t, _, original, trivia
    ):  # type: (StringType, str, original, Trivia) -> None
        super(String, self).__init__(trivia)

        self._t = t
        self._original = original

    @property
    def discriminant(self):  # type: () -> int
        return 11

    @property
    def value(self):  # type: () -> str
        return self

    def as_string(self):  # type: () -> str
        return "{}{}{}".format(self._t.value, decode(self._original), self._t.value)

    def __add__(self, other):
        result = super(String, self).__add__(other)

        return self._new(result)

    def __sub__(self, other):
        result = super(String, self).__sub__(other)

        return self._new(result)

    def _new(self, result):
        return String(self._t, result, result, self._trivia)


class AoT(Item, list):
    """
    An array of table literal
    """

    def __init__(
        self, body, name=None, parsed=False
    ):  # type: (List[Table], Optional[str]) -> None
        self.name = None
        self._body = []
        self._parsed = parsed

        super(AoT, self).__init__(Trivia(trail=""))

        for table in body:
            self.append(table)

    @property
    def body(self):  # type: () -> List[Table]
        return self._body

    @property
    def discriminant(self):  # type: () -> int
        return 12

    @property
    def value(self):  # type: () -> List[Dict[Any, Any]]
        return [v.value for v in self._body]

    def append(self, table):  # type: (Table) -> Table
        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if m:
            indent = m.group(1)

            m = re.match("(?s)^([^ ]*)(.*)$", table.trivia.indent)
            if not m:
                table.trivia.indent = indent
            else:
                table.trivia.indent = m.group(1) + indent + m.group(2)

        if not self._parsed and "\n" not in table.trivia.indent and self._body:
            table.trivia.indent = "\n" + table.trivia.indent

        self._body.append(table)

        super(AoT, self).append(table)

        return table

    def as_string(self):  # type: () -> str
        b = ""
        for table in self._body:
            b += table.as_string(prefix=self.name)

        return b

    def __repr__(self):  # type: () -> str
        return "<AoT {}>".format(self.value)


class Null(Item):
    """
    A null item.
    """

    def __init__(self):  # type: () -> None
        pass

    @property
    def discriminant(self):  # type: () -> int
        return -1

    @property
    def value(self):  # type: () -> None
        return None

    def as_string(self):  # type: () -> str
        return ""
