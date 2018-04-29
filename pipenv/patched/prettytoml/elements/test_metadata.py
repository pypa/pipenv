from prettytoml import lexer
from prettytoml.elements.metadata import WhitespaceElement, NewlineElement, CommentElement, PunctuationElement


def test_whitespace_element():
    element = WhitespaceElement(tuple(lexer.tokenize(' \t   ')))
    assert element.serialized() == ' \t   '


def test_newline_element():
    element = NewlineElement(tuple(lexer.tokenize('\n\n\n')))
    assert element.serialized() == '\n\n\n'


def test_comment_element():
    element = CommentElement(tuple(lexer.tokenize('# This is my insightful remark\n')))
    assert element.serialized() == '# This is my insightful remark\n'


def test_punctuation_element():
    PunctuationElement(tuple(lexer.tokenize('[')))
    PunctuationElement(tuple(lexer.tokenize('[[')))
    PunctuationElement(tuple(lexer.tokenize('.')))
    PunctuationElement(tuple(lexer.tokenize(']')))
    PunctuationElement(tuple(lexer.tokenize(']]')))
