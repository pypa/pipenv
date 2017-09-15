import operator
from prettytoml import tokens
from prettytoml.prettifier import common
from prettytoml.elements import traversal as t, factory as element_factory
from prettytoml.elements.array import ArrayElement
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.inlinetable import InlineTableElement
from prettytoml.elements.table import TableElement
from functools import *


MAXIMUM_LINE_LENGTH = 120


def line_length_limiter(toml_file_elements):
    """
    Rule: Lines whose lengths exceed 120 characters whose values are strings, arrays should have the array or
    string value broken onto multiple lines
    """
    return tuple(_fixed_table(e) if isinstance(e, TableElement) else e for e in toml_file_elements)


def _fixed_table(table_element):
    """
    Returns a new TableElement.
    """
    assert isinstance(table_element, TableElement)
    lines = tuple(common.lines(table_element.sub_elements))
    fixed_lines = tuple(_fixed_line(l) if _line_length(l) > MAXIMUM_LINE_LENGTH else l for l in lines)
    return TableElement(sub_elements=tuple(reduce(operator.concat, fixed_lines)))


def _line_length(line_elements):
    """
    Returns the character length of the serialized elements of the given line.
    """
    return sum(len(e.serialized()) for e in line_elements)


def _fixed_line(line_elements):

    def line_value_index():
        # Returns index of value element in the line
        key_index = t.find_following(line_elements, t.predicates.non_metadata)
        return t.find_following(line_elements, t.predicates.non_metadata, key_index)

    def multiline_equivalent(element):
        if isinstance(element, AtomicElement) and tokens.is_string(element.first_token):
            return element_factory.create_multiline_string(element.value, MAXIMUM_LINE_LENGTH)
        elif isinstance(element, ArrayElement):
            element.turn_into_multiline()
            return element
        else:
            return element

    line_elements = tuple(line_elements)
    value_index = line_value_index()
    if value_index >= 0:
        return line_elements[:value_index] + (multiline_equivalent(line_elements[value_index]),) + \
            line_elements[value_index+1:]
    else:
        return line_elements
