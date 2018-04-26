from ._version import VERSION

__version__ = VERSION


def loads(text):
    """
    Parses TOML text into a dict-like object and returns it.
    """
    from prettytoml.parser import parse_tokens
    from prettytoml.lexer import tokenize as lexer
    from .file import TOMLFile

    tokens = tuple(lexer(text, is_top_level=True))
    elements = parse_tokens(tokens)
    return TOMLFile(elements)


def load(file_path):
    """
    Parses a TOML file into a dict-like object and returns it.
    """
    return loads(open(file_path).read())


def dumps(value):
    """
    Dumps a data structure to TOML source code.

    The given value must be either a dict of dict values, a dict, or a TOML file constructed by this module.
    """

    from contoml.file.file import TOMLFile

    if not isinstance(value, TOMLFile):
        raise RuntimeError("Can only dump a TOMLFile instance loaded by load() or loads()")

    return value.dumps()


def dump(obj, file_path, prettify=False):
    """
    Dumps a data structure to the filesystem as TOML.

    The given value must be either a dict of dict values, a dict, or a TOML file constructed by this module.
    """
    with open(file_path, 'w') as fp:
        fp.write(dumps(obj))
