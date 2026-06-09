from __future__ import annotations

import abc
import copy
import dataclasses
import inspect
import re
import string

from collections.abc import Collection
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Sequence
from datetime import date
from datetime import datetime
from datetime import time
from datetime import timedelta
from datetime import tzinfo
from enum import Enum
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from typing import overload

from pipenv.vendor.tomlkit._compat import PY38
from pipenv.vendor.tomlkit._compat import decode
from pipenv.vendor.tomlkit._types import _CustomDict
from pipenv.vendor.tomlkit._types import _CustomFloat
from pipenv.vendor.tomlkit._types import _CustomInt
from pipenv.vendor.tomlkit._types import _CustomList
from pipenv.vendor.tomlkit._utils import CONTROL_CHARS
from pipenv.vendor.tomlkit._utils import escape_string
from pipenv.vendor.tomlkit.exceptions import ConvertError
from pipenv.vendor.tomlkit.exceptions import InvalidStringError


if TYPE_CHECKING:
    from typing import Protocol

    from pipenv.vendor.tomlkit import container
    from pipenv.vendor.tomlkit.container import OutOfOrderTableProxy

    class Encoder(Protocol):
        def __call__(self, __value: Any, /) -> Item: ...


ItemT = TypeVar("ItemT", bound="Item")
CUSTOM_ENCODERS: list[Encoder] = []
AT = TypeVar("AT", bound="AbstractTable")


@overload
def item(value: bool, _parent: Item | None = ..., _sort_keys: bool = ...) -> Bool: ...  # type: ignore[overload-overlap]


@overload
def item(value: int, _parent: Item | None = ..., _sort_keys: bool = ...) -> Integer: ...


@overload
def item(value: float, _parent: Item | None = ..., _sort_keys: bool = ...) -> Float: ...


@overload
def item(value: str, _parent: Item | None = ..., _sort_keys: bool = ...) -> String: ...


@overload
def item(  # type: ignore[overload-overlap]
    value: datetime, _parent: Item | None = ..., _sort_keys: bool = ...
) -> DateTime: ...


@overload
def item(value: date, _parent: Item | None = ..., _sort_keys: bool = ...) -> Date: ...


@overload
def item(value: time, _parent: Item | None = ..., _sort_keys: bool = ...) -> Time: ...


@overload
def item(
    value: Sequence[dict[str, Any]], _parent: Item | None = ..., _sort_keys: bool = ...
) -> AoT: ...


@overload
def item(
    value: Sequence[Any], _parent: Item | None = ..., _sort_keys: bool = ...
) -> Array: ...


@overload
def item(
    value: dict[str, Any], _parent: Array = ..., _sort_keys: bool = ...
) -> InlineTable: ...


@overload
def item(
    value: dict[str, Any], _parent: Item | None = ..., _sort_keys: bool = ...
) -> Table: ...


@overload
def item(value: ItemT, _parent: Item | None = ..., _sort_keys: bool = ...) -> ItemT: ...


@overload
def item(value: object, _parent: Item | None = ..., _sort_keys: bool = ...) -> Item: ...


def item(value: Any, _parent: Item | None = None, _sort_keys: bool = False) -> Item:
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

    from pipenv.vendor.tomlkit.container import Container

    if isinstance(value, Item):
        return value

    if isinstance(value, bool):
        return Bool(value, Trivia())
    elif isinstance(value, int):
        return Integer(value, Trivia(), str(value))
    elif isinstance(value, float):
        return Float(value, Trivia(), str(value))
    elif isinstance(value, dict):
        table_constructor = (
            InlineTable if isinstance(_parent, (Array, InlineTable)) else Table
        )
        val = table_constructor(Container(), Trivia(), False)
        for k, v in sorted(
            value.items(),
            key=lambda i: (isinstance(i[1], dict), i[0]) if _sort_keys else 1,
        ):
            val[k] = item(v, _parent=val, _sort_keys=_sort_keys)

        return val
    elif isinstance(value, (list, tuple)):
        a: AoT | Array
        if (
            value
            and all(isinstance(v, dict) for v in value)
            and (_parent is None or isinstance(_parent, Table))
        ):
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
                    i = item(_v, _parent=table, _sort_keys=_sort_keys)
                    if isinstance(table, InlineTable):
                        i.trivia.trail = ""

                    table[k] = i

                v = table

            a.append(v)

        return a
    elif isinstance(value, str):
        return String.from_raw(value)
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
    else:
        for encoder in CUSTOM_ENCODERS:
            try:
                # Check if encoder accepts keyword arguments for backward compatibility
                sig = inspect.signature(encoder)
                if "_parent" in sig.parameters or any(
                    p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
                ):
                    # New style encoder that can accept additional parameters
                    rv = encoder(value, _parent=_parent, _sort_keys=_sort_keys)  # type: ignore[call-arg]
                else:
                    # Old style encoder that only accepts value
                    rv = encoder(value)
            except ConvertError:
                pass
            else:
                if not isinstance(rv, Item):
                    raise ConvertError(
                        f"Custom encoder is expected to return an instance of Item, got {type(rv)}"
                    )
                return rv

    raise ConvertError(f"Unable to convert an object of {type(value)} to a TOML item")


