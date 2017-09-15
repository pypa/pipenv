import datetime

import strict_rfc3339

from prettytoml import tokens
from prettytoml.tokens import py2toml


def test_string():
    assert py2toml.create_string_token('fawzy', bare_string_allowed=True) == tokens.Token(tokens.TYPE_BARE_STRING, 'fawzy')
    assert py2toml.create_primitive_token('I am a "cr\'azy" sentence.') == \
           tokens.Token(tokens.TYPE_STRING, '"I am a \\"cr\'azy\\" sentence."')


def test_multiline_string():
    text = 'The\nSuper\nT"""OML"""\n\nIs coming'

    primitive_token = py2toml.create_primitive_token(text)

    assert primitive_token.source_substring == '"""The\nSuper\nT\"\"\"OML\"\"\"\n\nIs coming"""'


def test_long_string():
    text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Suspendisse faucibus nibh id urna euismod, " \
           "vitae blandit nisi blandit. Nam eu odio ex. Praesent iaculis sapien justo. Proin vehicula orci rhoncus " \
           "risus mattis cursus. Sed quis commodo diam. Morbi dictum fermentum ex. Ut augue lorem, facilisis eu " \
           "posuere ut, ullamcorper et quam. Donec porta neque eget erat lacinia, in convallis elit scelerisque. " \
           "Class aptent taciti sociosqu ad litora torquent per conubia nostra, per inceptos himenaeos. Praesent " \
           "felis metus, venenatis eu aliquam vel, fringilla in turpis. Praesent interdum pulvinar enim, et mattis " \
           "urna dapibus et. Sed ut egestas mauris. Etiam eleifend dui."

    primitive_token = py2toml.create_primitive_token(text)

    assert primitive_token.source_substring[3:-3] == r"""
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Suspendisse \
aucibus nibh id urna euismod, vitae blandit nisi blandit. Nam eu odio ex. \
raesent iaculis sapien justo. Proin vehicula orci rhoncus risus mattis \
ursus. Sed quis commodo diam. Morbi dictum fermentum ex. Ut augue lorem, \
acilisis eu posuere ut, ullamcorper et quam. Donec porta neque eget erat \
acinia, in convallis elit scelerisque. Class aptent taciti sociosqu ad \
itora torquent per conubia nostra, per inceptos himenaeos. Praesent felis \
etus, venenatis eu aliquam vel, fringilla in turpis. Praesent interdum \
ulvinar enim, et mattis urna dapibus et. Sed ut egestas mauris. Etiam \
leifend dui.\
"""


def test_int():
    assert py2toml.create_primitive_token(42) == tokens.Token(tokens.TYPE_INTEGER, '42')


def test_float():
    assert py2toml.create_primitive_token(4.2) == tokens.Token(tokens.TYPE_FLOAT, '4.2')


def test_bool():
    assert py2toml.create_primitive_token(False) == tokens.Token(tokens.TYPE_BOOLEAN, 'false')
    assert py2toml.create_primitive_token(True) == tokens.Token(tokens.TYPE_BOOLEAN, 'true')


def test_date():
    ts = strict_rfc3339.rfc3339_to_timestamp('1979-05-27T00:32:00-07:00')
    dt = datetime.datetime.fromtimestamp(ts)
    assert py2toml.create_primitive_token(dt) == tokens.Token(tokens.TYPE_DATE, '1979-05-27T07:32:00Z')


def test_none():
    t = py2toml.create_primitive_token(None)
    assert t.type == tokens.TYPE_STRING and t.source_substring == '""'
