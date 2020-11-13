import codecs
import re

from .compat import IS_TYPE_CHECKING, to_text

if IS_TYPE_CHECKING:
    from typing import (  # noqa:F401
        IO, Iterator, Match, NamedTuple, Optional, Pattern, Sequence, Text,
        Tuple
    )


def make_regex(string, extra_flags=0):
    # type: (str, int) -> Pattern[Text]
    return re.compile(to_text(string), re.UNICODE | extra_flags)


_newline = make_regex(r"(\r\n|\n|\r)")
_multiline_whitespace = make_regex(r"\s*", extra_flags=re.MULTILINE)
_whitespace = make_regex(r"[^\S\r\n]*")
_export = make_regex(r"(?:export[^\S\r\n]+)?")
_single_quoted_key = make_regex(r"'([^']+)'")
_unquoted_key = make_regex(r"([^=\#\s]+)")
_equal_sign = make_regex(r"(=[^\S\r\n]*)")
_single_quoted_value = make_regex(r"'((?:\\'|[^'])*)'")
_double_quoted_value = make_regex(r'"((?:\\"|[^"])*)"')
_unquoted_value = make_regex(r"([^\r\n]*)")
_comment = make_regex(r"(?:[^\S\r\n]*#[^\r\n]*)?")
_end_of_line = make_regex(r"[^\S\r\n]*(?:\r\n|\n|\r|$)")
_rest_of_line = make_regex(r"[^\r\n]*(?:\r|\n|\r\n)?")
_double_quote_escapes = make_regex(r"\\[\\'\"abfnrtv]")
_single_quote_escapes = make_regex(r"\\[\\']")


try:
    # this is necessary because we only import these from typing
    # when we are type checking, and the linter is upset if we
    # re-import
    import typing

    Original = typing.NamedTuple(
        "Original",
        [
            ("string", typing.Text),
            ("line", int),
        ],
    )

    Binding = typing.NamedTuple(
        "Binding",
        [
            ("key", typing.Optional[typing.Text]),
            ("value", typing.Optional[typing.Text]),
            ("original", Original),
            ("error", bool),
        ],
    )
except (ImportError, AttributeError):
    from collections import namedtuple
    Original = namedtuple(  # type: ignore
        "Original",
        [
            "string",
            "line",
        ],
    )
    Binding = namedtuple(  # type: ignore
        "Binding",
        [
            "key",
            "value",
            "original",
            "error",
        ],
    )


class Position:
    def __init__(self, chars, line):
        # type: (int, int) -> None
        self.chars = chars
        self.line = line

    @classmethod
    def start(cls):
        # type: () -> Position
        return cls(chars=0, line=1)

    def set(self, other):
        # type: (Position) -> None
        self.chars = other.chars
        self.line = other.line

    def advance(self, string):
        # type: (Text) -> None
        self.chars += len(string)
        self.line += len(re.findall(_newline, string))


class Error(Exception):
    pass


class Reader:
    def __init__(self, stream):
        # type: (IO[Text]) -> None
        self.string = stream.read()
        self.position = Position.start()
        self.mark = Position.start()

    def has_next(self):
        # type: () -> bool
        return self.position.chars < len(self.string)

    def set_mark(self):
        # type: () -> None
        self.mark.set(self.position)

    def get_marked(self):
        # type: () -> Original
        return Original(
            string=self.string[self.mark.chars:self.position.chars],
            line=self.mark.line,
        )

    def peek(self, count):
        # type: (int) -> Text
        return self.string[self.position.chars:self.position.chars + count]

    def read(self, count):
        # type: (int) -> Text
        result = self.string[self.position.chars:self.position.chars + count]
        if len(result) < count:
            raise Error("read: End of string")
        self.position.advance(result)
        return result

    def read_regex(self, regex):
        # type: (Pattern[Text]) -> Sequence[Text]
        match = regex.match(self.string, self.position.chars)
        if match is None:
            raise Error("read_regex: Pattern not found")
        self.position.advance(self.string[match.start():match.end()])
        return match.groups()


def decode_escapes(regex, string):
    # type: (Pattern[Text], Text) -> Text
    def decode_match(match):
        # type: (Match[Text]) -> Text
        return codecs.decode(match.group(0), 'unicode-escape')  # type: ignore

    return regex.sub(decode_match, string)


def parse_key(reader):
    # type: (Reader) -> Optional[Text]
    char = reader.peek(1)
    if char == "#":
        return None
    elif char == "'":
        (key,) = reader.read_regex(_single_quoted_key)
    else:
        (key,) = reader.read_regex(_unquoted_key)
    return key


def parse_unquoted_value(reader):
    # type: (Reader) -> Text
    (part,) = reader.read_regex(_unquoted_value)
    return re.sub(r"\s+#.*", "", part).rstrip()


def parse_value(reader):
    # type: (Reader) -> Text
    char = reader.peek(1)
    if char == u"'":
        (value,) = reader.read_regex(_single_quoted_value)
        return decode_escapes(_single_quote_escapes, value)
    elif char == u'"':
        (value,) = reader.read_regex(_double_quoted_value)
        return decode_escapes(_double_quote_escapes, value)
    elif char in (u"", u"\n", u"\r"):
        return u""
    else:
        return parse_unquoted_value(reader)


def parse_binding(reader):
    # type: (Reader) -> Binding
    reader.set_mark()
    try:
        reader.read_regex(_multiline_whitespace)
        if not reader.has_next():
            return Binding(
                key=None,
                value=None,
                original=reader.get_marked(),
                error=False,
            )
        reader.read_regex(_export)
        key = parse_key(reader)
        reader.read_regex(_whitespace)
        if reader.peek(1) == "=":
            reader.read_regex(_equal_sign)
            value = parse_value(reader)  # type: Optional[Text]
        else:
            value = None
        reader.read_regex(_comment)
        reader.read_regex(_end_of_line)
        return Binding(
            key=key,
            value=value,
            original=reader.get_marked(),
            error=False,
        )
    except Error:
        reader.read_regex(_rest_of_line)
        return Binding(
            key=None,
            value=None,
            original=reader.get_marked(),
            error=True,
        )


def parse_stream(stream):
    # type: (IO[Text]) -> Iterator[Binding]
    reader = Reader(stream)
    while reader.has_next():
        yield parse_binding(reader)
