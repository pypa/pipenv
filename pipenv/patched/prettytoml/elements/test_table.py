from prettytoml import lexer
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import WhitespaceElement, PunctuationElement, NewlineElement, CommentElement
from prettytoml.elements.table import TableElement


def test_table():

    initial_toml = """name = "first"
id=42 # My id


"""

    tokens = tuple(lexer.tokenize(initial_toml))

    elements = (
        AtomicElement(tokens[:1]),
        WhitespaceElement(tokens[1:2]),
        PunctuationElement(tokens[2:3]),
        WhitespaceElement(tokens[3:4]),
        AtomicElement(tokens[4:5]),
        NewlineElement(tokens[5:6]),

        AtomicElement(tokens[6:7]),
        PunctuationElement(tokens[7:8]),
        AtomicElement(tokens[8:9]),
        WhitespaceElement(tokens[9:10]),
        CommentElement(tokens[10:12]),

        NewlineElement(tokens[12:13]),
        NewlineElement(tokens[13:14]),
    )

    table = TableElement(elements)

    assert set(table.items()) == {('name', 'first'), ('id', 42)}

    assert table['name'] == 'first'
    assert table['id'] == 42

    table['relation'] = 'another'

    assert set(table.items()) == {('name', 'first'), ('id', 42), ('relation', 'another')}

    table['name'] = 'fawzy'

    assert set(table.items()) == {('name', 'fawzy'), ('id', 42), ('relation', 'another')}

    expected_toml = """name = "fawzy"
id=42 # My id
relation = "another"


"""

    assert table.serialized() == expected_toml


