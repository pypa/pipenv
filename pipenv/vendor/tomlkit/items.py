import abc
import copy
import re
import string

from datetime import date
from datetime import datetime
from datetime import time
from datetime import tzinfo
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Iterator
from typing import List
from typing import Optional
from typing import TypeVar
from typing import Union
from typing import cast
from typing import overload

from ._compat import PY38
from ._compat import decode
from ._utils import escape_string
from .toml_char import TOMLChar


if TYPE_CHECKING:  # pragma: no cover
    # Define _CustomList and _CustomDict as a workaround for:
    # https://github.com/python/mypy/issues/11427
    #
    # According to this issue, the typeshed contains a "lie"
    # (it adds MutableSequence to the ancestry of list and MutableMapping to
    # the ancestry of dict) which completely messes with the type inference for
    # Table, InlineTable, Array and Container.
    #
    # Importing from builtins is preferred over simple assignment, see issues:
    # https://github.com/python/mypy/issues/8715
    # https://github.com/python/mypy/issues/10068
    from builtins import dict as _CustomDict
    from builtins import list as _CustomList

    # Allow type annotations but break circular imports
    from . import container
else:
    from collections.abc import MutableMapping
    from collections.abc import MutableSequence

    class _CustomList(MutableSequence, list):
        """Adds MutableSequence mixin while pretending to be a builtin list"""

    class _CustomDict(MutableMapping, dict):
        """Adds MutableMapping mixin while pretending to be a builtin dict"""


def item(
    value: Any, _parent: Optional["Item"] = None, _sort_keys: bool = False
) -> "Item":
    """Create a TOML item from a Python object.

    :Example:

    >>> item(42)
    42
    >>> item([1, 2, 3])
    [1, 2, 3]
    >>> item({'a': 1, 'b': 2})
    a = 1
    b = 2
    """

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
        table_constructor = InlineTable if isinstance(_parent, Array) else Table
        val = table_constructor(Container(), Trivia(), False)
        for k, v in sorted(
            value.items(),
            key=lambda i: (isinstance(i[1], dict), i[0] if _sort_keys else 1),
        ):
            val[k] = item(v, _parent=val, _sort_keys=_sort_keys)
        only_child = len(value) == 1 and val[next(iter(value))]
        if (
            table_constructor is Table
            and only_child
            and isinstance(only_child, (AoT, Table))
        ):
            # The table becomes super table if the only child is a table or AoT.
            val._is_super_table = True

        return val
    elif isinstance(value, (list, tuple)):
        if value and all(isinstance(v, dict) for v in value):
            a = AoT([])
            table_constructor = Table
        else:
            a = Array([], Trivia())
            table_constructor = InlineTable

        for v in value:
            if isinstance(v, dict):
                table = table_constructor(Container(), Trivia(), True)

                for k, _v in sorted(
                    v.items(),
                    key=lambda i: (isinstance(i[1], dict), i[0] if _sort_keys else 1),
                ):
                    i = item(_v, _parent=a, _sort_keys=_sort_keys)
                    if isinstance(table, InlineTable):
                        i.trivia.trail = ""

                    table[k] = i

                v = table

            a.append(v)

        return a
    elif isinstance(value, str):
        escaped = escape_string(value)

        return String(StringType.SLB, decode(value), escaped, Trivia())
    elif isinstance(value, datetime):
        return DateTime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            Trivia(),
            value.isoformat().replace("+00:00", "Z"),
        )
    elif isinstance(value, date):
        return Date(value.year, value.month, value.day, Trivia(), value.isoformat())
    elif isinstance(value, time):
        return Time(
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
            Trivia(),
            value.isoformat(),
        )

    raise ValueError(f"Invalid type {type(value)}")