class StringType(Enum):
    # Single Line Basic
    SLB = '"'
    # Multi Line Basic
    MLB = '"""'
    # Single Line Literal
    SLL = "'"
    # Multi Line Literal
    MLL = "'''"

    @classmethod
    def select(cls, literal: bool = False, multiline: bool = False) -> StringType:
        return {
            (False, False): cls.SLB,
            (False, True): cls.MLB,
            (True, False): cls.SLL,
            (True, True): cls.MLL,
        }[(literal, multiline)]

    @property
    def escaped_sequences(self) -> Collection[str]:
        # https://toml.io/en/v1.0.0#string
        escaped_in_basic = CONTROL_CHARS | {"\\"}
        allowed_in_multiline = {"\n", "\r"}
        return {
            StringType.SLB: escaped_in_basic | {'"'},
            StringType.MLB: (escaped_in_basic | {'"""'}) - allowed_in_multiline,
            StringType.SLL: (),
            StringType.MLL: (),
        }[self]

    @property
    def invalid_sequences(self) -> Collection[str]:
        # https://toml.io/en/v1.0.0#string
        forbidden_in_literal = CONTROL_CHARS - {"\t"}
        allowed_in_multiline = {"\n", "\r"}
        return {
            StringType.SLB: (),
            StringType.MLB: (),
            StringType.SLL: forbidden_in_literal | {"'"},
            StringType.MLL: (forbidden_in_literal | {"'''"}) - allowed_in_multiline,
        }[self]

    @property
    def unit(self) -> str:
        return self.value[0]

    def is_basic(self) -> bool:
        return self in {StringType.SLB, StringType.MLB}

    def is_literal(self) -> bool:
        return self in {StringType.SLL, StringType.MLL}

    def is_singleline(self) -> bool:
        return self in {StringType.SLB, StringType.SLL}

    def is_multiline(self) -> bool:
        return self in {StringType.MLB, StringType.MLL}

    def toggle(self) -> StringType:
        return {
            StringType.SLB: StringType.MLB,
            StringType.MLB: StringType.SLB,
            StringType.SLL: StringType.MLL,
            StringType.MLL: StringType.SLL,
        }[self]


class BoolType(Enum):
    TRUE = "true"
    FALSE = "false"

    def __bool__(self) -> bool:
        return {BoolType.TRUE: True, BoolType.FALSE: False}[self]

    def __iter__(self) -> Iterator[str]:
        return iter(self.value)

    def __len__(self) -> int:
        return len(self.value)


@dataclasses.dataclass
class Trivia:
    """
    Trivia information (aka metadata).
    """

    # Whitespace before a value.
    indent: str = ""
    # Whitespace after a value, but before a comment.
    comment_ws: str = ""
    # Comment, starting with # character, or empty string if no comment.
    comment: str = ""
    # Trailing newline.
    trail: str = "\n"

    def copy(self) -> Trivia:
        return dataclasses.replace(self)


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
    _keys: list[SingleKey]
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

    def __iter__(self) -> Iterator[SingleKey]:
        return iter(self._keys)

    def concat(self, other: Key) -> DottedKey:
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
        t: KeyType | None = None,
        sep: str | None = None,
        original: str | None = None,
    ) -> None:
        if not isinstance(k, str):
            raise TypeError("Keys must be strings")

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

        return bool(self.key == other)


