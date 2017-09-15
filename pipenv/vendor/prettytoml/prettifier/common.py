
from itertools import *
from prettytoml.elements.common import TokenElement
from prettytoml.elements.metadata import NewlineElement


def text_to_elements(toml_text):
    from ..lexer import tokenize
    from ..parser import parse_tokens
    return parse_tokens(tokenize(toml_text))


def elements_to_text(toml_elements):
    return ''.join(e.serialized() for e in toml_elements)


def assert_prettifier_works(source_text, expected_text, prettifier_func):
    assert expected_text == elements_to_text(prettifier_func(text_to_elements(source_text)))


def lines(elements):
    """
    Splits a sequence of elements into a sub-sequence of each line.

    A line is defined as a sequence of elements terminated by a NewlineElement.
    """

    def __next_line(es):
        # Returns the next line and the remaining sequence of elements
        line = tuple(takewhile(lambda e: not isinstance(e, NewlineElement), es))
        line += (es[len(line)],)
        return line, es[len(line):]

    left_elements = tuple(elements)
    while left_elements:
        line, left_elements = __next_line(left_elements)
        yield line


def non_empty_elements(elements):
    """
    Filters out TokenElement instances with zero tokens.
    """
    return filter(lambda e: not (isinstance(e, TokenElement) and not e.tokens), elements)


def index(predicate, seq):
    """
    Returns the index of the element satisfying the given predicate, or None.
    """
    try:
        return next(i for (i, e) in enumerate(seq) if predicate(e))
    except StopIteration:
        return None
