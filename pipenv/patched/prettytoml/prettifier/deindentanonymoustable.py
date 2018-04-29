import operator
from prettytoml.elements import traversal as t, traversal
from itertools import *
from functools import *
from prettytoml.elements.metadata import WhitespaceElement
from prettytoml.elements.table import TableElement
from prettytoml.prettifier import common


def deindent_anonymous_table(toml_file_elements):
    """
    Rule: Anonymous table should never be indented.
    """

    anonymous_table_index = _find_anonymous_table(toml_file_elements)
    if anonymous_table_index is None:
        return toml_file_elements

    return toml_file_elements[:anonymous_table_index] + \
               [_unindent_table(toml_file_elements[anonymous_table_index])] + \
               toml_file_elements[anonymous_table_index+1:]


def _unindent_table(table_element):
    table_lines = tuple(common.lines(table_element.sub_elements))
    unindented_lines = tuple(tuple(dropwhile(lambda e: isinstance(e, WhitespaceElement), line)) for line in table_lines)
    return TableElement(reduce(operator.concat, unindented_lines))


def _find_anonymous_table(toml_file_elements):
    """
    Finds and returns the index of the TableElement comprising the anonymous table or None.
    """

    first_table_index = common.index(t.predicates.table, toml_file_elements)
    first_table_header_index = common.index(t.predicates.table_header, toml_file_elements)

    if first_table_header_index is None:
        return first_table_index
    elif first_table_index < first_table_header_index:
        return first_table_index


