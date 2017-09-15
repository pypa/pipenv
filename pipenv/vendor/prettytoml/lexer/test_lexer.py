# -*- coding: utf-8 -*-

from prettytoml.lexer import _munch_a_token
from prettytoml.lexer import *

# A mapping from token types to a sequence of pairs of (source_text, expected_matched_text)
valid_tokens = {
    tokens.TYPE_COMMENT: (
        (
            '# My very insightful comment about the state of the universe\n# And now for something completely different!',
            '# My very insightful comment about the state of the universe',
        ),
    ),
    tokens.TYPE_STRING: (
        ('"a valid hug3 text" "some other string" = 42', '"a valid hug3 text"'),
        (
            r'"I\'m a string. \"You can quote me\". Name\tJos\u00E9\nLocation\tSF." "some other string" = 42',
            r'"I\'m a string. \"You can quote me\". Name\tJos\u00E9\nLocation\tSF."'
        ),
        ('"ʎǝʞ" key', '"ʎǝʞ"'),
        ('""', '""'),
        ('"t"', '"t"'),
    ),
    tokens.TYPE_MULTILINE_STRING: (
        ('"""\nRoses are red\nViolets are blue""" """other text"""', '"""\nRoses are red\nViolets are blue"""'),
    ),
    tokens.TYPE_LITERAL_STRING: (
        (r"'This is \ \n a \\ literal string' 'another \ literal string'", r"'This is \ \n a \\ literal string'"),
    ),
    tokens.TYPE_MULTILINE_LITERAL_STRING: (
        (
            "'''\nThe first newline is\ntrimmed in raw strings.\n   All other whitespace\n   is preserved.\n''' '''some other\n\n\t string'''",
            "'''\nThe first newline is\ntrimmed in raw strings.\n   All other whitespace\n   is preserved.\n'''"
        ),
    ),
    tokens.TYPE_DATE: (
        ('1979-05-27 5345', '1979-05-27'),
        ('1979-05-27T07:32:00Z something', '1979-05-27T07:32:00Z'),
        ('1979-05-27T00:32:00-07:00 ommm', '1979-05-27T00:32:00-07:00'),
        ('1979-05-27T00:32:00.999999-07:00 2346', '1979-05-27T00:32:00.999999-07:00'),
    ),
    tokens.TYPE_WHITESPACE: (
        (' \t\n \r  some_text', ' '),
    ),
    tokens.TYPE_INTEGER: (
        ('+99 "number"', "+99"),
        ('42 fwfwef', "42"),
        ('-17 fh34g34g', "-17"),
        ('5_349_221 apples', "5_349_221"),
        ('-1_2_3_4_5 steps', '-1_2_3_4_5')
    ),
    tokens.TYPE_FLOAT: (
        ('1.0 fwef', '1.0'),
        ('3.1415 g4g', '3.1415'),
        ('-0.01 433re', '-0.01'),
        ('5e+2_2 ersdvf', '5e+2_2'),
        ('1e6 ewe23', '1e6'),
        ('-2E-2.2 3 rf23', '-2E-2'),
        ('6.626e-34 +234f', '6.626e-34'),
        ('9_224_617.445_991_228_313 f1ewer 23f4h = nonesense', '9_224_617.445_991_228_313'),
        ('1e1_000 2346f,ef2!!', '1e1_000'),
    ),
    tokens.TYPE_BOOLEAN: (
        ('false business = true', 'false'),
        ('true true', 'true'),
    ),
    tokens.TYPE_OP_SQUARE_LEFT_BRACKET: (
        ('[table_name]', '['),
    ),
    tokens.TYPE_OP_SQUARE_RIGHT_BRACKET: (
        (']\nbusiness = awesome', ']'),
    ),
    tokens.TYPE_OP_CURLY_LEFT_BRACKET: (
        ('{item_exists = no}', '{'),
    ),
    tokens.TYPE_OP_CURLY_RIGHT_BRACKET: (
        ('} moving on', '}'),
    ),
    tokens.TYPE_OP_COMMA: (
        (',item2,item4', ','),
    ),
    tokens.TYPE_OP_ASSIGNMENT: (
        ('== 42', '='),
    ),
    tokens.TYPE_OP_DOUBLE_SQUARE_LEFT_BRACKET: (
        ('[[array.of.tables]]', '[['),
    ),
    tokens.TYPE_OP_DOUBLE_SQUARE_RIGHT_BRACKET: (
        (']] item=3', ']]'),
    ),
    tokens.TYPE_BARE_STRING: (
        ('key another', 'key'),
        ('bare_key 2fews', 'bare_key'),
        ('bare-key kfcw', 'bare-key'),
    ),
    tokens.TYPE_OPT_DOT: (
        ('."another key"', '.'),
        ('.subname', '.'),
    ),
    tokens.TYPE_NEWLINE: (
        ('\n\r \n', '\n'),
    )
}

# A mapping from a token type to a sequence of (source, matched_text) pairs that shouldn't result from consuming the
# source text.
invalid_tokens = {
    tokens.TYPE_INTEGER: (
        ('_234_423', ''),
        ('0446234234', ''),
    ),
    tokens.TYPE_STRING: (
        ('"""', '"""'),
    ),
    tokens.TYPE_BOOLEAN: (
        ('True', 'True'),
        ('True', 'true'),
    ),
    tokens.TYPE_FLOAT: (
        ('', ''),
    )
}


def test_valid_tokenizing():
    for token_type in valid_tokens:
        for (source, expected_match) in valid_tokens[token_type]:

            token = _munch_a_token(source)
            assert token, "Failed to tokenize: {}\nExpected: {}\nOut of: {}\nGot nothing!".format(
                token_type, expected_match, source)

            assert token.type == token_type, \
                "Expected type: {}\nOut of: {}\nThat matched: {}\nOf type: {}".format(
                    token_type, source, token.source_substring, token.type)
            assert token.source_substring == expected_match


def test_invalid_tokenizing():
    for token_type in invalid_tokens:
        for source, expected_match in invalid_tokens[token_type]:
            token = _munch_a_token(source)
            if token:
                assert not (token.type == token_type and token.source_substring == expected_match)


def test_token_type_order():
    type_a = tokens.TokenType('a', 5, is_metadata=False)
    type_b = tokens.TokenType('b', 0, is_metadata=False)
    type_c = tokens.TokenType('c', 3, is_metadata=False)

    assert type_b < type_c < type_a
    assert type_a > type_c > type_b
