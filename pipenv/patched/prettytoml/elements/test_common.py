from prettytoml import tokens, lexer
from prettytoml.elements import traversal
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.metadata import NewlineElement, PunctuationElement, WhitespaceElement, CommentElement
from prettytoml.elements.table import TableElement
from prettytoml.elements.tableheader import TableHeaderElement

atomic_token_types = (
    tokens.TYPE_INTEGER,
    tokens.TYPE_FLOAT,
    tokens.TYPE_BARE_STRING,
    tokens.TYPE_STRING,
    tokens.TYPE_LITERAL_STRING,
    tokens.TYPE_MULTILINE_STRING,
    tokens.TYPE_MULTILINE_LITERAL_STRING,
)

punctuation_token_types = (
    tokens.TYPE_OPT_DOT,
    tokens.TYPE_OP_CURLY_LEFT_BRACKET,
    tokens.TYPE_OP_SQUARE_LEFT_BRACKET,
    tokens.TYPE_OP_DOUBLE_SQUARE_LEFT_BRACKET,
    tokens.TYPE_OP_SQUARE_RIGHT_BRACKET,
    tokens.TYPE_OP_CURLY_RIGHT_BRACKET,
    tokens.TYPE_OP_DOUBLE_SQUARE_RIGHT_BRACKET,
    tokens.TYPE_OP_ASSIGNMENT,
)

def primitive_token_to_primitive_element(token):
    if token.type == tokens.TYPE_NEWLINE:
        return NewlineElement((token,))
    elif token.type in atomic_token_types:
        return AtomicElement((token,))
    elif token.type == tokens.TYPE_NEWLINE:
        return NewlineElement((token,))
    elif token.type in punctuation_token_types:
        return PunctuationElement((token,))
    elif token.type == tokens.TYPE_WHITESPACE:
        return WhitespaceElement((token,))
    elif token.type == tokens.TYPE_COMMENT:
        return CommentElement((token,))
    else:
        raise RuntimeError("{} has no mapped primitive element".format(token))


def primitive_tokens_to_primitive_elements(tokens):
    return list(map(primitive_token_to_primitive_element, tokens))


def dummy_file_elements():
        tokens_ = tuple(lexer.tokenize("""
name = fawzy
another_name=another_fawzy

[details]
id= 42
section =fourth

[[person]]
personname= lefawzy
dest=north

[[person]]
dest=south
personname=lafawzy

[details.extended]
number = 313
type =complex"""))

        elements = \
            [TableElement(primitive_tokens_to_primitive_elements(tokens_[:12]))] + \
            [TableHeaderElement(tokens_[12:16])] + \
            [TableElement(primitive_tokens_to_primitive_elements(tokens_[16:25]))] + \
            [TableHeaderElement(tokens_[25:31])] + \
            [TableElement(primitive_tokens_to_primitive_elements(tokens_[31:39]))] + \
            [TableHeaderElement(tokens_[39:45])] + \
            [TableElement(primitive_tokens_to_primitive_elements(tokens_[45:53]))] + \
            [TableHeaderElement(tokens_[53:60])] + \
            [TableElement(primitive_tokens_to_primitive_elements(tokens_[60:]))]

        return elements


class DummyFile(traversal.TraversalMixin):

    @property
    def elements(self):
        return dummy_file_elements()