class DottedKey(Key):
    def __init__(
        self,
        keys: Iterable[SingleKey],
        sep: str | None = None,
        original: str | None = None,
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

    @property
    def value(self) -> Any:
        return self

    def unwrap(self) -> Any:
        """Returns as pure python object (ppo)"""
        raise NotImplementedError()

    # Helpers

    def comment(self, comment: str) -> Item:
        """Attach a comment to this item"""
        if not comment.strip().startswith("#"):
            comment = "# " + comment

        self._trivia.comment_ws = " "
        self._trivia.comment = comment

        return self

    def indent(self, indent: int) -> Item:
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

    def _getstate(self, protocol: int = 3) -> tuple[object, ...]:
        return (self._trivia,)

    def __reduce__(self) -> tuple[type, tuple[object, ...]]:
        return self.__reduce_ex__(2)

    def __reduce_ex__(self, protocol: int) -> tuple[type, tuple[object, ...]]:  # type: ignore[override]
        return self.__class__, self._getstate(protocol)

    def __getitem__(self, key: Key | str | int) -> Any:
        raise TypeError(f"{type(self).__name__} does not support item access")

    def __setitem__(self, key: Key | str | int, value: Any) -> None:
        raise TypeError(f"{type(self).__name__} does not support item assignment")

    def __delitem__(self, key: Key | str | int) -> None:
        raise TypeError(f"{type(self).__name__} does not support item deletion")


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
        return f"<{self.__class__.__name__} {self._s!r}>"

    def _getstate(self, protocol: int = 3) -> tuple[str, bool]:
        return self._s, self._fixed


class Comment(Item):
    """
    A comment literal.
    """

    @property
    def discriminant(self) -> int:
        return 1

    def as_string(self) -> str:
        return (
            f"{self._trivia.indent}{decode(self._trivia.comment)}{self._trivia.trail}"
        )

    def __str__(self) -> str:
        return f"{self._trivia.indent}{decode(self._trivia.comment)}"


class Integer(Item, _CustomInt):
    """
    An integer literal.
    """

    def __new__(cls, value: int, trivia: Trivia, raw: str) -> Integer:
        return int.__new__(cls, value)

    def __init__(self, value: int, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)
        self._original = value
        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-]\d+$", raw):
            self._sign = True

    def unwrap(self) -> int:
        return self._original

    __int__ = unwrap

    def __hash__(self) -> int:
        return hash(self.unwrap())

    @property
    def discriminant(self) -> int:
        return 2

    @property
    def value(self) -> int:
        """The wrapped integer value"""
        return self

    def as_string(self) -> str:
        return self._raw

    def _new(self, result: int) -> Integer:
        raw = str(result)
        if self._sign and result >= 0:
            raw = f"+{raw}"

        return Integer(result, self._trivia, raw)

    def _getstate(self, protocol: int = 3) -> tuple[int, Trivia, str]:
        return int(self), self._trivia, self._raw

    # int methods — explicit typed wrappers
    def __abs__(self) -> Integer:
        return self._new(int.__abs__(self))

    def __add__(self, other: object) -> Integer:
        result = int.__add__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __and__(self, other: object) -> Integer:
        result = int.__and__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __ceil__(self) -> Integer:
        return self._new(int.__ceil__(self))

    __eq__ = int.__eq__

    def __floor__(self) -> Integer:
        return self._new(int.__floor__(self))

    def __floordiv__(self, other: object) -> Integer:
        result = int.__floordiv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __invert__(self) -> Integer:
        return self._new(int.__invert__(self))

    __le__ = int.__le__

    def __lshift__(self, other: object) -> Integer:
        result = int.__lshift__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    __lt__ = int.__lt__

    def __mod__(self, other: object) -> Integer:
        result = int.__mod__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __mul__(self, other: object) -> Integer:
        result = int.__mul__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __neg__(self) -> Integer:
        return self._new(int.__neg__(self))

    def __or__(self, other: object) -> Integer:
        result = int.__or__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __pos__(self) -> Integer:
        return self._new(int.__pos__(self))

    def __pow__(self, other: int, mod: int | None = None) -> Integer:  # type: ignore[override]
        result = (
            int.__pow__(self, other) if mod is None else int.__pow__(self, other, mod)
        )
        return self._new(result)

    def __radd__(self, other: object) -> Integer:
        result = int.__radd__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rand__(self, other: object) -> Integer:
        result = int.__rand__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rfloordiv__(self, other: object) -> Integer:
        result = int.__rfloordiv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rlshift__(self, other: object) -> Integer:
        result = int.__rlshift__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rmod__(self, other: object) -> Integer:
        result = int.__rmod__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rmul__(self, other: object) -> Integer:
        result = int.__rmul__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __ror__(self, other: object) -> Integer:
        result = int.__ror__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __round__(self, ndigits: int = 0) -> Integer:  # type: ignore[override]
        return self._new(int.__round__(self, ndigits))

    def __rpow__(self, other: int, mod: int | None = None) -> Integer:  # type: ignore[misc]
        result = (
            int.__rpow__(self, other) if mod is None else int.__rpow__(self, other, mod)
        )
        return self._new(result)

    def __rrshift__(self, other: object) -> Integer:
        result = int.__rrshift__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rshift__(self, other: object) -> Integer:
        result = int.__rshift__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rxor__(self, other: object) -> Integer:
        result = int.__rxor__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __sub__(self, other: object) -> Integer:
        result = int.__sub__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rsub__(self, other: object) -> Integer:
        result = int.__rsub__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __trunc__(self) -> Integer:
        return self._new(int.__trunc__(self))

    def __xor__(self, other: object) -> Integer:
        result = int.__xor__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rtruediv__(self, other: object) -> Float:
        result = int.__rtruediv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return Float._new(self, result)  # type: ignore[arg-type]

    def __truediv__(self, other: object) -> Float:
        result = int.__truediv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return Float._new(self, result)  # type: ignore[arg-type]


class Float(Item, _CustomFloat):
    """
    A float literal.
    """

    def __new__(cls, value: float, trivia: Trivia, raw: str) -> Float:
        return float.__new__(cls, value)

    def __init__(self, value: float, trivia: Trivia, raw: str) -> None:
        super().__init__(trivia)
        self._original = value
        self._raw = raw
        self._sign = False

        if re.match(r"^[+\-].+$", raw):
            self._sign = True

    def unwrap(self) -> float:
        return self._original

    __float__ = unwrap

    def __hash__(self) -> int:
        return hash(self.unwrap())

    @property
    def discriminant(self) -> int:
        return 3

    @property
    def value(self) -> float:
        """The wrapped float value"""
        return self

    def as_string(self) -> str:
        return self._raw

    def _new(self, result: float) -> Float:
        raw = str(result)

        if self._sign and result >= 0:
            raw = f"+{raw}"

        return Float(result, self._trivia, raw)

    def _getstate(self, protocol: int = 3) -> tuple[float, Trivia, str]:
        return float(self), self._trivia, self._raw

    # float methods — explicit typed wrappers
    def __abs__(self) -> Float:
        return self._new(float.__abs__(self))

    def __add__(self, other: object) -> Float:
        result = float.__add__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    __eq__ = float.__eq__

    def __floordiv__(self, other: object) -> Float:
        result = float.__floordiv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    __le__ = float.__le__
    __lt__ = float.__lt__

    def __mod__(self, other: object) -> Float:
        result = float.__mod__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __mul__(self, other: object) -> Float:
        result = float.__mul__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __neg__(self) -> Float:
        return self._new(float.__neg__(self))

    def __pos__(self) -> Float:
        return self._new(float.__pos__(self))

    def __pow__(self, other: object, mod: None = None) -> Float:
        result = float.__pow__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[no-any-return]
        return self._new(result)

    def __radd__(self, other: object) -> Float:
        result = float.__radd__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rfloordiv__(self, other: object) -> Float:
        result = float.__rfloordiv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rmod__(self, other: object) -> Float:
        result = float.__rmod__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rmul__(self, other: object) -> Float:
        result = float.__rmul__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __round__(self, ndigits: int = 0) -> Float:  # type: ignore[override]
        return self._new(float.__round__(self, ndigits))

    def __rpow__(self, other: object, mod: None = None) -> Float:
        result = float.__rpow__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[no-any-return]
        return self._new(result)

    def __rtruediv__(self, other: object) -> Float:
        result = float.__rtruediv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __truediv__(self, other: object) -> Float:
        result = float.__truediv__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __sub__(self, other: object) -> Float:
        result = float.__sub__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    def __rsub__(self, other: object) -> Float:
        result = float.__rsub__(self, other)  # type: ignore[operator]
        if result is NotImplemented:
            return result  # type: ignore[return-value]
        return self._new(result)

    __trunc__ = float.__trunc__
    __ceil__ = float.__ceil__
    __floor__ = float.__floor__