class StringType(Enum):
    # Single Line Basic
    SLB = '"'
    # Multi Line Basic
    MLB = '"""'
    # Single Line Literal
    SLL = "'"
    # Multi Line Literal
    MLL = "'''"

    @property
    @lru_cache(maxsize=None)
    def unit(self) -> str:
        return self.value[0]

    @lru_cache(maxsize=None)
    def is_basic(self) -> bool:
        return self in {StringType.SLB, StringType.MLB}

    @lru_cache(maxsize=None)
    def is_literal(self) -> bool:
        return self in {StringType.SLL, StringType.MLL}

    @lru_cache(maxsize=None)
    def is_singleline(self) -> bool:
        return self in {StringType.SLB, StringType.SLL}

    @lru_cache(maxsize=None)
    def is_multiline(self) -> bool:
        return self in {StringType.MLB, StringType.MLL}

    @lru_cache(maxsize=None)
    def toggle(self) -> "StringType":
        return {
            StringType.SLB: StringType.MLB,
            StringType.MLB: StringType.SLB,
            StringType.SLL: StringType.MLL,
            StringType.MLL: StringType.SLL,
        }[self]


class BoolType(Enum):
    TRUE = "true"
    FALSE = "false"

    @lru_cache(maxsize=None)
    def __bool__(self):
        return {BoolType.TRUE: True, BoolType.FALSE: False}[self]

    def __iter__(self):
        return iter(self.value)

    def __len__(self):
        return len(self.value)


class Trivia:
    """
    Trivia information (aka metadata).
    """

    def __init__(
        self,
        indent: str = None,
        comment_ws: str = None,
        comment: str = None,
        trail: str = None,
    ) -> None:
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

    def copy(self) -> "Trivia":
        return type(self)(self.indent, self.comment_ws, self.comment, self.trail)


class KeyType(Enum):
    """
    The type of a Key.

    Keys can be bare (unquoted), or quoted using basic ("), or literal (')
    quotes following the same escaping rules as single-line StringType.
    """

    Bare = ""
    Basic = '"'
    Literal = "'"


class Key(abc.ABC):
    """Base class for a key"""

    sep: str
    _original: str
    _keys: List["SingleKey"]
    _dotted: bool
    key: str

    @abc.abstractmethod
    def __hash__(self) -> int:
        pass

    @abc.abstractmethod
    def __eq__(self, __o: object) -> bool:
        pass

    def is_dotted(self) -> bool:
        """If the key is followed by other keys"""
        return self._dotted

    def __iter__(self) -> Iterator["SingleKey"]:
        return iter(self._keys)

    def concat(self, other: "Key") -> "DottedKey":
        """Concatenate keys into a dotted key"""
        keys = self._keys + other._keys
        return DottedKey(keys, sep=self.sep)

    def is_multi(self) -> bool:
        """Check if the key contains multiple keys"""
        return len(self._keys) > 1

    def as_string(self) -> str:
        """The TOML representation"""
        return self._original

    def __str__(self) -> str:
        return self.as_string()

    def __repr__(self) -> str:
        return f"<Key {self.as_string()}>"


class SingleKey(Key):
    """A single key"""

    def __init__(
        self,
        k: str,
        t: Optional[KeyType] = None,
        sep: Optional[str] = None,
        original: Optional[str] = None,
    ) -> None:
        if t is None:
            if not k or any(
                c not in string.ascii_letters + string.digits + "-" + "_" for c in k
            ):
                t = KeyType.Basic
            else:
                t = KeyType.Bare

        self.t = t
        if sep is None:
            sep = " = "

        self.sep = sep
        self.key = k
        if original is None:
            key_str = escape_string(k) if t == KeyType.Basic else k
            original = f"{t.value}{key_str}{t.value}"

        self._original = original
        self._keys = [self]
        self._dotted = False

    @property
    def delimiter(self) -> str:
        """The delimiter: double quote/single quote/none"""
        return self.t.value

    def is_bare(self) -> bool:
        """Check if the key is bare"""
        return self.t == KeyType.Bare

    def __hash__(self) -> int:
        return hash(self.key)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, Key):
            return isinstance(other, SingleKey) and self.key == other.key

        return self.key == other


