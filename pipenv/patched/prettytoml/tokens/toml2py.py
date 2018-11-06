from __future__ import unicode_literals
import re
import string
import iso8601
from prettytoml import tokens
from prettytoml.tokens import TYPE_BOOLEAN, TYPE_INTEGER, TYPE_FLOAT, TYPE_DATE, \
    TYPE_MULTILINE_STRING, TYPE_BARE_STRING, TYPE_MULTILINE_LITERAL_STRING, TYPE_LITERAL_STRING, \
    TYPE_STRING
import codecs
import six
from prettytoml.tokens.errors import MalformedDateError
from .errors import BadEscapeCharacter
import functools
import operator


def deserialize(token):
    """
    Deserializes the value of a single tokens.Token instance based on its type.

    Raises DeserializationError when appropriate.
    """

    if token.type == TYPE_BOOLEAN:
        return _to_boolean(token)
    elif token.type == TYPE_INTEGER:
        return _to_int(token)
    elif token.type == TYPE_FLOAT:
        return _to_float(token)
    elif token.type == TYPE_DATE:
        return _to_date(token)
    elif token.type in (TYPE_STRING, TYPE_MULTILINE_STRING, TYPE_BARE_STRING,
                        TYPE_LITERAL_STRING, TYPE_MULTILINE_LITERAL_STRING):
        return _to_string(token)
    else:
        raise Exception('This should never happen!')


def _unescape_str(text):
    """
    Unescapes a string according the TOML spec. Raises BadEscapeCharacter when appropriate.
    """
    text = text.decode('utf-8') if isinstance(text, six.binary_type) else text
    tokens = []
    i = 0
    basicstr_re = re.compile(r'[^"\\\000-\037]*')
    unicode_re = re.compile(r'[uU]((?<=u)[a-fA-F0-9]{4}|(?<=U)[a-fA-F0-9]{8})')
    escapes = {
        'b': '\b',
        't': '\t',
        'n': '\n',
        'f': '\f',
        'r': '\r',
        '\\': '\\',
        '"': '"',
        '/': '/',
        "'": "'"
    }
    while True:
        m = basicstr_re.match(text, i)
        i = m.end()
        tokens.append(m.group())
        if i == len(text) or text[i] != '\\':
            break
        else:
            i += 1
        if unicode_re.match(text, i):
            m = unicode_re.match(text, i)
            i = m.end()
            tokens.append(six.unichr(int(m.group(1), 16)))
        else:
            if text[i] not in escapes:
                raise BadEscapeCharacter
            tokens.append(escapes[text[i]])
            i += 1
    return ''.join(tokens)


def _to_string(token):
    if token.type == tokens.TYPE_BARE_STRING:
        return token.source_substring

    elif token.type == tokens.TYPE_STRING:
        escaped = token.source_substring[1:-1]
        return _unescape_str(escaped)

    elif token.type == tokens.TYPE_MULTILINE_STRING:
        escaped = token.source_substring[3:-3]

        # Drop the first newline if existed
        if escaped and escaped[0] == '\n':
            escaped = escaped[1:]

        # Remove all occurrences of a slash-newline-zero-or-more-whitespace patterns
        escaped = re.sub(r'\\\n\s*', repl='', string=escaped, flags=re.DOTALL)
        return _unescape_str(escaped)

    elif token.type == tokens.TYPE_LITERAL_STRING:
        return token.source_substring[1:-1]

    elif token.type == tokens.TYPE_MULTILINE_LITERAL_STRING:
        text = token.source_substring[3:-3]
        if text[0] == '\n':
            text = text[1:]
        return text

    raise RuntimeError('Control should never reach here.')


def _to_int(token):
    return int(token.source_substring.replace('_', ''))


def _to_float(token):
    assert token.type == tokens.TYPE_FLOAT
    string = token.source_substring.replace('_', '')
    return float(string)


def _to_boolean(token):
    return token.source_substring == 'true'


_correct_date_format = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|(\+|-)\d{2}:\d{2})')


def _to_date(token):
    if not _correct_date_format.match(token.source_substring):
        raise MalformedDateError
    return iso8601.parse_date(token.source_substring)