class Bool(Item):
    """
    A boolean literal.
    """

    def __init__(self, t: int | BoolType, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._value = bool(t)

    def unwrap(self) -> bool:
        return bool(self)

    @property
    def discriminant(self) -> int:
        return 4

    @property
    def value(self) -> bool:
        """The wrapped boolean value"""
        return self._value

    def as_string(self) -> str:
        return str(self._value).lower()

    def _getstate(self, protocol: int = 3) -> tuple[bool, Trivia]:
        return self._value, self._trivia

    def __bool__(self) -> bool:
        return self._value

    __nonzero__ = __bool__

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, bool):
            return NotImplemented

        return other == self._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __repr__(self) -> str:
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
        tzinfo: tzinfo | None,
        trivia: Trivia | None = None,
        raw: str | None = None,
        **kwargs: object,
    ) -> DateTime:
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
        tzinfo: tzinfo | None,
        trivia: Trivia | None = None,
        raw: str | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(trivia or Trivia())

        self._raw = raw or self.isoformat()

    def unwrap(self) -> datetime:
        (
            year,
            month,
            day,
            hour,
            minute,
            second,
            microsecond,
            tzinfo,
            _,
            _,
        ) = self._getstate()
        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo)

    @property
    def discriminant(self) -> int:
        return 5

    @property
    def value(self) -> datetime:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other: timedelta) -> DateTime:
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

    @overload  # type: ignore[override]
    def __sub__(self, other: timedelta) -> DateTime: ...

    @overload
    def __sub__(self, other: datetime) -> timedelta: ...

    def __sub__(self, other: timedelta | datetime) -> DateTime | timedelta:
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
            result = super().__sub__(other)  # type: ignore[operator]

        if isinstance(result, datetime):
            result = self._new(result)

        return result

    def replace(self, *args: object, **kwargs: object) -> DateTime:
        return self._new(super().replace(*args, **kwargs))  # type: ignore[arg-type]

    def astimezone(self, tz: tzinfo) -> DateTime:  # type: ignore[override]
        result = super().astimezone(tz)
        if PY38:
            return result
        return self._new(result)

    def _new(self, result: datetime) -> DateTime:
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

    def _getstate(
        self, protocol: int = 3
    ) -> tuple[int, int, int, int, int, int, int, tzinfo | None, Trivia, str]:
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

    def __new__(
        cls,
        year: int,
        month: int,
        day: int,
        trivia: Trivia | None = None,
        raw: str = "",
    ) -> Date:
        return date.__new__(cls, year, month, day)

    def __init__(
        self,
        year: int,
        month: int,
        day: int,
        trivia: Trivia | None = None,
        raw: str = "",
    ) -> None:
        super().__init__(trivia or Trivia())

        self._raw = raw

    def unwrap(self) -> date:
        (year, month, day, _, _) = self._getstate()
        return date(year, month, day)

    @property
    def discriminant(self) -> int:
        return 6

    @property
    def value(self) -> date:
        return self

    def as_string(self) -> str:
        return self._raw

    def __add__(self, other: timedelta) -> Date:
        if PY38:
            result = date(self.year, self.month, self.day).__add__(other)
        else:
            result = super().__add__(other)

        return self._new(result)

    @overload  # type: ignore[override]
    def __sub__(self, other: timedelta) -> Date: ...

    @overload
    def __sub__(self, other: date) -> timedelta: ...

    def __sub__(self, other: timedelta | date) -> Date | timedelta:
        if PY38:
            result = date(self.year, self.month, self.day).__sub__(other)
        else:
            result = super().__sub__(other)  # type: ignore[operator]

        if isinstance(result, date):
            result = self._new(result)

        return result

    def replace(self, *args: object, **kwargs: object) -> Date:
        return self._new(super().replace(*args, **kwargs))  # type: ignore[arg-type]

    def _new(self, result: date) -> Date:
        raw = result.isoformat()

        return Date(result.year, result.month, result.day, self._trivia, raw)

    def _getstate(self, protocol: int = 3) -> tuple[int, int, int, Trivia, str]:
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
        tzinfo: tzinfo | None,
        trivia: Trivia | None = None,
        raw: str = "",
    ) -> Time:
        return time.__new__(cls, hour, minute, second, microsecond, tzinfo)

    def __init__(
        self,
        hour: int,
        minute: int,
        second: int,
        microsecond: int,
        tzinfo: tzinfo | None,
        trivia: Trivia | None = None,
        raw: str = "",
    ) -> None:
        super().__init__(trivia or Trivia())

        self._raw = raw

    def unwrap(self) -> time:
        (hour, minute, second, microsecond, tzinfo, _, _) = self._getstate()
        return time(hour, minute, second, microsecond, tzinfo)

    @property
    def discriminant(self) -> int:
        return 7

    @property
    def value(self) -> time:
        return self

    def as_string(self) -> str:
        return self._raw

    def replace(self, *args: object, **kwargs: object) -> Time:
        return self._new(super().replace(*args, **kwargs))  # type: ignore[arg-type]

    def _new(self, result: time) -> Time:
        raw = result.isoformat()

        return Time(
            result.hour,
            result.minute,
            result.second,
            result.microsecond,
            result.tzinfo,
            self._trivia,
            raw,
        )

    def _getstate(
        self, protocol: int = 3
    ) -> tuple[int, int, int, int, tzinfo | None, Trivia, str]:
        return (
            self.hour,
            self.minute,
            self.second,
            self.microsecond,
            self.tzinfo,
            self._trivia,
            self._raw,
        )