class DottedKey(Key):
    def __init__(
        self,
        keys: Iterable[Key],
        sep: Optional[str] = None,
        original: Optional[str] = None,
    ) -> None:
        self._keys = list(keys)
        if original is None:
            original = ".".join(k.as_string() for k in self._keys)

        self.sep = " = " if sep is None else sep
        self._original = original
        self._dotted = False
        self.key = ".".join(k.key for k in self._keys)

    def __hash__(self) -> int:
        return hash(tuple(self._keys))

    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, DottedKey) and self._keys == __o._keys


class Item:
    """
    An item within a TOML document.
    """

    def __init__(self, trivia: Trivia) -> None:
        self._trivia = trivia

    @property
    def trivia(self) -> Trivia:
        """The trivia element associated with this item"""
        return self._trivia

    @property
    def discriminant(self) -> int:
        raise NotImplementedError()

    def as_string(self) -> str:
        """The TOML representation"""
        raise NotImplementedError()

    # Helpers

    def comment(self, comment: str) -> "Item":
        """Attach a comment to this item"""
        if not comment.strip().startswith("#"):
            comment = "# " + comment

        self._trivia.comment_ws = " "
        self._trivia.comment = comment

        return self

    def indent(self, indent: int) -> "Item":
        """Indent this item with given number of spaces"""
        if self._trivia.indent.startswith("\n"):
            self._trivia.indent = "\n" + " " * indent
        else:
            self._trivia.indent = " " * indent

        return self

    def is_boolean(self) -> bool:
        return isinstance(self, Bool)

    def is_table(self) -> bool:
        return isinstance(self, Table)

    def is_inline_table(self) -> bool:
        return isinstance(self, InlineTable)

    def is_aot(self) -> bool:
        return isinstance(self, AoT)

    def _getstate(self, protocol=3):
        return (self._trivia,)

    def __reduce__(self):
        return self.__reduce_ex__(2)

    def __reduce_ex__(self, protocol):
        return self.__class__, self._getstate(protocol)


class Whitespace(Item):
    """
    A whitespace literal.
    """

    def __init__(self, s: str, fixed: bool = False) -> None:
        self._s = s
        self._fixed = fixed

    @property
    def s(self) -> str:
        return self._s

    @property
    def value(self) -> str:
        """The wrapped string of the whitespace"""
        return self._s

    @property
    def trivia(self) -> Trivia:
        raise RuntimeError("Called trivia on a Whitespace variant.")

    @property
    def discriminant(self) -> int:
        return 0

    def is_fixed(self) -> bool:
        """If the whitespace is fixed, it can't be merged or discarded from the output."""
        return self._fixed

    def as_string(self) -> str:
        return self._s

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {repr(self._s)}>"

    def _getstate(self, protocol=3):
        return self._s, self._fixed


class Comment(Item):
    """
    A comment literal.
    """

    @property
    def discriminant(self) -> int:
        return 1

    def as_string(self) -> str:
        return "{}{}{}".format(
            self._trivia.indent, decode(self._trivia.comment), self._trivia.trail
        )

    def __str__(self) -> str:
        return f"{self._trivia.indent}{decode(self._trivia.comment)}"


class Integer(int, Item):
    """
    An integer literal.
    """

    def __new__(cls, value: int, trivia: Trivia, raw: str) -> "Integer":
        return super().__new__(cls, value)

    def __init__(self, _: int, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-]\d+$", raw):
            self._sign = True

    @property
    def discriminant(self) -> int:
        return 2

    @property
    def value(self) -> int:
        """The wrapped integer value"""
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super().__radd__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super().__rsub__(other)

        if isinstance(other, Integer):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Integer(result, self._trivia, raw)

    def _getstate(self, protocol=3):
        return int(self), self._trivia, self._raw


class Float(float, Item):
    """
    A float literal.
    """

    def __new__(cls, value: float, trivia: Trivia, raw: str) -> Integer:
        return super().__new__(cls, value)

    def __init__(self, _: float, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)

        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-].+$", raw):
            self._sign = True

    @property
    def discriminant(self) -> int:
        return 3

    @property
    def value(self) -> float:
        """The wrapped float value"""
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __radd__(self, other):
        result = super().__radd__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def __rsub__(self, other):
        result = super().__rsub__(other)

        if isinstance(other, Float):
            return self._new(result)

        return result

    def _new(self, result):
        raw = str(result)

        if self._sign:
            sign = "+" if result >= 0 else "-"
            raw = sign + raw

        return Float(result, self._trivia, raw)

    def _getstate(self, protocol=3):
        return float(self), self._trivia, self._raw


