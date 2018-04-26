# We need to import the patched packages directly from sys.path, so the
# identity checks can pass.
import pipenv  # noqa

import datetime
import os

import pytest
import pytz

from pipfile.api import PipfileParser
from prettytoml import lexer, tokens
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import (
    WhitespaceElement, PunctuationElement, CommentElement
)
from prettytoml.elements.table import TableElement
from prettytoml.tokens.py2toml import create_primitive_token


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


@pytest.mark.parametrize('dt, content', [
    (   # Date.
        datetime.date(1992, 8, 19),
        '1992-08-19',
    ),
    (   # Naive time.
        datetime.time(15, 10),
        '15:10:00',
    ),
    (   # Aware time in UTC.
        datetime.time(15, 10, tzinfo=pytz.UTC),
        '15:10:00Z',
    ),
    (   # Aware local time.
        datetime.time(15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
        '15:10:00+08:00',
    ),
    (   # Naive datetime.
        datetime.datetime(1992, 8, 19, 15, 10),
        '1992-08-19T15:10:00',
    ),
    (   # Aware datetime in UTC.
        datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.UTC),
        '1992-08-19T15:10:00Z',
    ),
    (   # Aware local datetime.
        datetime.datetime(1992, 8, 19, 15, 10, tzinfo=pytz.FixedOffset(8 * 60)),
        '1992-08-19T15:10:00+08:00',
    ),
])
def test_token_date(dt, content):
    token = create_primitive_token(dt)
    assert token == tokens.Token(tokens.TYPE_DATE, content)