class _ArrayItemGroup:
    __slots__ = ("comma", "comment", "indent", "value")

    def __init__(
        self,
        value: Item | None = None,
        indent: Whitespace | None = None,
        comma: Whitespace | None = None,
        comment: Comment | None = None,
    ) -> None:
        self.value = value
        self.indent = indent
        self.comma = comma
        self.comment = comment

    def __iter__(self) -> Iterator[Item]:
        return (
            x
            for x in (self.indent, self.value, self.comma, self.comment)
            if x is not None
        )

    def __repr__(self) -> str:
        return repr(tuple(self))

    def is_whitespace(self) -> bool:
        return self.value is None and self.comment is None

    def __bool__(self) -> bool:
        try:
            next(iter(self))
        except StopIteration:
            return False
        return True


class Array(Item, _CustomList):  # type: ignore[type-arg]
    """
    An array literal
    """

    def __init__(
        self, value: list[Item], trivia: Trivia, multiline: bool = False
    ) -> None:
        super().__init__(trivia)
        list.__init__(
            self,
            [v for v in value if not isinstance(v, (Whitespace, Comment, Null))],
        )
        self._index_map: dict[int, int] = {}
        self._value = self._group_values(value)
        self._multiline = multiline
        self._reindex()

    def _group_values(self, value: list[Item]) -> list[_ArrayItemGroup]:
        """Group the values into (indent, value, comma, comment) tuples"""
        groups = []
        this_group = _ArrayItemGroup()
        start_new_group = False
        for item in value:
            if isinstance(item, Whitespace):
                if "," not in item.s or start_new_group:
                    groups.append(this_group)
                    this_group = _ArrayItemGroup(indent=item)
                    start_new_group = False
                else:
                    if this_group.value is None:
                        # when comma is met and no value is provided, add a dummy Null
                        this_group.value = Null()
                    this_group.comma = item
            elif isinstance(item, Comment):
                if this_group.value is None:
                    this_group.value = Null()
                this_group.comment = item
                # Comments are the last item in a group.
                start_new_group = True
            elif this_group.value is None:
                this_group.value = item
            else:
                groups.append(this_group)
                this_group = _ArrayItemGroup(value=item)
        groups.append(this_group)
        return [group for group in groups if group]

    def unwrap(self) -> list[Any]:
        unwrapped = []
        for v in self:
            if hasattr(v, "unwrap"):
                unwrapped.append(v.unwrap())
            else:
                unwrapped.append(v)
        return unwrapped

    @property
    def discriminant(self) -> int:
        return 8

    @property
    def value(self) -> list[Item]:
        return self

    def _iter_items(self) -> Iterator[Item]:
        for v in self._value:
            yield from v

    def multiline(self, multiline: bool) -> Array:
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
            return f"[{''.join(v.as_string() for v in self._iter_items())}]"

        s = "[\n"
        s += "".join(
            self.trivia.indent
            + " " * 4
            + v.value.as_string()
            + ("," if not isinstance(v.value, Null) else "")
            + (v.comment.as_string() if v.comment is not None else "")
            + "\n"
            for v in self._value
            if v.value is not None
        )
        s += self.trivia.indent + "]"

        return s

    def _reindex(self) -> None:
        self._index_map.clear()
        index = 0
        for i, v in enumerate(self._value):
            if v.value is None or isinstance(v.value, Null):
                continue
            self._index_map[index] = i
            index += 1

    def add_line(
        self,
        *items: Any,
        indent: str = "    ",
        comment: str | None = None,
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
        new_values: list[Item] = []
        first_indent = f"\n{indent}" if newline else indent
        if first_indent:
            new_values.append(Whitespace(first_indent))
        whitespace = ""
        data_values = []
        for i, el in enumerate(items):
            it = item(el, _parent=self)
            if isinstance(it, Comment) or (add_comma and isinstance(el, Whitespace)):
                raise ValueError(f"item type {type(it)} is not allowed in add_line")
            if not isinstance(it, Whitespace):
                if whitespace:
                    new_values.append(Whitespace(whitespace))
                    whitespace = ""
                new_values.append(it)
                data_values.append(it.value)
                if add_comma:
                    new_values.append(Whitespace(","))
                    if i != len(items) - 1:
                        new_values.append(Whitespace(" "))
            elif "," not in it.s:
                whitespace += it.s
            else:
                new_values.append(it)
        if whitespace:
            new_values.append(Whitespace(whitespace))
        if comment:
            indent = " " if items else ""
            new_values.append(
                Comment(Trivia(indent=indent, comment=f"# {comment}", trail=""))
            )
        list.extend(self, data_values)
        if len(self._value) > 0:
            last_item = self._value[-1]
            last_value_item = next(
                (
                    v
                    for v in self._value[::-1]
                    if v.value is not None and not isinstance(v.value, Null)
                ),
                None,
            )
            if last_value_item is not None:
                last_value_item.comma = Whitespace(",")
            if last_item.is_whitespace():
                self._value[-1:-1] = self._group_values(new_values)
            else:
                self._value.extend(self._group_values(new_values))
        else:
            self._value.extend(self._group_values(new_values))
        self._reindex()

    def clear(self) -> None:
        """Clear the array."""
        list.clear(self)
        self._index_map.clear()
        self._value.clear()

    def __len__(self) -> int:
        return list.__len__(self)

    def item(self, index: int) -> Item:
        return list.__getitem__(self, index)  # type: ignore[no-any-return]

    def __getitem__(self, key: int | slice) -> Any:  # type: ignore[override]
        return list.__getitem__(self, key)

    def __setitem__(self, key: int | slice, value: Any) -> None:  # type: ignore[override]
        it = item(value, _parent=self)
        list.__setitem__(self, key, it)
        if isinstance(key, slice):
            raise ValueError("slice assignment is not supported")
        if key < 0:
            key += len(self)
        self._value[self._index_map[key]].value = it

    def insert(self, pos: int, value: Any) -> None:  # type: ignore[override]
        it = item(value, _parent=self)
        length = len(self)
        if not isinstance(it, (Comment, Whitespace)):
            list.insert(self, pos, it)
        if pos < 0:
            pos += length
            if pos < 0:
                pos = 0

        idx = 0  # insert position of the self._value list
        default_indent = " "
        if pos < length:
            try:
                idx = self._index_map[pos]
            except KeyError as e:
                raise IndexError("list index out of range") from e
        else:
            idx = len(self._value)
            if idx >= 1 and self._value[idx - 1].is_whitespace():
                # The last item is a pure whitespace(\n ), insert before it
                idx -= 1
                _indent = self._value[idx].indent
                if _indent is not None and "\n" in _indent.s:
                    default_indent = "\n    "
        indent: Whitespace | None = None
        comma: Whitespace | None = Whitespace(",") if pos < length else None
        if idx < len(self._value) and not self._value[idx].is_whitespace():
            # Prefer to copy the indentation from the item after
            indent = self._value[idx].indent
        if idx > 0:
            last_item = self._value[idx - 1]
            if indent is None:
                indent = last_item.indent
            if not isinstance(last_item.value, Null) and "\n" in default_indent:
                # Copy the comma from the last item if 1) it contains a value and
                # 2) the array is multiline
                comma = last_item.comma
            if last_item.comma is None and not isinstance(last_item.value, Null):
                # Add comma to the last item to separate it from the following items.
                last_item.comma = Whitespace(",")
        if indent is None and (idx > 0 or "\n" in default_indent):
            # apply default indent if it isn't the first item or the array is multiline.
            indent = Whitespace(default_indent)
        new_item = _ArrayItemGroup(value=it, indent=indent, comma=comma)
        self._value.insert(idx, new_item)
        self._reindex()

    def __delitem__(self, key: int | slice) -> None:  # type: ignore[override]
        length = len(self)
        list.__delitem__(self, key)

        if isinstance(key, slice):
            indices_to_remove = list(
                range(key.start or 0, key.stop or length, key.step or 1)
            )
        else:
            indices_to_remove = [length + key if key < 0 else key]
        for i in sorted(indices_to_remove, reverse=True):
            try:
                idx = self._index_map[i]
            except KeyError as e:
                if not isinstance(key, slice):
                    raise IndexError("list index out of range") from e
            else:
                group_rm = self._value[idx]
                del self._value[idx]
                if (
                    idx == 0
                    and len(self._value) > 0
                    and (ind := self._value[idx].indent)
                    and "\n" not in ind.s
                ):
                    # Remove the indentation of the first item if not newline
                    self._value[idx].indent = None
                comma_in_indent = (
                    group_rm.indent is not None and "," in group_rm.indent.s
                )
                comma_in_comma = group_rm.comma is not None and "," in group_rm.comma.s
                if comma_in_indent and comma_in_comma:
                    # Removed group had both commas. Add one to the next group.
                    group = self._value[idx] if len(self._value) > idx else None
                    if group is not None:
                        if group.indent is None:
                            group.indent = Whitespace(",")
                        elif "," not in group.indent.s:
                            # Insert the comma after the newline
                            try:
                                newline_index = group.indent.s.index("\n")
                                group.indent._s = (
                                    group.indent.s[: newline_index + 1]
                                    + ","
                                    + group.indent.s[newline_index + 1 :]
                                )
                            except ValueError:
                                group.indent._s = "," + group.indent.s
                elif not comma_in_indent and not comma_in_comma:
                    # Removed group had no commas. Remove the next comma found.
                    for j in range(idx, len(self._value)):
                        group = self._value[j]
                        if group.indent is not None and "," in group.indent.s:
                            group.indent._s = group.indent.s.replace(",", "", 1)
                            break
                if group_rm.indent is not None and "\n" in group_rm.indent.s:
                    # Restore the removed group's newline onto the next group
                    # if the next group does not have a newline.
                    # i.e. the two were on the same line
                    group = self._value[idx] if len(self._value) > idx else None
                    if group is not None and (
                        group.indent is None or "\n" not in group.indent.s
                    ):
                        group.indent = group_rm.indent

        if len(self._value) > 0:
            v = self._value[-1]
            if not v.is_whitespace():
                # remove the comma of the last item
                v.comma = None

        self._reindex()

    def _getstate(self, protocol: int = 3) -> tuple[list[Item], Trivia, bool]:
        return list(self._iter_items()), self._trivia, self._multiline


class AbstractTable(Item, _CustomDict):  # type: ignore[type-arg]
    """Common behaviour of both :class:`Table` and :class:`InlineTable`"""

    def __init__(self, value: container.Container, trivia: Trivia):
        Item.__init__(self, trivia)

        self._value = value

        for k, v in self._value.body:
            if k is not None:
                dict.__setitem__(self, k.key, v)

    def unwrap(self) -> dict[str, Any]:
        unwrapped = {}
        for k, v in self.items():
            if isinstance(k, Key):
                k = k.key
            if hasattr(v, "unwrap"):
                v = v.unwrap()
            unwrapped[k] = v

        return unwrapped

    @property
    def value(self) -> container.Container:
        return self._value

    @overload
    def append(self: AT, key: None, value: Comment | Whitespace) -> AT: ...

    @overload
    def append(self: AT, key: Key | str, value: Any) -> AT: ...

    def append(self: AT, key: Key | str | None, value: Any) -> AT:
        raise NotImplementedError

    @overload
    def add(self: AT, key: Comment | Whitespace) -> AT: ...

    @overload
    def add(self: AT, key: Key | str, value: Any = ...) -> AT: ...

    def add(
        self: AT, key: Key | str | Comment | Whitespace, value: Any | None = None
    ) -> AT:
        if value is None:
            if not isinstance(key, (Comment, Whitespace)):
                msg = "Non comment/whitespace items must have an associated key"
                raise ValueError(msg)

            return self.append(None, key)

        if isinstance(key, (Comment, Whitespace)):
            raise ValueError("Comment/Whitespace keys must not have a value")

        return self.append(key, value)

    def remove(self: AT, key: Key | str) -> AT:
        self._value.remove(key)

        if isinstance(key, Key):
            key = key.key

        if key is not None:
            dict.__delitem__(self, key)

        return self

    def item(self, key: Key | str) -> Item | OutOfOrderTableProxy:
        return self._value.item(key)

    def setdefault(self, key: Key | str, default: Any) -> Any:  # type: ignore[override]
        super().setdefault(key, default)
        return self[key]

    def __str__(self) -> str:
        return str(self.value)

    def copy(self: AT) -> AT:
        return copy.copy(self)

    def __repr__(self) -> str:
        return repr(self.value)

    def __iter__(self) -> Iterator[str]:
        return iter(self._value)

    def __len__(self) -> int:
        return len(self._value)

    def __delitem__(self, key: Key | str) -> None:  # type: ignore[override]
        self.remove(key)

    def __getitem__(self, key: Key | str) -> Any:  # type: ignore[override]
        return self._value[key]

    def __setitem__(self, key: Key | str, value: Any) -> None:  # type: ignore[override]
        if not isinstance(value, Item):
            value = item(value, _parent=self)

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
        value: container.Container,
        trivia: Trivia,
        is_aot_element: bool,
        is_super_table: bool | None = None,
        name: str | None = None,
        display_name: str | None = None,
    ) -> None:
        super().__init__(value, trivia)

        self.name = name
        self.display_name = display_name
        self._is_aot_element = is_aot_element
        self._is_super_table = is_super_table

    @property
    def discriminant(self) -> int:
        return 9

    def __copy__(self) -> Table:
        return type(self)(
            self._value.copy(),
            self._trivia.copy(),
            self._is_aot_element,
            self._is_super_table,
            self.name,
            self.display_name,
        )

    def append(self, key: Key | str | None, _item: Any) -> Table:
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item, _parent=self)

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

    def raw_append(self, key: Key | str | None, _item: Any) -> Table:
        """Similar to :meth:`append` but does not copy indentation."""
        if not isinstance(_item, Item):
            _item = item(_item)

        self._value.append(key, _item, validate=False)

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
        if self._is_super_table is not None:
            return self._is_super_table
        if not self:
            return False
        # If the table has children and all children are tables, then it is a super table.
        for k, child in self.items():
            if not isinstance(k, Key):
                k = SingleKey(k)
            index = self.value._map[k]
            if isinstance(index, tuple):
                return False
            real_key = self.value.body[index][0]
            if (
                not isinstance(child, (Table, AoT))
                or real_key is None
                or real_key.is_dotted()
            ):
                return False
        return True

    def as_string(self) -> str:
        return self._value.as_string()

    # Helpers

    def indent(self, indent: int) -> Table:
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

    def invalidate_display_name(self) -> None:
        """Call ``invalidate_display_name`` on the contained tables"""
        self.display_name = None

        for child in self.values():
            if hasattr(child, "invalidate_display_name"):
                child.invalidate_display_name()

    def _getstate(
        self, protocol: int = 3
    ) -> tuple[container.Container, Trivia, bool, bool | None, str | None, str | None]:
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
        self, value: container.Container, trivia: Trivia, new: bool = False
    ) -> None:
        super().__init__(value, trivia)

        self._new = new

    @property
    def discriminant(self) -> int:
        return 10

    def append(self, key: Key | str | None, _item: Any) -> InlineTable:
        """
        Appends a (key, item) to the table.
        """
        if not isinstance(_item, Item):
            _item = item(_item, _parent=self)

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
        emitted_key = False
        has_explicit_commas = any(
            k is None and isinstance(v, Whitespace) and "," in v.s
            for k, v in self._value.body
        )
        last_item_idx = next(
            (
                i
                for i in range(len(self._value.body) - 1, -1, -1)
                if self._value.body[i][0] is not None
            ),
            None,
        )
        for i, (k, v) in enumerate(self._value.body):
            if k is None:
                if isinstance(v, Whitespace) and "," in v.s:
                    if not emitted_key:
                        buf += v.as_string().replace(",", "", 1)
                        continue

                    has_following_null = any(
                        isinstance(next_v, Null)
                        for _, next_v in self._value.body[i + 1 :]
                    )
                    has_following_key = any(
                        next_k is not None for next_k, _ in self._value.body[i + 1 :]
                    )
                    if has_following_null and not has_following_key:
                        buf += v.as_string().replace(",", "", 1)
                        continue

                if i == len(self._value.body) - 1:
                    if self._new:
                        buf = buf.rstrip(", ")
                    elif not has_explicit_commas or "," in v.as_string():
                        buf = buf.rstrip(",")

                buf += v.as_string()

                continue

            v_trivia_trail = v.trivia.trail.replace("\n", "")
            buf += (
                f"{v.trivia.indent}"
                f"{k.as_string() + ('.' if k.is_dotted() else '')}"
                f"{k.sep}"
                f"{v.as_string()}"
                f"{v.trivia.comment}"
                f"{v_trivia_trail}"
            )
            emitted_key = True

            if (
                not has_explicit_commas
                and last_item_idx is not None
                and i < last_item_idx
            ):
                buf += ","
                if self._new:
                    buf += " "

        buf += "}"

        return buf

    def __setitem__(self, key: Key | str, value: Any) -> None:  # type: ignore[override]
        if hasattr(value, "trivia") and value.trivia.comment:
            value.trivia.comment = ""
        super().__setitem__(key, value)

    def __copy__(self) -> InlineTable:
        return type(self)(self._value.copy(), self._trivia.copy(), self._new)

    def _getstate(self, protocol: int = 3) -> tuple[container.Container, Trivia]:
        return (self._value, self._trivia)