class Bool(Item):
    """
    A boolean literal.
    """

    def __init__(self, t: int, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._value = bool(t)

    @property
    def discriminant(self) -> int:
        return 4

    @property
    def value(self) -> bool:
        """The wrapped boolean value"""
        return self._value

    def as_string(self) -> str:
        return str(self._value).lower()

    def _getstate(self, protocol=3):
        return self._value, self._trivia

    def __bool__(self):
        return self._value

    __nonzero__ = __bool__

    def __eq__(self, other):
        if not isinstance(other, bool):
            return NotImplemented

        return other == self._value

    def __hash__(self):
        return hash(self._value)

    def __repr__(self):
        return repr(self._value)


class DateTime(Item, datetime):
    """
    A datetime literal.
    """

    def __new__(
        cls,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
        **kwargs: Any,
    ) -> datetime:
        return datetime.__new__(
            cls,
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo=tzinfo,
            **kwargs,
        )

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 5

    @property
    def value(self) -> datetime:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        if PY38:
            result = datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
                self.microsecond,
                self.tzinfo,
            ).__add__(other)
        else:
            result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        if PY38:
            result = datetime(
                self.year,
                self.month,
                self.day,
                self.hour,
                self.minute,
                self.second,
                self.microsecond,
                self.tzinfo,
            ).__sub__(other)
        else:
            result = super().__sub__(other)

        if isinstance(result, datetime):
            result = self._new(result)

        return result

    def _new(self, result):
        raw = result.isoformat()

        return DateTime(
            result.year,
            result.month,
            result.day,
            result.hour,
            result.minute,
            result.second,
            result.microsecond,
            result.tzinfo,
            self._trivia,
            raw,
        )

    def _getstate(self, protocol=3):
        return (
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            self.tzinfo,
            self._trivia,
            self._raw,
        )


class Date(Item, date):
    """
    A date literal.
    """

    def __new__(cls, year: int, month: int, day: int, *_: Any) -> date:
        return date.__new__(cls, year, month, day)

    def __init__(
        self, year: int, month: int, day: int, trivia: Trivia, raw: str
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 6

    @property
    def value(self) -> date:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other):
        if PY38:
            result = date(self.year, self.month, self.day).__add__(other)
        else:
            result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        if PY38:
            result = date(self.year, self.month, self.day).__sub__(other)
        else:
            result = super().__sub__(other)

        if isinstance(result, date):
            result = self._new(result)

        return result

    def _new(self, result):
        raw = result.isoformat()

        return Date(result.year, result.month, result.day, self._trivia, raw)

    def _getstate(self, protocol=3):
        return (self.year, self.month, self.day, self._trivia, self._raw)


class Time(Item, time):
    """
    A time literal.
    """

    def __new__(
        cls,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        *_: Any,
    ) -> time:
        return time.__new__(cls, hour, minute, second, microsecond, tzinfo)

    def __init__(
        self,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: Optional[tzinfo],
        trivia: Trivia,
        raw: str,
    ) -> None:
        super().__init__(trivia)

        self._raw = raw

    @property
    def discriminant(self) -> int:
        return 7

    @property
    def value(self) -> time:
        return self

    def as_string(self) -> str:
        return self._raw

    def _getstate(self, protocol: int = 3) -> tuple:
        return (
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            self.tzinfo,
            self._trivia,
            self._raw,
        )


