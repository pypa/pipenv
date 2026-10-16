from __future__ import annotations

import collections.abc
import datetime
import os
import typing


__all__ = ['ConfigSettings', 'Distribution', 'JSONValue', 'StrPath', 'SubprocessRunner', 'TOMLValue']

ConfigSettings = collections.abc.Mapping[str, str | collections.abc.Sequence[str]]
Distribution = typing.Literal['sdist', 'wheel', 'editable']

StrPath = str | os.PathLike[str]

# A decoded JSON value, as produced by ``json.load``. Uses the covariant ``Sequence``/``Mapping``
# so concrete literals (e.g. ``str | list[str]``) are also assignable to it.
JSONValue: typing.TypeAlias = (
    str | int | float | bool | collections.abc.Sequence['JSONValue'] | collections.abc.Mapping[str, 'JSONValue'] | None
)

# A value as produced by ``tomllib`` when parsing ``pyproject.toml``. Uses the covariant
# ``Sequence``/``Mapping`` so concrete literals (e.g. ``dict[str, list[str]]``) are assignable.
TOMLValue: typing.TypeAlias = (
    str
    | int
    | float
    | bool
    | datetime.datetime
    | datetime.date
    | datetime.time
    | collections.abc.Sequence['TOMLValue']
    | collections.abc.Mapping[str, 'TOMLValue']
)

TYPE_CHECKING = False

if TYPE_CHECKING:
    from pipenv.vendor.pyproject_hooks import SubprocessRunner
else:
    SubprocessRunner = collections.abc.Callable[
        [collections.abc.Sequence[str], str | None, collections.abc.Mapping[str, str] | None], None
    ]
