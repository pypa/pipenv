import datetime as _datetime

from ._utils import parse_rfc3339
from .container import Container
from .items import AoT
from .items import Array
from .items import Bool
from .items import Comment
from .items import Date
from .items import DateTime
from .items import Float
from .items import InlineTable
from .items import Integer
from .items import Item as _Item
from .items import Key
from .items import String
from .items import Table
from .items import Time
from .items import Trivia
from .items import Whitespace
from .items import item
from .parser import Parser
from .toml_document import TOMLDocument as _TOMLDocument


def loads(string):  # type: (str) -> _TOMLDocument
    """
    Parses a string into a TOMLDocument.

    Alias for parse().
    """
    return parse(string)


def dumps(data, sort_keys=False):  # type: (_TOMLDocument, bool) -> str
    """
    Dumps a TOMLDocument into a string.
    """
    if not isinstance(data, _TOMLDocument) and isinstance(data, dict):
        data = item(data, _sort_keys=sort_keys)

    return data.as_string()


def parse(string):  # type: (str) -> _TOMLDocument
    """
    Parses a string into a TOMLDocument.
    """
    return Parser(string).parse()


def document():  # type: () -> _TOMLDocument
    """
    Returns a new TOMLDocument instance.
    """
    return _TOMLDocument()


# Items
def integer(raw):  # type: (str) -> Integer
    return item(int(raw))


def float_(raw):  # type: (str) -> Float
    return item(float(raw))


def boolean(raw):  # type: (str) -> Bool
    return item(raw == "true")


def string(raw):  # type: (str) -> String
    return item(raw)


def date(raw):  # type: (str) -> Date
    value = parse_rfc3339(raw)
    if not isinstance(value, _datetime.date):
        raise ValueError("date() only accepts date strings.")

    return item(value)


def time(raw):  # type: (str) -> Time
    value = parse_rfc3339(raw)
    if not isinstance(value, _datetime.time):
        raise ValueError("time() only accepts time strings.")

    return item(value)


def datetime(raw):  # type: (str) -> DateTime
    value = parse_rfc3339(raw)
    if not isinstance(value, _datetime.datetime):
        raise ValueError("datetime() only accepts datetime strings.")

    return item(value)


def array(raw=None):  # type: (str) -> Array
    if raw is None:
        raw = "[]"

    return value(raw)


def table():  # type: () -> Table
    return Table(Container(), Trivia(), False)


def inline_table():  # type: () -> InlineTable
    return InlineTable(Container(), Trivia(), new=True)


def aot():  # type: () -> AoT
    return AoT([])


def key(k):  # type: (str) -> Key
    return Key(k)


def value(raw):  # type: (str) -> _Item
    return Parser(raw)._parse_value()


def key_value(src):  # type: (str) -> Tuple[Key, _Item]
    return Parser(src)._parse_key_value()


def ws(src):  # type: (str) -> Whitespace
    return Whitespace(src, fixed=True)


def nl():  # type: () -> Whitespace
    return ws("\n")


def comment(string):  # type: (str) -> Comment
    return Comment(Trivia(comment_ws="  ", comment="# " + string))
