# coding: utf-8

import warnings
import textwrap

from typing import Any, Dict, Optional, List, Text  # NOQA


__all__ = [
    'FileMark',
    'StringMark',
    'CommentMark',
    'YAMLError',
    'MarkedYAMLError',
    'ReusedAnchorWarning',
    'UnsafeLoaderWarning',
    'MarkedYAMLWarning',
    'MarkedYAMLFutureWarning',
]


class StreamMark:
    __slots__ = 'name', 'index', 'line', 'column'

    def __init__(self, name: Any, index: int, line: int, column: int) -> None:
        self.name = name
        self.index = index
        self.line = line
        self.column = column

    def __str__(self) -> Any:
        where = f'  in "{self.name!s}", line {self.line + 1:d}, column {self.column + 1:d}'
        return where

    def __eq__(self, other: Any) -> bool:
        if self.line != other.line or self.column != other.column:
            return False
        if self.name != other.name or self.index != other.index:
            return False
        return True

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)


class FileMark(StreamMark):
    __slots__ = ()


class StringMark(StreamMark):
    __slots__ = 'name', 'index', 'line', 'column', 'buffer', 'pointer'

    def __init__(
        self, name: Any, index: int, line: int, column: int, buffer: Any, pointer: Any,
    ) -> None:
        StreamMark.__init__(self, name, index, line, column)
        self.buffer = buffer
        self.pointer = pointer

    def get_snippet(self, indent: int = 4, max_length: int = 75) -> Any:
        if self.buffer is None:  # always False
            return None
        head = ""
        start = self.pointer
        while start > 0 and self.buffer[start - 1] not in '\0\r\n\x85\u2028\u2029':
            start -= 1
            if self.pointer - start > max_length / 2 - 1:
                head = ' ... '
                start += 5
                break
        tail = ""
        end = self.pointer
        while end < len(self.buffer) and self.buffer[end] not in '\0\r\n\x85\u2028\u2029':
            end += 1
            if end - self.pointer > max_length / 2 - 1:
                tail = ' ... '
                end -= 5
                break
        snippet = self.buffer[start:end]
        caret = '^'
        caret = f'^ (line: {self.line + 1})'
        return (
            ' ' * indent
            + head
            + snippet
            + tail
            + '\n'
            + ' ' * (indent + self.pointer - start + len(head))
            + caret
        )

    def __str__(self) -> Any:
        snippet = self.get_snippet()
        where = f'  in "{self.name!s}", line {self.line + 1:d}, column {self.column + 1:d}'
        if snippet is not None:
            where += ':\n' + snippet
        return where

    def __repr__(self) -> Any:
        snippet = self.get_snippet()
        where = f'  in "{self.name!s}", line {self.line + 1:d}, column {self.column + 1:d}'
        if snippet is not None:
            where += ':\n' + snippet
        return where


class CommentMark:
    __slots__ = ('column',)

    def __init__(self, column: Any) -> None:
        self.column = column


class YAMLError(Exception):
    pass


class MarkedYAMLError(YAMLError):
    def __init__(
        self,
        context: Any = None,
        context_mark: Any = None,
        problem: Any = None,
        problem_mark: Any = None,
        note: Any = None,
        warn: Any = None,
    ) -> None:
        self.context = context
        self.context_mark = context_mark
        self.problem = problem
        self.problem_mark = problem_mark
        self.note = note
        # warn is ignored

    def __str__(self) -> Any:
        lines: List[str] = []
        if self.context is not None:
            lines.append(self.context)
        if self.context_mark is not None and (
            self.problem is None
            or self.problem_mark is None
            or self.context_mark.name != self.problem_mark.name
            or self.context_mark.line != self.problem_mark.line
            or self.context_mark.column != self.problem_mark.column
        ):
            lines.append(str(self.context_mark))
        if self.problem is not None:
            lines.append(self.problem)
        if self.problem_mark is not None:
            lines.append(str(self.problem_mark))
        if self.note is not None and self.note:
            note = textwrap.dedent(self.note)
            lines.append(note)
        return '\n'.join(lines)