class Array(Item, _CustomList):
    """
    An array literal
    """

    def __init__(self, value: list, trivia: Trivia, multiline: bool = False) -> None:
        super().__init__(trivia)
        self._index_map: Dict[int, int] = {}
        list.__init__(
            self, [v.value for v in value if not isinstance(v, (Whitespace, Comment))]
        )

        self._value = value
        self._multiline = multiline
        self._reindex()

    @property
    def discriminant(self) -> int:
        return 8

    @property
    def value(self) -> list:
        return self

    def multiline(self, multiline: bool) -> "Array":
        """Change the array to display in multiline or not.

        :Example:

        >>> a = item([1, 2, 3])
        >>> print(a.as_string())
        [1, 2, 3]
        >>> print(a.multiline(True).as_string())
        [
            1,
            2,
            3,
        ]
        """
        self._multiline = multiline

        return self

    def as_string(self) -> str:
        if not self._multiline or not self._value:
            return "[{}]".format("".join(v.as_string() for v in self._value))

        s = "[\n" + self.trivia.indent + " " * 4
        s += (",\n" + self.trivia.indent + " " * 4).join(
            v.as_string() for v in self._value if not isinstance(v, Whitespace)
        )
        s += ",\n"
        s += "]"

        return s

    def _reindex(self) -> None:
        self._index_map.clear()
        index = 0
        for i, v in enumerate(self._value):
            if isinstance(v, (Whitespace, Comment)):
                continue
            self._index_map[index] = i
            index += 1

    def add_line(
        self,
        *items: Any,
        indent: str = "    ",
        comment: Optional[str] = None,
        add_comma: bool = True,
        newline: bool = True,
    ) -> None:
        """Add multiple items in a line to control the format precisely.
        When add_comma is True, only accept actual values and
        ", " will be added between values automatically.

        :Example:

        >>> a = array()
        >>> a.add_line(1, 2, 3)
        >>> a.add_line(4, 5, 6)
        >>> a.add_line(indent="")
        >>> print(a.as_string())
        [
            1, 2, 3,
            4, 5, 6,
        ]
        """
        values = self._value[:]
        new_values = []

        def append_item(el: Item) -> None:
            if not values:
                return values.append(el)
            last_el = values[-1]
            if (
                isinstance(el, Whitespace)
                and "," not in el.s
                and isinstance(last_el, Whitespace)
                and "," not in last_el.s
            ):
                values[-1] = Whitespace(last_el.s + el.s)
            else:
                values.append(el)

        if newline:
            append_item(Whitespace("\n"))
        if indent:
            append_item(Whitespace(indent))
        for i, el in enumerate(items):
            el = item(el, _parent=self)
            if isinstance(el, Comment) or add_comma and isinstance(el, Whitespace):
                raise ValueError(f"item type {type(el)} is not allowed")
            if not isinstance(el, Whitespace):
                new_values.append(el.value)
            append_item(el)
            if add_comma:
                append_item(Whitespace(","))
                if i != len(items) - 1:
                    append_item(Whitespace(" "))
        if comment:
            indent = " " if items else ""
            append_item(
                Comment(Trivia(indent=indent, comment=f"# {comment}", trail=""))
            )
        # Atomic manipulation
        self._value[:] = values
        list.extend(self, new_values)
        self._reindex()

    def clear(self) -> None:
        """Clear the array."""
        list.clear(self)

        self._value.clear()
        self._index_map.clear()

    def __len__(self) -> int:
        return list.__len__(self)

    def __getitem__(self, key: Union[int, slice]) -> Any:
        return list.__getitem__(self, key)

    def __setitem__(self, key: Union[int, slice], value: Any) -> Any:
        it = item(value, _parent=self)
        list.__setitem__(self, key, it.value)
        if isinstance(key, slice):
            raise ValueError("slice assignment is not supported")
        if key < 0:
            key += len(self)
        self._value[self._index_map[key]] = it

    def insert(self, pos: int, value: Any) -> None:
        it = item(value, _parent=self)
        length = len(self)
        if not isinstance(it, (Comment, Whitespace)):
            list.insert(self, pos, it.value)
        if pos < 0:
            pos += length
            if pos < 0:
                pos = 0

        items = [it]
        idx = 0
        if pos < length:
            try:
                idx = self._index_map[pos]
            except KeyError:
                raise IndexError("list index out of range")
            if not isinstance(it, (Whitespace, Comment)):
                items.append(Whitespace(","))
        else:
            idx = len(self._value)
        if idx > 0:
            last_item = self._value[idx - 1]
            if isinstance(last_item, Whitespace) and "," not in last_item.s:
                # the item has an indent, copy that
                idx -= 1
                ws = last_item.s
                if isinstance(it, Whitespace) and "," not in it.s:
                    # merge the whitespace
                    self._value[idx] = Whitespace(ws + it.s)
                    return
            else:
                ws = ""
            has_newline = bool(set(ws) & set(TOMLChar.NL))
            has_space = ws and ws[-1] in TOMLChar.SPACES
            if not has_space:
                # four spaces for multiline array and single space otherwise
                ws += "    " if has_newline else " "
            items.insert(0, Whitespace(ws))
        self._value[idx:idx] = items
        i = idx - 1
        if pos > 0:  # Check if the last item ends with a comma
            while i >= 0 and isinstance(self._value[i], (Whitespace, Comment)):
                if isinstance(self._value[i], Whitespace) and "," in self._value[i].s:
                    break
                i -= 1
            else:
                self._value.insert(i + 1, Whitespace(","))

        self._reindex()

    def __delitem__(self, key: Union[int, slice]):
        length = len(self)
        list.__delitem__(self, key)

        def get_indice_to_remove(idx: int) -> Iterable[int]:
            try:
                real_idx = self._index_map[idx]
            except KeyError:
                raise IndexError("list index out of range")
            yield real_idx
            for i in range(real_idx + 1, len(self._value)):
                if isinstance(self._value[i], Whitespace):
                    yield i
                else:
                    break

        indexes = set()
        if isinstance(key, slice):
            for idx in range(key.start or 0, key.stop or length, key.step or 1):
                indexes.update(get_indice_to_remove(idx))
        else:
            indexes.update(get_indice_to_remove(length + key if key < 0 else key))
        for i in sorted(indexes, reverse=True):
            del self._value[i]
        while self._value and isinstance(self._value[-1], Whitespace):
            self._value.pop()
        self._reindex()

    def __str__(self):
        return str(
            [v.value for v in self._value if not isinstance(v, (Whitespace, Comment))]
        )

    def _getstate(self, protocol=3):
        return self._value, self._trivia


