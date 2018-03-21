# Make sure we use the patched packages.
import pipenv  # noqa
import os

from prettytoml import lexer
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import (
    WhitespaceElement, PunctuationElement, CommentElement
)
from prettytoml.elements.table import TableElement
from pipenv.patched.pipfile.api import PipfileParser


def test_table():
    initial_toml = """id=42 # My id\nage=14"""
    tokens = tuple(lexer.tokenize(initial_toml))
    table = TableElement(
        [
            AtomicElement(tokens[0:1]),
            PunctuationElement(tokens[1:2]),
            AtomicElement(tokens[2:3]),
            WhitespaceElement(tokens[3:4]),
            CommentElement(tokens[4:6]),
            AtomicElement(tokens[6:7]),
            PunctuationElement(tokens[7:8]),
            AtomicElement(tokens[8:9]),
        ]
    )
    assert set(table.items()) == {('id', 42), ('age', 14)}
    del table['id']
    assert set(table.items()) == {('age', 14)}


class TestPipfileParser:

    def test_inject_environment_variables(self):
        os.environ['PYTEST_PIPFILE_TEST'] = "XYZ"
        p = PipfileParser()

        parsed_dict = p.inject_environment_variables({
            "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
            "another_string": "https://${PYTEST_PIPFILE_TEST}@something.com",
            "nested": {
                "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
                "another_string": "${PYTEST_PIPFILE_TEST}",
            },
            "list": [
                {
                    "a_string": "https://$PYTEST_PIPFILE_TEST@something.com",
                    "another_string": "${PYTEST_PIPFILE_TEST}"
                },
                {},
            ],
            "bool": True,
            "none": None,
        })

        assert parsed_dict["a_string"] == "https://XYZ@something.com"
        assert parsed_dict["another_string"] == "https://XYZ@something.com"
        assert parsed_dict["nested"]["another_string"] == "XYZ"
        assert parsed_dict["list"][0]["a_string"] == "https://XYZ@something.com"
        assert parsed_dict["list"][1] == {}
        assert parsed_dict["bool"] is True
        assert parsed_dict["none"] is None
