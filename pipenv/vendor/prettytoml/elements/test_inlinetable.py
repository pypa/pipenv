from prettytoml import lexer
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.inlinetable import InlineTableElement
from prettytoml.elements.metadata import PunctuationElement, WhitespaceElement


def test_inline_table():
    tokens = tuple(lexer.tokenize('{ name= "first", id=42}'))

    elements = (
        PunctuationElement(tokens[:1]),
        WhitespaceElement(tokens[1:2]),
        AtomicElement(tokens[2:3]),
        PunctuationElement(tokens[3:4]),
        WhitespaceElement(tokens[4:5]),
        AtomicElement(tokens[5:6]),
        PunctuationElement(tokens[6:7]),
        WhitespaceElement(tokens[7:8]),
        AtomicElement(tokens[8:9]),
        PunctuationElement(tokens[9:10]),
        AtomicElement(tokens[10:11]),
        PunctuationElement(tokens[11:12])
    )

    table = InlineTableElement(elements)

    assert table['name'] == 'first'
    assert table['id'] == 42

    table['name'] = 'fawzy'
    table['nickname'] = 'nickfawzy'

    assert set(table.items()) == {('name', 'fawzy'), ('id', 42), ('nickname', 'nickfawzy')}

    assert table.serialized() == '{ name= "fawzy", id=42, nickname = "nickfawzy"}'

    del table['name']

    assert table.serialized() == '{ id=42, nickname = "nickfawzy"}'

    del table['nickname']

    assert table.serialized() == '{ id=42}'

    del table['id']

    assert table.serialized() == '{ }'

    table['item1'] = 11
    table['item2'] = 22

    assert table.serialized() == '{ item1 = 11, item2 = 22}'
