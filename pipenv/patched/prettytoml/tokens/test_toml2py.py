from datetime import datetime

import pytz

from prettytoml import tokens
from prettytoml.tokens import toml2py
from prettytoml.tokens.errors import BadEscapeCharacter, DeserializationError


def test_integer():
    t1 = tokens.Token(tokens.TYPE_INTEGER, '42')
    t2 = tokens.Token(tokens.TYPE_INTEGER, '1_001_2')

    assert toml2py.deserialize(t1) == 42
    assert toml2py.deserialize(t2) == 10012


def test_float():
    tokens_and_values = (
        ('4.2', 4.2),
        ('12e2', 12e2),
        ('1_000e2', 1e5),
        ('314.1e-2', 3.141)
    )
    for token_string, value in tokens_and_values:
        token = tokens.Token(tokens.TYPE_FLOAT, token_string)
        assert toml2py.deserialize(token) == value


def test_string():

    t0 = tokens.Token(tokens.TYPE_BARE_STRING, 'fawzy')
    assert toml2py.deserialize(t0) == 'fawzy'

    t1 = tokens.Token(tokens.TYPE_STRING, '"I\'m a string. \\"You can quote me\\". Name\\tJos\\u00E9\\nLocation\\tSF."')
    assert toml2py.deserialize(t1) == u'I\'m a string. "You can quote me". Name\tJos\xe9\nLocation\tSF.'

    t2 = tokens.Token(tokens.TYPE_MULTILINE_STRING, '"""\nRoses are red\nViolets are blue"""')
    assert toml2py.deserialize(t2) == 'Roses are red\nViolets are blue'

    t3_str = '"""\nThe quick brown \\\n\n\n  fox jumps over \\\n    the lazy dog."""'
    t3 = tokens.Token(tokens.TYPE_MULTILINE_STRING, t3_str)
    assert toml2py.deserialize(t3) == 'The quick brown fox jumps over the lazy dog.'

    t4_str = '"""\\\n       The quick brown \\\n       fox jumps over \\\n       the lazy dog.\\\n       """'
    t4 = tokens.Token(tokens.TYPE_MULTILINE_STRING, t4_str)
    assert toml2py.deserialize(t4) == 'The quick brown fox jumps over the lazy dog.'

    t5 = tokens.Token(tokens.TYPE_LITERAL_STRING, r"'C:\Users\nodejs\templates'")
    assert toml2py.deserialize(t5) == r'C:\Users\nodejs\templates'

    t6_str = "'''\nThe first newline is\ntrimmed in raw strings.\n   All other whitespace\n   is preserved.\n'''"
    t6 = tokens.Token(tokens.TYPE_MULTILINE_LITERAL_STRING, t6_str)
    assert toml2py.deserialize(t6) == 'The first newline is\ntrimmed in raw strings.\n   All' \
                                      ' other whitespace\n   is preserved.\n'


def test_date():
    t0 = tokens.Token(tokens.TYPE_DATE, '1979-05-27T07:32:00Z')
    assert toml2py.deserialize(t0) == datetime(1979, 5, 27, 7, 32, tzinfo=pytz.utc)

    t1 = tokens.Token(tokens.TYPE_DATE, '1979-05-27T00:32:00-07:00')
    assert toml2py.deserialize(t1) == datetime(1979, 5, 27, 7, 32, tzinfo=pytz.utc)

    t3 = tokens.Token(tokens.TYPE_DATE, '1987-07-05T17:45:00')
    try:
        toml2py.deserialize(t3)
        assert False, 'Should detect malformed date'
    except DeserializationError:
        pass


def test_unescaping_a_string():

    bad_escapes = (
        r"This string has a bad \a escape character.",
        r'\x33',
    )

    for source in bad_escapes:
        # Should complain about bad escape jobs
        try:
            toml2py._unescape_str(source)
            assert False, "Should have thrown an exception for: " + source
        except BadEscapeCharacter:
            pass