class String(str, Item):  # type: ignore[misc]
    """
    A string literal.
    """

    def __new__(
        cls, t: StringType, value: str, original: str, trivia: Trivia
    ) -> String:
        return super().__new__(cls, value)

    def __init__(self, t: StringType, _: str, original: str, trivia: Trivia) -> None:
        super().__init__(trivia)

        self._t = t
        self._original = original

    def unwrap(self) -> str:
        return str(self)

    @property
    def discriminant(self) -> int:
        return 11

    @property
    def value(self) -> str:
        return self

    def as_string(self) -> str:
        return f"{self._t.value}{decode(self._original)}{self._t.value}"

    @property
    def type(self) -> StringType:
        return self._t

    def __add__(self, other: str) -> String:
        result = super().__add__(other)
        original = self._original + getattr(other, "_original", other)

        return self._new(result, original)

    def _new(self, result: str, original: str) -> String:
        return String(self._t, result, original, self._trivia)

    def _getstate(self, protocol: int = 3) -> tuple[StringType, str, str, Trivia]:
        return self._t, str(self), self._original, self._trivia

    @classmethod
    def from_raw(
        cls, value: str, type_: StringType = StringType.SLB, escape: bool = True
    ) -> String:
        value = decode(value)

        invalid = type_.invalid_sequences
        if any(c in value for c in invalid):
            raise InvalidStringError(value, invalid, type_.value)

        escaped = type_.escaped_sequences
        string_value = escape_string(value, escaped) if escape and escaped else value

        return cls(type_, decode(value), string_value, Trivia())