AT = TypeVar("AT", bound="AbstractTable")


class AbstractTable(Item, _CustomDict):
    """Common behaviour of both :class:`Table` and :class:`InlineTable`"""

    def __init__(self, value: "container.Container", trivia: Trivia):
        Item.__init__(self, trivia)

        self._value = value

        for k, v in self._value.body:
            if k is not None:
                dict.__setitem__(self, k.key, v)

    @property
    def value(self) -> "container.Container":
        return self._value

    @overload
    def append(self: AT, key: None, value: Union[Comment, Whitespace]) -> AT:
        ...

    @overload
    def append(self: AT, key: Union[Key, str], value: Any) -> AT:
        ...

    def append(self, key, value):
        raise NotImplementedError

    @overload
    def add(self: AT, value: Union[Comment, Whitespace]) -> AT:
        ...

    @overload
    def add(self: AT, key: Union[Key, str], value: Any) -> AT:
        ...

    def add(self, key, value=None):
        if value is None:
            if not isinstance(key, (Comment, Whitespace)):
                msg = "Non comment/whitespace items must have an associated key"
                raise ValueError(msg)

            key, value = None, key

        return self.append(key, value)

    def remove(self: AT, key: Union[Key, str]) -> AT:
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__delitem__(self, key)

        return self

    def setdefault(self, key: Union[Key, str], default: Any) -> Any:
        super().setdefault(key, default)
        return self[key]

    def __str__(self):
        return str(self.value)

    def copy(self: AT) -> AT:
        return copy.copy(self)

    def __repr__(self) -> str:
        return repr(self.value)

    def __iter__(self) -> Iterator[str]:
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __delitem__(self, key: Union[Key, str]) -> None:
        self.remove(key)

    def __getitem__(self, key: Union[Key, str]) -> Item:
        return cast(Item, self._value[key])

    def __setitem__(self, key: Union[Key, str], value: Any) -> None:
        if not isinstance(value, Item):
            value = item(value)

        is_replace = key in self
        self._value[key] = value

        if key is not None:
            dict.__setitem__(self, key, value)

        if is_replace:
            return
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


