# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import itertools

from copy import copy
from typing import Any
from typing import Optional
from typing import Tuple
from typing import Type

from ._compat import PY2
from ._compat import unicode
from .exceptions import ParseError
from .exceptions import UnexpectedCharError
from .exceptions import UnexpectedEofError
from .toml_char import TOMLChar


class _State:
    def __init__(
        self, source, save_marker=False, restore=False
    ):  # type: (_Source, Optional[bool], Optional[bool]) -> None
        self._source = source
        self._save_marker = save_marker
        self.restore = restore

    def __enter__(self):  # type: () -> None
        # Entering this context manager - save the state
        if PY2:
            # Python 2.7 does not allow to directly copy
            # an iterator, so we have to make tees of the original
            # chars iterator.
            self._source._chars, self._chars = itertools.tee(self._source._chars)
        else:
            self._chars = copy(self._source._chars)
        self._idx = self._source._idx
        self._current = self._source._current
        self._marker = self._source._marker

        return self

    def __exit__(self, exception_type, exception_val, trace):
        # Exiting this context manager - restore the prior state
        if self.restore or exception_type:
            self._source._chars = self._chars
            self._source._idx = self._idx
            self._source._current = self._current
            if self._save_marker:
                self._source._marker = self._marker


class _StateHandler:
    """
    State preserver for the Parser.
    """

    def __init__(self, source):  # type: (Source) -> None
        self._source = source
        self._states = []

    def __call__(self, *args, **kwargs):
        return _State(self._source, *args, **kwargs)

    def __enter__(self):  # type: () -> None
        state = self()
        self._states.append(state)
        return state.__enter__()

    def __exit__(self, exception_type, exception_val, trace):
        state = self._states.pop()
        return state.__exit__(exception_type, exception_val, trace)


class Source(unicode):
    EOF = TOMLChar("\0")

    def __init__(self, _):  # type: (unicode) -> None
        super(Source, self).__init__()

        # Collection of TOMLChars
        self._chars = iter([(i, TOMLChar(c)) for i, c in enumerate(self)])

        self._idx = 0
        self._marker = 0
        self._current = TOMLChar("")

        self._state = _StateHandler(self)

        self.inc()

    def reset(self):
        # initialize both idx and current
        self.inc()

        # reset marker
        self.mark()

    @property
    def state(self):  # type: () -> _StateHandler
        return self._state

    @property
    def idx(self):  # type: () -> int
        return self._idx

    @property
    def current(self):  # type: () -> TOMLChar
        return self._current

    @property
    def marker(self):  # type: () -> int
        return self._marker

    def extract(self):  # type: () -> unicode
        """
        Extracts the value between marker and index
        """
        return self[self._marker : self._idx]

    def inc(self, exception=None):  # type: (Optional[Type[ParseError]]) -> bool
        """
        Increments the parser if the end of the input has not been reached.
        Returns whether or not it was able to advance.
        """
        try:
            self._idx, self._current = next(self._chars)

            return True
        except StopIteration:
            self._idx = len(self)
            self._current = self.EOF
            if exception:
                raise self.parse_error(exception)

            return False

    def inc_n(self, n, exception=None):  # type: (int, Exception) -> bool
        """
        Increments the parser by n characters
        if the end of the input has not been reached.
        """
        for _ in range(n):
            if not self.inc(exception=exception):
                return False

        return True

    def consume(self, chars, min=0, max=-1):
        """
        Consume chars until min/max is satisfied is valid.
        """
        while self.current in chars and max != 0:
            min -= 1
            max -= 1
            if not self.inc():
                break

        # failed to consume minimum number of characters
        if min > 0:
            self.parse_error(UnexpectedCharError)

    def end(self):  # type: () -> bool
        """
        Returns True if the parser has reached the end of the input.
        """
        return self._current is self.EOF

    def mark(self):  # type: () -> None
        """
        Sets the marker to the index's current position
        """
        self._marker = self._idx

    def parse_error(
        self, exception=ParseError, *args
    ):  # type: (Type[ParseError], Any) -> ParseError
        """
        Creates a generic "parse error" at the current position.
        """
        line, col = self._to_linecol()

        return exception(line, col, *args)

    def _to_linecol(self):  # type: () -> Tuple[int, int]
        cur = 0
        for i, line in enumerate(self.splitlines()):
            if cur + len(line) + 1 > self.idx:
                return (i + 1, self.idx - cur)

            cur += len(line) + 1

        return len(self.splitlines()), 0
