
"""
     The following predicates can be used in the traversal functions directly.
"""

from ..atomic import AtomicElement
from ..metadata import PunctuationElement, CommentElement, NewlineElement, WhitespaceElement
from prettytoml import tokens
from .. import common


atomic = lambda e: isinstance(e, AtomicElement)


op_assignment = lambda e: isinstance(e, PunctuationElement) and e.token.type == tokens.TYPE_OP_ASSIGNMENT


op_comma = lambda e: isinstance(e, PunctuationElement) and e.token.type == tokens.TYPE_OP_COMMA


comment = lambda e: isinstance(e, CommentElement)


newline = lambda e: isinstance(e, NewlineElement)


non_metadata = lambda e: e.type != common.TYPE_METADATA


closing_square_bracket = \
    lambda e: isinstance(e, PunctuationElement) and e.token.type == tokens.TYPE_OP_SQUARE_RIGHT_BRACKET


opening_square_bracket = \
    lambda e: isinstance(e, PunctuationElement) and e.token.type == tokens.TYPE_OP_SQUARE_LEFT_BRACKET


def table(e):
    from ..table import TableElement
    return isinstance(e, TableElement)


def table_header(e):
    from prettytoml.elements.tableheader import TableHeaderElement
    return isinstance(e, TableHeaderElement)


whitespace = lambda e: isinstance(e, WhitespaceElement)
