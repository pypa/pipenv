# Make sure we use the patched packages.
import pipenv   # noqa

from prettytoml import lexer
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import (
    WhitespaceElement, PunctuationElement, CommentElement,
)
from prettytoml.elements.table import TableElement


def test_table():

    initial_toml = """id=42 # My id\nage=14"""
    tokens = tuple(lexer.tokenize(initial_toml))
    table = TableElement([
        AtomicElement(tokens[0:1]),
        PunctuationElement(tokens[1:2]),
        AtomicElement(tokens[2:3]),
        WhitespaceElement(tokens[3:4]),
        CommentElement(tokens[4:6]),

        AtomicElement(tokens[6:7]),
        PunctuationElement(tokens[7:8]),
        AtomicElement(tokens[8:9]),
    ])

    assert set(table.items()) == {('id', 42), ('age', 14)}

    del table['id']
    assert set(table.items()) == {('age', 14)}
