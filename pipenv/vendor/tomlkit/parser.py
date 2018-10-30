# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import datetime
import itertools
import re
import string

from copy import copy

from ._compat import PY2
from ._compat import chr
from ._compat import decode
from ._utils import _escaped
from ._utils import parse_rfc3339
from .container import Container
from .exceptions import EmptyKeyError
from .exceptions import EmptyTableNameError
from .exceptions import InternalParserError
from .exceptions import InvalidCharInStringError
from .exceptions import InvalidNumberOrDateError
from .exceptions import MixedArrayTypesError
from .exceptions import ParseError
from .exceptions import UnexpectedCharError
from .exceptions import UnexpectedEofError
from .items import AoT
from .items import Array
from .items import Bool
from .items import Comment
from .items import Date
from .items import DateTime
from .items import Float
from .items import InlineTable
from .items import Integer
from .items import Key
from .items import KeyType
from .items import Null
from .items import String
from .items import StringType
from .items import Table
from .items import Time
from .items import Trivia
from .items import Whitespace
from .toml_char import TOMLChar
from .toml_document import TOMLDocument


class Parser:
    """
    Parser for TOML documents.
    """

    def __init__(self, string):  # type: (str) -> None
        # Input to parse
        self._src = decode(string)  # type: str
        # Iterator used for getting characters from src.
        self._chars = iter([(i, TOMLChar(c)) for i, c in enumerate(self._src)])
        # Current byte offset into src.
        self._idx = 0
        # Current character
        self._current = TOMLChar("")  # type: TOMLChar
        # Index into src between which and idx slices will be extracted
        self._marker = 0

        self._aot_stack = []

        self.inc()

    def extract(self):  # type: () -> str
        """
        Extracts the value between marker and index
        """
        if self.end():
            return self._src[self._marker :]
        else:
            return self._src[self._marker : self._idx]

    def inc(self, exception=None):  # type: () -> bool
        """
        Increments the parser if the end of the input has not been reached.
        Returns whether or not it was able to advance.
        """
        try:
            self._idx, self._current = next(self._chars)

            return True
        except StopIteration:
            self._idx = len(self._src)
            self._current = TOMLChar("\0")

            if not exception:
                return False
            raise exception

    def inc_n(self, n, exception=None):  # type: (int) -> bool
        """
        Increments the parser by n characters
        if the end of the input has not been reached.
        """
        for _ in range(n):
            if not self.inc(exception=exception):
                return False

        return True

    def end(self):  # type: () -> bool
        """
        Returns True if the parser has reached the end of the input.
        """
        return self._idx >= len(self._src) or self._current == "\0"

    def mark(self):  # type: () -> None
        """
        Sets the marker to the index's current position
        """
        self._marker = self._idx

    def parse(self):  # type: () -> TOMLDocument
        body = TOMLDocument(True)

        # Take all keyvals outside of tables/AoT's.
        while not self.end():
            # Break out if a table is found
            if self._current == "[":
                break

            # Otherwise, take and append one KV
            item = self._parse_item()
            if not item:
                break

            key, value = item
            if key is not None and key.is_dotted():
                # We actually have a table
                self._handle_dotted_key(body, key, value)
            elif not self._merge_ws(value, body):
                body.append(key, value)

            self.mark()

        while not self.end():
            key, value = self._parse_table()
            if isinstance(value, Table) and value.is_aot_element():
                # This is just the first table in an AoT. Parse the rest of the array
                # along with it.
                value = self._parse_aot(value, key.key)

            body.append(key, value)

        body.parsing(False)

        return body

    def _merge_ws(self, item, container):  # type: (Item, Container) -> bool
        """
        Merges the given Item with the last one currently in the given Container if
        both are whitespace items.

        Returns True if the items were merged.
        """
        last = container.last_item()
        if not last:
            return False

        if not isinstance(item, Whitespace) or not isinstance(last, Whitespace):
            return False

        start = self._idx - (len(last.s) + len(item.s))
        container.body[-1] = (
            container.body[-1][0],
            Whitespace(self._src[start : self._idx]),
        )

        return True

    def parse_error(self, kind=ParseError, args=None):  # type: () -> None
        """
        Creates a generic "parse error" at the current position.
        """
        line, col = self._to_linecol(self._idx)

        if args:
            return kind(line, col, *args)
        else:
            return kind(line, col)

    def _to_linecol(self, offset):  # type: (int) -> Tuple[int, int]
        cur = 0
        for i, line in enumerate(self._src.splitlines()):
            if cur + len(line) + 1 > offset:
                return (i + 1, offset - cur)

            cur += len(line) + 1

        return len(self._src.splitlines()), 0

    def _is_child(self, parent, child):  # type: (str, str) -> bool
        """
        Returns whether a key is strictly a child of another key.
        AoT siblings are not considered children of one another.
        """
        parent_parts = tuple(self._split_table_name(parent))
        child_parts = tuple(self._split_table_name(child))

        if parent_parts == child_parts:
            return False

        return parent_parts == child_parts[: len(parent_parts)]

    def _split_table_name(self, name):  # type: (str) -> Generator[Key]
        in_name = False
        current = ""
        t = KeyType.Bare
        for c in name:
            c = TOMLChar(c)

            if c == ".":
                if in_name:
                    current += c
                    continue

                if not current:
                    raise self.parse_error()

                yield Key(current, t=t, sep="")

                current = ""
                t = KeyType.Bare
                continue
            elif c in {"'", '"'}:
                if in_name:
                    if t == KeyType.Literal and c == '"':
                        current += c
                        continue

                    if c != t.value:
                        raise self.parse_error()

                    in_name = False
                else:
                    in_name = True
                    t = KeyType.Literal if c == "'" else KeyType.Basic

                continue
            elif in_name or c.is_bare_key_char():
                current += c
            else:
                raise self.parse_error()

        if current:
            yield Key(current, t=t, sep="")

    def _parse_item(self):  # type: () -> Optional[Tuple[Optional[Key], Item]]
        """
        Attempts to parse the next item and returns it, along with its key
        if the item is value-like.
        """
        self.mark()
        saved_idx = self._save_idx()

        while True:
            c = self._current
            if c == "\n":
                # Found a newline; Return all whitespace found up to this point.
                self.inc()

                return (None, Whitespace(self.extract()))
            elif c in " \t\r":
                # Skip whitespace.
                if not self.inc():
                    return (None, Whitespace(self.extract()))
            elif c == "#":
                # Found a comment, parse it
                indent = self.extract()
                cws, comment, trail = self._parse_comment_trail()

                return (None, Comment(Trivia(indent, cws, comment, trail)))
            elif c == "[":
                # Found a table, delegate to the calling function.
                return
            else:
                # Begining of a KV pair.
                # Return to beginning of whitespace so it gets included
                # as indentation for the KV about to be parsed.
                self._restore_idx(*saved_idx)
                key, value = self._parse_key_value(True)

                return key, value

    def _save_idx(self):  # type: () -> Tuple[Iterator, int, str]
        if PY2:
            # Python 2.7 does not allow to directly copy
            # an iterator, so we have to make tees of the original
            # chars iterator.
            chars1, chars2 = itertools.tee(self._chars)

            # We can no longer use the original chars iterator.
            self._chars = chars1

            return chars2, self._idx, self._current

        return copy(self._chars), self._idx, self._current

    def _restore_idx(self, chars, idx, current):  # type: (Iterator, int, str) -> None
        self._chars = chars
        self._idx = idx
        self._current = current

    def _parse_comment_trail(self):  # type: () -> Tuple[str, str, str]
        """
        Returns (comment_ws, comment, trail)
        If there is no comment, comment_ws and comment will
        simply be empty.
        """
        if self.end():
            return "", "", ""

        comment = ""
        comment_ws = ""
        self.mark()

        while True:
            c = self._current

            if c == "\n":
                break
            elif c == "#":
                comment_ws = self.extract()

                self.mark()
                self.inc()  # Skip #

                # The comment itself
                while not self.end() and not self._current.is_nl() and self.inc():
                    pass

                comment = self.extract()
                self.mark()

                break
            elif c in " \t\r":
                self.inc()
            else:
                raise self.parse_error(UnexpectedCharError, (c))

            if self.end():
                break

        while self._current.is_spaces() and self.inc():
            pass

        if self._current == "\r":
            self.inc()

        if self._current == "\n":
            self.inc()

        trail = ""
        if self._idx != self._marker or self._current.is_ws():
            trail = self.extract()

        return comment_ws, comment, trail

    def _parse_key_value(
        self, parse_comment=False, inline=True
    ):  # type: (bool, bool) -> (Key, Item)
        # Leading indent
        self.mark()

        while self._current.is_spaces() and self.inc():
            pass

        indent = self.extract()

        # Key
        key = self._parse_key()
        if not key.key.strip():
            raise self.parse_error(EmptyKeyError)

        self.mark()

        found_equals = self._current == "="
        while self._current.is_kv_sep() and self.inc():
            if self._current == "=":
                if found_equals:
                    raise self.parse_error(UnexpectedCharError, ("=",))
                else:
                    found_equals = True
            pass

        key.sep = self.extract()

        # Value
        val = self._parse_value()

        # Comment
        if parse_comment:
            cws, comment, trail = self._parse_comment_trail()
            meta = val.trivia
            meta.comment_ws = cws
            meta.comment = comment
            meta.trail = trail
        else:
            val.trivia.trail = ""

        val.trivia.indent = indent

        return key, val

    def _parse_key(self):  # type: () -> Key
        """
        Parses a Key at the current position;
        WS before the key must be exhausted first at the callsite.
        """
        if self._current in "\"'":
            return self._parse_quoted_key()
        else:
            return self._parse_bare_key()

    def _parse_quoted_key(self):  # type: () -> Key
        """
        Parses a key enclosed in either single or double quotes.
        """
        quote_style = self._current
        key_type = None
        dotted = False
        for t in KeyType:
            if t.value == quote_style:
                key_type = t
                break

        if key_type is None:
            raise RuntimeError("Should not have entered _parse_quoted_key()")

        self.inc()
        self.mark()

        while self._current != quote_style and self.inc():
            pass

        key = self.extract()

        if self._current == ".":
            self.inc()
            dotted = True
            key += "." + self._parse_key().as_string()
            key_type = KeyType.Bare
        else:
            self.inc()

        return Key(key, key_type, "", dotted)

    def _parse_bare_key(self):  # type: () -> Key
        """
        Parses a bare key.
        """
        key_type = None
        dotted = False

        self.mark()
        while self._current.is_bare_key_char() and self.inc():
            pass

        key = self.extract()

        if self._current == ".":
            self.inc()
            dotted = True
            key += "." + self._parse_key().as_string()
            key_type = KeyType.Bare

        return Key(key, key_type, "", dotted)

    def _handle_dotted_key(
        self, container, key, value
    ):  # type: (Container, Key) -> None
        names = tuple(self._split_table_name(key.key))
        name = names[0]
        name._dotted = True
        if name in container:
            table = container.item(name)
        else:
            table = Table(Container(True), Trivia(), False, is_super_table=True)
            container.append(name, table)

        for i, _name in enumerate(names[1:]):
            if i == len(names) - 2:
                _name.sep = key.sep

                table.append(_name, value)
            else:
                _name._dotted = True
                if _name in table.value:
                    table = table.value.item(_name)
                else:
                    table.append(
                        _name,
                        Table(
                            Container(True),
                            Trivia(),
                            False,
                            is_super_table=i < len(names) - 2,
                        ),
                    )

                    table = table[_name]

    def _parse_value(self):  # type: () -> Item
        """
        Attempts to parse a value at the current position.
        """
        self.mark()
        trivia = Trivia()

        c = self._current
        if c == '"':
            return self._parse_basic_string()
        elif c == "'":
            return self._parse_literal_string()
        elif c == "t" and self._src[self._idx :].startswith("true"):
            # Boolean: true
            self.inc_n(4)

            return Bool(True, trivia)
        elif c == "f" and self._src[self._idx :].startswith("false"):
            # Boolean: true
            self.inc_n(5)

            return Bool(False, trivia)
        elif c == "[":
            # Array
            elems = []  # type: List[Item]
            self.inc()

            while self._current != "]":
                self.mark()
                while self._current.is_ws() or self._current == ",":
                    self.inc()

                if self._idx != self._marker:
                    elems.append(Whitespace(self.extract()))

                if self._current == "]":
                    break

                if self._current == "#":
                    cws, comment, trail = self._parse_comment_trail()

                    next_ = Comment(Trivia("", cws, comment, trail))
                else:
                    next_ = self._parse_value()

                elems.append(next_)

            self.inc()

            try:
                res = Array(elems, trivia)
            except ValueError:
                raise self.parse_error(MixedArrayTypesError)

            if res.is_homogeneous():
                return res

            raise self.parse_error(MixedArrayTypesError)
        elif c == "{":
            # Inline table
            elems = Container(True)
            self.inc()

            while self._current != "}":
                self.mark()
                while self._current.is_spaces() or self._current == ",":
                    self.inc()

                if self._idx != self._marker:
                    ws = self.extract().lstrip(",")
                    if ws:
                        elems.append(None, Whitespace(ws))

                if self._current == "}":
                    break

                key, val = self._parse_key_value(False, inline=True)
                elems.append(key, val)

            self.inc()

            return InlineTable(elems, trivia)
        elif c in string.digits + "+-" or self._peek(4) in {
            "+inf",
            "-inf",
            "inf",
            "+nan",
            "-nan",
            "nan",
        }:
            # Integer, Float, Date, Time or DateTime
            while self._current not in " \t\n\r#,]}" and self.inc():
                pass

            raw = self.extract()

            item = self._parse_number(raw, trivia)
            if item is not None:
                return item

            try:
                res = parse_rfc3339(raw)
            except ValueError:
                res = None

            if res is None:
                raise self.parse_error(InvalidNumberOrDateError)

            if isinstance(res, datetime.datetime):
                return DateTime(res, trivia, raw)
            elif isinstance(res, datetime.time):
                return Time(res, trivia, raw)
            elif isinstance(res, datetime.date):
                return Date(res, trivia, raw)
            else:
                raise self.parse_error(InvalidNumberOrDateError)
        else:
            raise self.parse_error(UnexpectedCharError, (c))

    def _parse_number(self, raw, trivia):  # type: (str, Trivia) -> Optional[Item]
        # Leading zeros are not allowed
        sign = ""
        if raw.startswith(("+", "-")):
            sign = raw[0]
            raw = raw[1:]

        if (
            len(raw) > 1
            and raw.startswith("0")
            and not raw.startswith(("0.", "0o", "0x", "0b"))
        ):
            return

        if raw.startswith(("0o", "0x", "0b")) and sign:
            return

        digits = "[0-9]"
        base = 10
        if raw.startswith("0b"):
            digits = "[01]"
            base = 2
        elif raw.startswith("0o"):
            digits = "[0-7]"
            base = 8
        elif raw.startswith("0x"):
            digits = "[0-9a-f]"
            base = 16

        # Underscores should be surrounded by digits
        clean = re.sub("(?i)(?<={})_(?={})".format(digits, digits), "", raw)

        if "_" in clean:
            return

        if clean.endswith("."):
            return

        try:
            return Integer(int(sign + clean, base), trivia, sign + raw)
        except ValueError:
            try:
                return Float(float(sign + clean), trivia, sign + raw)
            except ValueError:
                return

    def _parse_literal_string(self):  # type: () -> Item
        return self._parse_string(StringType.SLL)

    def _parse_basic_string(self):  # type: () -> Item
        return self._parse_string(StringType.SLB)

    def _parse_escaped_char(self, multiline):
        if multiline and self._current.is_ws():
            # When the last non-whitespace character on a line is
            # a \, it will be trimmed along with all whitespace
            # (including newlines) up to the next non-whitespace
            # character or closing delimiter.
            # """\
            #     hello \
            #     world"""
            tmp = ""
            while self._current.is_ws():
                tmp += self._current
                # consume the whitespace, EOF here is an issue
                # (middle of string)
                self.inc(exception=UnexpectedEofError)
                continue

            # the escape followed by whitespace must have a newline
            # before any other chars
            if "\n" not in tmp:
                raise self.parse_error(InvalidCharInStringError, (self._current,))

            return ""

        if self._current in _escaped:
            c = _escaped[self._current]

            # consume this char, EOF here is an issue (middle of string)
            self.inc(exception=UnexpectedEofError)

            return c

        if self._current in {"u", "U"}:
            # this needs to be a unicode
            u, ue = self._peek_unicode(self._current == "U")
            if u is not None:
                # consume the U char and the unicode value
                self.inc_n(len(ue) + 1)

                return u

        raise self.parse_error(InvalidCharInStringError, (self._current,))

    def _parse_string(self, delim):  # type: (str) -> Item
        delim = StringType(delim)
        assert delim.is_singleline()

        # only keep parsing for string if the current character matches the delim
        if self._current != delim.unit:
            raise ValueError("Expecting a {!r} character".format(delim))

        # consume the opening/first delim, EOF here is an issue
        # (middle of string or middle of delim)
        self.inc(exception=UnexpectedEofError)

        if self._current == delim.unit:
            # consume the closing/second delim, we do not care if EOF occurs as
            # that would simply imply an empty single line string
            if not self.inc() or self._current != delim.unit:
                # Empty string
                return String(delim, "", "", Trivia())

            # consume the third delim, EOF here is an issue (middle of string)
            self.inc(exception=UnexpectedEofError)

            delim = delim.toggle()  # convert delim to multi delim

        self.mark()  # to extract the original string with whitespace and all
        value = ""

        # A newline immediately following the opening delimiter will be trimmed.
        if delim.is_multiline() and self._current == "\n":
            # consume the newline, EOF here is an issue (middle of string)
            self.inc(exception=UnexpectedEofError)

        escaped = False  # whether the previous key was ESCAPE
        while True:
            if delim.is_singleline() and self._current.is_nl():
                # single line cannot have actual newline characters
                raise self.parse_error(InvalidCharInStringError, (self._current,))
            elif not escaped and self._current == delim.unit:
                # try to process current as a closing delim
                original = self.extract()

                close = ""
                if delim.is_multiline():
                    # try consuming three delims as this would mean the end of
                    # the string
                    for last in [False, False, True]:
                        if self._current != delim.unit:
                            # Not a triple quote, leave in result as-is.
                            # Adding back the characters we already consumed
                            value += close
                            close = ""  # clear the close
                            break

                        close += delim.unit

                        # consume this delim, EOF here is only an issue if this
                        # is not the third (last) delim character
                        self.inc(exception=UnexpectedEofError if not last else None)

                    if not close:  # if there is no close characters, keep parsing
                        continue
                else:
                    close = delim.unit

                    # consume the closing delim, we do not care if EOF occurs as
                    # that would simply imply the end of self._src
                    self.inc()

                return String(delim, value, original, Trivia())
            elif delim.is_basic() and escaped:
                # attempt to parse the current char as an escaped value, an exception
                # is raised if this fails
                value += self._parse_escaped_char(delim.is_multiline())

                # no longer escaped
                escaped = False
            elif delim.is_basic() and self._current == "\\":
                # the next char is being escaped
                escaped = True

                # consume this char, EOF here is an issue (middle of string)
                self.inc(exception=UnexpectedEofError)
            else:
                # this is either a literal string where we keep everything as is,
                # or this is not a special escaped char in a basic string
                value += self._current

                # consume this char, EOF here is an issue (middle of string)
                self.inc(exception=UnexpectedEofError)

    def _parse_table(
        self, parent_name=None
    ):  # type: (Optional[str]) -> Tuple[Key, Union[Table, AoT]]
        """
        Parses a table element.
        """
        if self._current != "[":
            raise self.parse_error(
                InternalParserError,
                ("_parse_table() called on non-bracket character.",),
            )

        indent = self.extract()
        self.inc()  # Skip opening bracket

        if self.end():
            raise self.parse_error(UnexpectedEofError)

        is_aot = False
        if self._current == "[":
            if not self.inc():
                raise self.parse_error(UnexpectedEofError)

            is_aot = True

        # Key
        self.mark()
        while self._current != "]" and self.inc():
            if self.end():
                raise self.parse_error(UnexpectedEofError)

            pass

        name = self.extract()
        if not name.strip():
            raise self.parse_error(EmptyTableNameError)

        key = Key(name, sep="")
        name_parts = tuple(self._split_table_name(name))
        missing_table = False
        if parent_name:
            parent_name_parts = tuple(self._split_table_name(parent_name))
        else:
            parent_name_parts = tuple()

        if len(name_parts) > len(parent_name_parts) + 1:
            missing_table = True

        name_parts = name_parts[len(parent_name_parts) :]

        values = Container(True)

        self.inc()  # Skip closing bracket
        if is_aot:
            # TODO: Verify close bracket
            self.inc()

        cws, comment, trail = self._parse_comment_trail()

        result = Null()

        if len(name_parts) > 1:
            if missing_table:
                # Missing super table
                # i.e. a table initialized like this: [foo.bar]
                # without initializing [foo]
                #
                # So we have to create the parent tables
                table = Table(
                    Container(True),
                    Trivia(indent, cws, comment, trail),
                    is_aot and name_parts[0].key in self._aot_stack,
                    is_super_table=True,
                    name=name_parts[0].key,
                )

                result = table
                key = name_parts[0]

                for i, _name in enumerate(name_parts[1:]):
                    if _name in table:
                        child = table[_name]
                    else:
                        child = Table(
                            Container(True),
                            Trivia(indent, cws, comment, trail),
                            is_aot and i == len(name_parts[1:]) - 1,
                            is_super_table=i < len(name_parts[1:]) - 1,
                            name=_name.key,
                            display_name=name if i == len(name_parts[1:]) - 1 else None,
                        )

                    if is_aot and i == len(name_parts[1:]) - 1:
                        table.append(_name, AoT([child], name=table.name, parsed=True))
                    else:
                        table.append(_name, child)

                    table = child
                    values = table.value
        else:
            if name_parts:
                key = name_parts[0]

        while not self.end():
            item = self._parse_item()
            if item:
                _key, item = item
                if not self._merge_ws(item, values):
                    if _key is not None and _key.is_dotted():
                        self._handle_dotted_key(values, _key, item)
                    else:
                        values.append(_key, item)
            else:
                if self._current == "[":
                    is_aot_next, name_next = self._peek_table()

                    if self._is_child(name, name_next):
                        key_next, table_next = self._parse_table(name)

                        values.append(key_next, table_next)

                        # Picking up any sibling
                        while not self.end():
                            _, name_next = self._peek_table()

                            if not self._is_child(name, name_next):
                                break

                            key_next, table_next = self._parse_table(name)

                            values.append(key_next, table_next)

                    break
                else:
                    raise self.parse_error(
                        InternalParserError,
                        ("_parse_item() returned None on a non-bracket character.",),
                    )

        if isinstance(result, Null):
            result = Table(
                values,
                Trivia(indent, cws, comment, trail),
                is_aot,
                name=name,
                display_name=name,
            )

            if is_aot and (not self._aot_stack or name != self._aot_stack[-1]):
                result = self._parse_aot(result, name)

        return key, result

    def _peek_table(self):  # type: () -> Tuple[bool, str]
        """
        Peeks ahead non-intrusively by cloning then restoring the
        initial state of the parser.

        Returns the name of the table about to be parsed,
        as well as whether it is part of an AoT.
        """
        # Save initial state
        idx = self._save_idx()
        marker = self._marker

        if self._current != "[":
            raise self.parse_error(
                InternalParserError, ("_peek_table() entered on non-bracket character",)
            )

        # AoT
        self.inc()
        is_aot = False
        if self._current == "[":
            self.inc()
            is_aot = True

        self.mark()

        while self._current != "]" and self.inc():
            table_name = self.extract()

        # Restore initial state
        self._restore_idx(*idx)
        self._marker = marker

        return is_aot, table_name

    def _parse_aot(self, first, name_first):  # type: (Table, str) -> AoT
        """
        Parses all siblings of the provided table first and bundles them into
        an AoT.
        """
        payload = [first]
        self._aot_stack.append(name_first)
        while not self.end():
            is_aot_next, name_next = self._peek_table()
            if is_aot_next and name_next == name_first:
                _, table = self._parse_table(name_first)
                payload.append(table)
            else:
                break

        self._aot_stack.pop()

        return AoT(payload, parsed=True)

    def _peek(self, n):  # type: (int) -> str
        """
        Peeks ahead n characters.

        n is the max number of characters that will be peeked.
        """
        idx = self._save_idx()
        buf = ""
        for _ in range(n):
            if self._current not in " \t\n\r#,]}":
                buf += self._current
                self.inc()
                continue

            break

        self._restore_idx(*idx)

        return buf

    def _peek_unicode(self, is_long):  # type: () -> Tuple[bool, str]
        """
        Peeks ahead non-intrusively by cloning then restoring the
        initial state of the parser.

        Returns the unicode value is it's a valid one else None.
        """
        # Save initial state
        idx = self._save_idx()
        marker = self._marker

        if self._current not in {"u", "U"}:
            raise self.parse_error(
                InternalParserError, ("_peek_unicode() entered on non-unicode value")
            )

        # AoT
        self.inc()  # Dropping prefix
        self.mark()

        if is_long:
            chars = 8
        else:
            chars = 4

        if not self.inc_n(chars):
            value, extracted = None, None
        else:
            extracted = self.extract()

            try:
                value = chr(int(extracted, 16))
            except ValueError:
                value = None

        # Restore initial state
        self._restore_idx(*idx)
        self._marker = marker

        return value, extracted