class Table(AbstractTable):
    """
    A table literal.
    """

    def __init__(
        self,
        value: "container.Container",
        trivia: Trivia,
        is_aot_element: bool,
        is_super_table: bool = False,
        name: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> None:
        super().__init__(value, trivia)

        self.name = name
        self.display_name = display_name
        self._is_aot_element = is_aot_element
        self._is_super_table = is_super_table

    @property
    def discriminant(self) -> int:
        return 9

    def __copy__(self) -> "Table":
        return type(self)(
            self._value.copy(),
            self._trivia.copy(),
            self._is_aot_element,
            self._is_super_table,
            self.name,
            self.display_name,
        )

    def append(self, key, _item):
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = next(iter(key)).key
            _item = self._value[key]

        if key is not None:
            dict.__setitem__(self, key, _item)

        m = re.match(r"(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
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

    def raw_append(self, key: Union[Key, str], _item: Any) -> "Table":
        """Similar to :meth:`append` but does not copy indentation."""
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = next(iter(key)).key
            _item = self._value[key]

        if key is not None:
            dict.__setitem__(self, key, _item)

        return self

    def is_aot_element(self) -> bool:
        """True if the table is the direct child of an AOT element."""
        return self._is_aot_element

    def is_super_table(self) -> bool:
        """A super table is the intermediate parent of a nested table as in [a.b.c].
        If true, it won't appear in the TOML representation."""
        return self._is_super_table

    def as_string(self) -> str:
        return self._value.as_string()

    # Helpers

    def indent(self, indent: int) -> "Table":
        """Indent the table with given number of spaces."""
        super().indent(indent)

        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if not m:
            indent_str = ""
        else:
            indent_str = m.group(1)

        for _, item in self._value.body:
            if not isinstance(item, Whitespace):
                item.trivia.indent = indent_str + item.trivia.indent

        return self

    def invalidate_display_name(self):
        self.display_name = None

        for child in self.values():
            if hasattr(child, "invalidate_display_name"):
                child.invalidate_display_name()

    def _getstate(self, protocol: int = 3) -> tuple:
        return (
            self._value,
            self._trivia,
            self._is_aot_element,
            self._is_super_table,
            self.name,
            self.display_name,
        )


class InlineTable(AbstractTable):
    """
    An inline table literal.
    """

    def __init__(
        self, value: "container.Container", trivia: Trivia, new: bool = False
    ) -> None:
        super().__init__(value, trivia)

        self._new = new

    @property
    def discriminant(self) -> int:
        return 10

    def append(self, key, _item):
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item)

        if not isinstance(_item, (Whitespace, Comment)):
            if not _item.trivia.indent and len(self._value) > 0 and not self._new:
                _item.trivia.indent = " "
            if _item.trivia.comment:
                _item.trivia.comment = ""

        self._value.append(key, _item)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__setitem__(self, key, _item)

        return self

    def as_string(self) -> str:
        buf = "{"
        for i, (k, v) in enumerate(self._value.body):
            if k is None:
                if i == len(self._value.body) - 1:
                    if self._new:
                        buf = buf.rstrip(", ")
                    else:
                        buf = buf.rstrip(",")

                buf += v.as_string()

                continue

            buf += "{}{}{}{}{}{}".format(
                v.trivia.indent,
                k.as_string() + ("." if k.is_dotted() else ""),
                k.sep,
                v.as_string(),
                v.trivia.comment,
                v.trivia.trail.replace("\n", ""),
            )

            if i != len(self._value.body) - 1:
                buf += ","
                if self._new:
                    buf += " "

        buf += "}"

        return buf

    def __setitem__(self, key: Union[Key, str], value: Any) -> None:
        if hasattr(value, "trivia") and value.trivia.comment:
            value.trivia.comment = ""
        super().__setitem__(key, value)

    def __copy__(self) -> "InlineTable":
        return type(self)(self._value.copy(), self._trivia.copy(), self._new)

    def _getstate(self, protocol: int = 3) -> tuple:
        return (self._value, self._trivia)


class String(str, Item):
    """
    A string literal.
    """

    def __new__(cls, t, value, original, trivia):
        return super().__new__(cls, value)

    def __init__(self, t: StringType, _: str, original: str, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._t = t
        self._original = original

    @property
    def discriminant(self) -> int:
        return 11

    @property
    def value(self) -> str:
        return self

    def as_string(self) -> str:
        return f"{self._t.value}{decode(self._original)}{self._t.value}"

    def __add__(self, other):
        result = super().__add__(other)

        return self._new(result)

    def __sub__(self, other):
        result = super().__sub__(other)

        return self._new(result)

    def _new(self, result):
        return String(self._t, result, result, self._trivia)

    def _getstate(self, protocol=3):
        return self._t, str(self), self._original, self._trivia


class AoT(Item, _CustomList):
    """
    An array of table literal
    """

    def __init__(
        self, body: List[Table], name: Optional[str] = None, parsed: bool = False
    ) -> None:
        self.name = name
        self._body: List[Table] = []
        self._parsed = parsed

        super().__init__(Trivia(trail=""))

        for table in body:
            self.append(table)

    @property
    def body(self) -> List[Table]:
        return self._body

    @property
    def discriminant(self) -> int:
        return 12

    @property
    def value(self) -> List[Dict[Any, Any]]:
        return [v.value for v in self._body]

    def __len__(self) -> int:
        return len(self._body)

    @overload
    def __getitem__(self, key: slice) -> List[Table]:
        ...

    @overload
    def __getitem__(self, key: int) -> Table:
        ...

    def __getitem__(self, key):
        return self._body[key]

    def __setitem__(self, key: Union[slice, int], value: Any) -> None:
        raise NotImplementedError

    def __delitem__(self, key: Union[slice, int]) -> None:
        del self._body[key]
        list.__delitem__(self, key)

    def insert(self, index: int, value: dict) -> None:
        value = item(value, _parent=self)
        if not isinstance(value, Table):
            raise ValueError(f"Unsupported insert value type: {type(value)}")
        length = len(self)
        if index < 0:
            index += length
        if index < 0:
            index = 0
        elif index >= length:
            index = length
        m = re.match("(?s)^[^ ]*([ ]+).*$", self._trivia.indent)
        if m:
            indent = m.group(1)

            m = re.match("(?s)^([^ ]*)(.*)$", value.trivia.indent)
            if not m:
                value.trivia.indent = indent
            else:
                value.trivia.indent = m.group(1) + indent + m.group(2)
        prev_table = self._body[index - 1] if 0 < index and length else None
        next_table = self._body[index + 1] if index < length - 1 else None
        if not self._parsed:
            if prev_table and "\n" not in value.trivia.indent:
                value.trivia.indent = "\n" + value.trivia.indent
            if next_table and "\n" not in next_table.trivia.indent:
                next_table.trivia.indent = "\n" + next_table.trivia.indent
        self._body.insert(index, value)
        list.insert(self, index, value)

    def invalidate_display_name(self):
        """Call ``invalidate_display_name`` on the contained tables"""
        for child in self:
            if hasattr(child, "invalidate_display_name"):
                child.invalidate_display_name()

    def as_string(self) -> str:
        b = ""
        for table in self._body:
            b += table.as_string()

        return b

    def __repr__(self) -> str:
        return f"<AoT {self.value}>"

    def _getstate(self, protocol=3):
        return self._body, self.name, self._parsed


class Null(Item):
    """
    A null item.
    """

    def __init__(self) -> None:
        pass

    @property
    def discriminant(self) -> int:
        return -1

    @property
    def value(self) -> None:
        return None

    def as_string(self) -> str:
        return ""

    def _getstate(self, protocol=3):
        return tuple()
