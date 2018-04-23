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

    # Detect bad escape jobs
    bad_escape_regexp = re.compile(r'([^\\]|^)\\[^btnfr"\\uU]')
    if bad_escape_regexp.findall(text):
        raise BadEscapeCharacter

    # Do the unescaping
    if six.PY2:
        return _unicode_escaped_string(text).decode('string-escape').decode('unicode-escape')
    else:
        return codecs.decode(_unicode_escaped_string(text), 'unicode-escape')


def _unicode_escaped_string(text):
    """
    Escapes all unicode characters in the given string
    """

    if six.PY2:
        text = unicode(text)

    def is_unicode(c):
        return c.lower() not in string.ascii_letters + string.whitespace + string.punctuation + string.digits

    def escape_unicode_char(x):
        if six.PY2:
            return x.encode('unicode-escape')
        else:
            return codecs.encode(x, 'unicode-escape')

    if any(is_unicode(c) for c in text):
        homogeneous_chars = tuple(escape_unicode_char(c) if is_unicode(c) else c.encode() for c in text)
        homogeneous_bytes = functools.reduce(operator.add, homogeneous_chars)
        return homogeneous_bytes.decode()
    else:
        return text


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
