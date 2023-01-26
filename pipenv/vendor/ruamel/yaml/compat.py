# coding: utf-8

# partially from package six by Benjamin Peterson

import sys
import os
import io
import traceback
from abc import abstractmethod
import collections.abc


# fmt: off
if False:  # MYPY
    from typing import Any, Dict, Optional, List, Union, BinaryIO, IO, Text, Tuple  # NOQA
    from typing import Optional  # NOQA
# fmt: on

_DEFAULT_YAML_VERSION = (1, 2)

try:
    from collections import OrderedDict
except ImportError:
    from ordereddict import OrderedDict  # type: ignore

    # to get the right name import ... as ordereddict doesn't do that


class ordereddict(OrderedDict):  # type: ignore
    if not hasattr(OrderedDict, 'insert'):

        def insert(self, pos, key, value):
            # type: (int, Any, Any) -> None
            if pos >= len(self):
                self[key] = value
                return
            od = ordereddict()
            od.update(self)
            for k in od:
                del self[k]
            for index, old_key in enumerate(od):
                if pos == index:
                    self[key] = value
                self[old_key] = od[old_key]


PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3


# replace with f-strings when 3.5 support is dropped
# ft = '42'
# assert _F('abc {ft!r}', ft=ft) == 'abc %r' % ft
# 'abc %r' % ft -> _F('abc {ft!r}' -> f'abc {ft!r}'
def _F(s, *superfluous, **kw):
    # type: (Any, Any, Any) -> Any
    if superfluous:
        raise TypeError
    return s.format(**kw)


StringIO = io.StringIO
BytesIO = io.BytesIO

if False:  # MYPY
    # StreamType = Union[BinaryIO, IO[str], IO[unicode],  StringIO]
    # StreamType = Union[BinaryIO, IO[str], StringIO]  # type: ignore
    StreamType = Any

    StreamTextType = StreamType  # Union[Text, StreamType]
    VersionType = Union[List[int], str, Tuple[int, int]]

builtins_module = 'builtins'


def with_metaclass(meta, *bases):
    # type: (Any, Any) -> Any
    """Create a base class with a metaclass."""
    return meta('NewBase', bases, {})


DBG_TOKEN = 1
DBG_EVENT = 2
DBG_NODE = 4


_debug = None  # type: Optional[int]
if 'RUAMELDEBUG' in os.environ:
    _debugx = os.environ.get('RUAMELDEBUG')
    if _debugx is None:
        _debug = 0
    else:
        _debug = int(_debugx)


if bool(_debug):

    class ObjectCounter:
        def __init__(self):
            # type: () -> None
            self.map = {}  # type: Dict[Any, Any]

        def __call__(self, k):
            # type: (Any) -> None
            self.map[k] = self.map.get(k, 0) + 1

        def dump(self):
            # type: () -> None
            for k in sorted(self.map):
                sys.stdout.write('{} -> {}'.format(k, self.map[k]))

    object_counter = ObjectCounter()


# used from yaml util when testing
def dbg(val=None):
    # type: (Any) -> Any
    global _debug
    if _debug is None:
        # set to true or false
        _debugx = os.environ.get('YAMLDEBUG')
        if _debugx is None:
            _debug = 0
        else:
            _debug = int(_debugx)
    if val is None:
        return _debug
    return _debug & val


class Nprint:
    def __init__(self, file_name=None):
        # type: (Any) -> None
        self._max_print = None  # type: Any
        self._count = None  # type: Any
        self._file_name = file_name

    def __call__(self, *args, **kw):
        # type: (Any, Any) -> None
        if not bool(_debug):
            return
        out = sys.stdout if self._file_name is None else open(self._file_name, 'a')
        dbgprint = print  # to fool checking for print statements by dv utility
        kw1 = kw.copy()
        kw1['file'] = out
        dbgprint(*args, **kw1)
        out.flush()
        if self._max_print is not None:
            if self._count is None:
                self._count = self._max_print
            self._count -= 1
            if self._count == 0:
                dbgprint('forced exit\n')
                traceback.print_stack()
                out.flush()
                sys.exit(0)
        if self._file_name:
            out.close()

    def set_max_print(self, i):
        # type: (int) -> None
        self._max_print = i
        self._count = None

    def fp(self, mode='a'):
        # type: (str) -> Any
        out = sys.stdout if self._file_name is None else open(self._file_name, mode)
        return out


nprint = Nprint()
nprintf = Nprint('/var/tmp/ruamel.yaml.log')

# char checkers following production rules


def check_namespace_char(ch):
    # type: (Any) -> bool
    if '\x21' <= ch <= '\x7E':  # ! to ~
        return True
    if '\xA0' <= ch <= '\uD7FF':
        return True
    if ('\uE000' <= ch <= '\uFFFD') and ch != '\uFEFF':  # excl. byte order mark
        return True
    if '\U00010000' <= ch <= '\U0010FFFF':
        return True
    return False


def check_anchorname_char(ch):
    # type: (Any) -> bool
    if ch in ',[]{}':
        return False
    return check_namespace_char(ch)


def version_tnf(t1, t2=None):
    # type: (Any, Any) -> Any
    """
    return True if ruamel version_info < t1, None if t2 is specified and bigger else False
    """
    from pipenv.vendor.ruamel.yaml import version_info  # NOQA

    if version_info < t1:
        return True
    if t2 is not None and version_info < t2:
        return None
    return False


class MutableSliceableSequence(collections.abc.MutableSequence):  # type: ignore
    __slots__ = ()

    def __getitem__(self, index):
        # type: (Any) -> Any
        if not isinstance(index, slice):
            return self.__getsingleitem__(index)
        return type(self)([self[i] for i in range(*index.indices(len(self)))])  # type: ignore

    def __setitem__(self, index, value):
        # type: (Any, Any) -> None
        if not isinstance(index, slice):
            return self.__setsingleitem__(index, value)
        assert iter(value)
        # nprint(index.start, index.stop, index.step, index.indices(len(self)))
        if index.step is None:
            del self[index.start : index.stop]
            for elem in reversed(value):
                self.insert(0 if index.start is None else index.start, elem)
        else:
            range_parms = index.indices(len(self))
            nr_assigned_items = (range_parms[1] - range_parms[0] - 1) // range_parms[2] + 1
            # need to test before changing, in case TypeError is caught
            if nr_assigned_items < len(value):
                raise TypeError(
                    'too many elements in value {} < {}'.format(nr_assigned_items, len(value))
                )
            elif nr_assigned_items > len(value):
                raise TypeError(
                    'not enough elements in value {} > {}'.format(
                        nr_assigned_items, len(value)
                    )
                )
            for idx, i in enumerate(range(*range_parms)):
                self[i] = value[idx]

    def __delitem__(self, index):
        # type: (Any) -> None
        if not isinstance(index, slice):
            return self.__delsingleitem__(index)
        # nprint(index.start, index.stop, index.step, index.indices(len(self)))
        for i in reversed(range(*index.indices(len(self)))):
            del self[i]

    @abstractmethod
    def __getsingleitem__(self, index):
        # type: (Any) -> Any
        raise IndexError

    @abstractmethod
    def __setsingleitem__(self, index, value):
        # type: (Any, Any) -> None
        raise IndexError

    @abstractmethod
    def __delsingleitem__(self, index):
        # type: (Any) -> None
        raise IndexError
