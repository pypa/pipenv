from prettytoml import lexer
from prettytoml.elements.tableheader import TableHeaderElement


def test_tableheader():
    tokens = tuple(lexer.tokenize('\n\t [[personal. information.details]] \n'))
    element = TableHeaderElement(tokens)

    assert element.is_array_of_tables
    assert ('personal', 'information', 'details') == element.names

    assert element.has_name_prefix(('personal', 'information'))
