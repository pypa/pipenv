from prettytoml import lexer
from prettytoml.elements.atomic import AtomicElement


def test_atomic_element():
    element = AtomicElement(tuple(lexer.tokenize(' \t 42 ')))
    assert element.value == 42
    element.set(23)
    assert element.serialized() == ' \t 23 '