class AoT(Item, _CustomList):  # type: ignore[type-arg]
    """
    An array of table literal
    """

    def __init__(
        self, body: list[Table], name: str | None = None, parsed: bool = False
    ) -> None:
        self.name = name
        self._body: list[Table] = []
        self._parsed = parsed

        super().__init__(Trivia(trail=""))

        for table in body:
            self.append(table)

    def unwrap(self) -> list[dict[str, Any]]:
        unwrapped = []
        for t in self._body:
            if hasattr(t, "unwrap"):
                unwrapped.append(t.unwrap())
            else:
                unwrapped.append(t)
        return unwrapped

    @property
    def body(self) -> list[Table]:
        return self._body

    @property
    def discriminant(self) -> int:
        return 12

    @property
    def value(self) -> list[dict[str, Any]]:
        return [v.value for v in self._body]

    def __len__(self) -> int:
        return len(self._body)

    @overload  # type: ignore[override]
    def __getitem__(self, key: slice) -> list[Table]: ...

    @overload
    def __getitem__(self, key: int) -> Table: ...

    def __getitem__(self, key: int | slice) -> Table | list[Table]:
        return self._body[key]

    def __setitem__(self, key: slice | int, value: Any) -> None:  # type: ignore[override]
        self._body[key] = item(value, _parent=self)

    def __delitem__(self, key: slice | int) -> None:  # type: ignore[override]
        del self._body[key]
        list.__delitem__(self, key)

    def insert(self, index: int, value: dict[str, Any]) -> None:  # type: ignore[override]
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

    def invalidate_display_name(self) -> None:
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

    def _getstate(self, protocol: int = 3) -> tuple[list[Table], str | None, bool]:
        return self._body, self.name, self._parsed


class Null(Item):
    """
    A null item.
    """

    def __init__(self) -> None:
        super().__init__(Trivia(trail=""))

    def unwrap(self) -> None:
        return None

    @property
    def discriminant(self) -> int:
        return -1

    @property
    def value(self) -> None:
        return None

    def as_string(self) -> str:
        return ""

    def _getstate(self, protocol: int = 3) -> tuple[()]:
        return ()
