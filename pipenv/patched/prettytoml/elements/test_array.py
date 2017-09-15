import pytest
from prettytoml import lexer
from prettytoml.elements.array import ArrayElement
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import PunctuationElement, WhitespaceElement, NewlineElement


def test_array_element():
    tokens = tuple(lexer.tokenize('[4, 8, 42, \n 23, 15]'))
    assert len(tokens) == 17
    sub_elements = (
        PunctuationElement(tokens[:1]),

        AtomicElement(tokens[1:2]),
        PunctuationElement(tokens[2:3]),
        WhitespaceElement(tokens[3:4]),

        AtomicElement(tokens[4:5]),
        PunctuationElement(tokens[5:6]),
        WhitespaceElement(tokens[6:7]),

        AtomicElement(tokens[7:8]),
        PunctuationElement(tokens[8:9]),
        WhitespaceElement(tokens[9:10]),
        NewlineElement(tokens[10:11]),
        WhitespaceElement(tokens[11:12]),

        AtomicElement(tokens[12:13]),
        PunctuationElement(tokens[13:14]),

        WhitespaceElement(tokens[14:15]),
        AtomicElement(tokens[15:16]),
        PunctuationElement(tokens[16:17])
    )

    array_element = ArrayElement(sub_elements)

    # Test length
    assert len(array_element) == 5

    # Test getting a value
    assert array_element[0] == 4
    assert array_element[1] == 8
    assert array_element[2] == 42
    assert array_element[3] == 23
    assert array_element[-1] == 15

    # Test assignment with a negative index
    array_element[-1] = 12

    # Test persistence of formatting
    assert '[4, 8, 42, \n 23, 12]' == array_element.serialized()

    # Test raises IndexError on invalid index
    with pytest.raises(IndexError) as _:
        print(array_element[5])

    # Test appending a new value
    array_element.append(77)
    assert '[4, 8, 42, \n 23, 12, 77]' == array_element.serialized()

    # Test deleting a value
    del array_element[3]
    assert '[4, 8, 42, 12, 77]' == array_element.serialized()

    # Test primitive_value
    assert [4, 8, 42, 12, 77] == array_element.primitive_value