class YAMLStreamError(Exception):
    pass


class YAMLWarning(Warning):
    pass


class MarkedYAMLWarning(YAMLWarning):
    def __init__(
        self,
        context: Any = None,
        context_mark: Any = None,
        problem: Any = None,
        problem_mark: Any = None,
        note: Any = None,
        warn: Any = None,
    ) -> None:
        self.context = context
        self.context_mark = context_mark
        self.problem = problem
        self.problem_mark = problem_mark
        self.note = note
        self.warn = warn

    def __str__(self) -> Any:
        lines: List[str] = []
        if self.context is not None:
            lines.append(self.context)
        if self.context_mark is not None and (
            self.problem is None
            or self.problem_mark is None
            or self.context_mark.name != self.problem_mark.name
            or self.context_mark.line != self.problem_mark.line
            or self.context_mark.column != self.problem_mark.column
        ):
            lines.append(str(self.context_mark))
        if self.problem is not None:
            lines.append(self.problem)
        if self.problem_mark is not None:
            lines.append(str(self.problem_mark))
        if self.note is not None and self.note:
            note = textwrap.dedent(self.note)
            lines.append(note)
        if self.warn is not None and self.warn:
            warn = textwrap.dedent(self.warn)
            lines.append(warn)
        return '\n'.join(lines)


class ReusedAnchorWarning(YAMLWarning):
    pass


class UnsafeLoaderWarning(YAMLWarning):
    text = """
The default 'Loader' for 'load(stream)' without further arguments can be unsafe.
Use 'load(stream, Loader=ruamel.yaml.Loader)' explicitly if that is OK.
Alternatively include the following in your code:

  import warnings
  warnings.simplefilter('ignore', ruamel.error.UnsafeLoaderWarning)

In most other cases you should consider using 'safe_load(stream)'"""
    pass


warnings.simplefilter('once', UnsafeLoaderWarning)


class MantissaNoDotYAML1_1Warning(YAMLWarning):
    def __init__(self, node: Any, flt_str: Any) -> None:
        self.node = node
        self.flt = flt_str

    def __str__(self) -> Any:
        line = self.node.start_mark.line
        col = self.node.start_mark.column
        return f"""
In YAML 1.1 floating point values should have a dot ('.') in their mantissa.
See the Floating-Point Language-Independent Type for YAML™ Version 1.1 specification
( http://yaml.org/type/float.html ). This dot is not required for JSON nor for YAML 1.2

Correct your float: "{self.flt}" on line: {line}, column: {col}

or alternatively include the following in your code:

  import warnings
  warnings.simplefilter('ignore', ruamel.error.MantissaNoDotYAML1_1Warning)

"""


warnings.simplefilter('once', MantissaNoDotYAML1_1Warning)


class YAMLFutureWarning(Warning):
    pass


class MarkedYAMLFutureWarning(YAMLFutureWarning):
    def __init__(
        self,
        context: Any = None,
        context_mark: Any = None,
        problem: Any = None,
        problem_mark: Any = None,
        note: Any = None,
        warn: Any = None,
    ) -> None:
        self.context = context
        self.context_mark = context_mark
        self.problem = problem
        self.problem_mark = problem_mark
        self.note = note
        self.warn = warn

    def __str__(self) -> Any:
        lines: List[str] = []
        if self.context is not None:
            lines.append(self.context)

        if self.context_mark is not None and (
            self.problem is None
            or self.problem_mark is None
            or self.context_mark.name != self.problem_mark.name
            or self.context_mark.line != self.problem_mark.line
            or self.context_mark.column != self.problem_mark.column
        ):
            lines.append(str(self.context_mark))
        if self.problem is not None:
            lines.append(self.problem)
        if self.problem_mark is not None:
            lines.append(str(self.problem_mark))
        if self.note is not None and self.note:
            note = textwrap.dedent(self.note)
            lines.append(note)
        if self.warn is not None and self.warn:
            warn = textwrap.dedent(self.warn)
            lines.append(warn)
        return '\n'.join(lines)
