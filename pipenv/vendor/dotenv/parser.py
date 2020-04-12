import codecs
import re

from .compat import to_text, IS_TYPE_CHECKING


if IS_TYPE_CHECKING:
    from typing import (  # noqa:F401
        IO, Iterator, Match, NamedTuple, Optional, Pattern, Sequence, Text,
        Tuple
    )


def make_regex(string, extra_flags=0):
    # type: (str, int) -> Pattern[Text]
    return re.compile(to_text(string), re.UNICODE | extra_flags)


_whitespace = make_regex(r"\s*", extra_flags=re.MULTILINE)
_export = make_regex(r"(?:export[^\S\r\n]+)?")
_single_quoted_key = make_regex(r"'([^']+)'")
_unquoted_key = make_regex(r"([^=\#\s]+)")
_equal_sign = make_regex(r"[^\S\r\n]*=[^\S\r\n]*")
_single_quoted_value = make_regex(r"'((?:\\'|[^'])*)'")
_double_quoted_value = make_regex(r'"((?:\\"|[^"])*)"')
_unquoted_value_part = make_regex(r"([^ \r\n]*)")
_comment = make_regex(r"(?:\s*#[^\r\n]*)?")
_end_of_line = make_regex(r"[^\S\r\n]*(?:\r\n|\n|\r)?")
_rest_of_line = make_regex(r"[^\r\n]*(?:\r|\n|\r\n)?")
_double_quote_escapes = make_regex(r"\\[\\'\"abfnrtv]")
_single_quote_escapes = make_regex(r"\\[\\']")


try:
    # this is necessary because we only import these from typing
    # when we are type checking, and the linter is upset if we
    # re-import
    import typing
    Binding = typing.NamedTuple("Binding", [("key", typing.Optional[typing.Text]),
                                            ("value", typing.Optional[typing.Text]),
                                            ("original", typing.Text)])
except ImportError:  # pragma: no cover
    from collections import namedtuple
    Binding = namedtuple("Binding", ["key",  # type: ignore
                                     "value",
                                     "original"])  # type: Tuple[Optional[Text], Optional[Text], Text]


class Error(Exception):
    pass


class Reader:
    def __init__(self, stream):
        # type: (IO[Text]) -> None
        self.string = stream.read()
        self.position = 0
        self.mark = 0

    def has_next(self):
        # type: () -> bool
        return self.position < len(self.string)

    def set_mark(self):
        # type: () -> None
        self.mark = self.position

    def get_marked(self):
        # type: () -> Text
        return self.string[self.mark:self.position]

    def peek(self, count):
        # type: (int) -> Text
        return self.string[self.position:self.position + count]

    def read(self, count):
        # type: (int) -> Text
        result = self.string[self.position:self.position + count]
        if len(result) < count:
            raise Error("read: End of string")
        self.position += count
        return result

    def read_regex(self, regex):
        # type: (Pattern[Text]) -> Sequence[Text]
        match = regex.match(self.string, self.position)
        if match is None:
            raise Error("read_regex: Pattern not found")
        self.position = match.end()
        return match.groups()


def decode_escapes(regex, string):
    # type: (Pattern[Text], Text) -> Text
    def decode_match(match):
        # type: (Match[Text]) -> Text
        return codecs.decode(match.group(0), 'unicode-escape')  # type: ignore

    return regex.sub(decode_match, string)


def parse_key(reader):
    # type: (Reader) -> Text
    char = reader.peek(1)
    if char == "'":
        (key,) = reader.read_regex(_single_quoted_key)
    else:
        (key,) = reader.read_regex(_unquoted_key)
    return key


def parse_unquoted_value(reader):
    # type: (Reader) -> Text
    value = u""
    while True:
        (part,) = reader.read_regex(_unquoted_value_part)
        value += part
        after = reader.peek(2)
        if len(after) < 2 or after[0] in u"\r\n" or after[1] in u" #\r\n":
            return value
        value += reader.read(2)


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
        reader.read_regex(_whitespace)
        reader.read_regex(_export)
        key = parse_key(reader)
        reader.read_regex(_equal_sign)
        value = parse_value(reader)
        reader.read_regex(_comment)
        reader.read_regex(_end_of_line)
        return Binding(key=key, value=value, original=reader.get_marked())
    except Error:
        reader.read_regex(_rest_of_line)
        return Binding(key=None, value=None, original=reader.get_marked())


def parse_stream(stream):
    # type:(IO[Text]) -> Iterator[Binding]
    reader = Reader(stream)
    while reader.has_next():
        try:
            yield parse_binding(reader)
        except Error:
            return
