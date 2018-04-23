from prettytoml import lexer, parser
from contoml.file import toplevels
from prettytoml.parser import elementsanitizer
from contoml.file.structurer import NamedDict, structure
from prettytoml.parser.tokenstream import TokenStream


def test_NamedDict():

    d = NamedDict()

    d[toplevels.Name(('super', 'sub1', 'sub2'))] = {'sub3': 12}
    d[toplevels.Name(('super', 'sub1', 'sub2'))]['sub4'] = 42

    assert d[toplevels.Name(('super', 'sub1', 'sub2', 'sub3'))] == 12
    assert d[toplevels.Name(('super', 'sub1', 'sub2', 'sub4'))] == 42


def test_structure():
    tokens = lexer.tokenize(open('sample.toml').read())
    elements = elementsanitizer.sanitize(parser.parse_tokens(tokens))
    entries_ = tuple(toplevels.identify(elements))

    s = structure(entries_)

    assert s['']['title'] == 'TOML Example'
    assert s['owner']['name'] == 'Tom Preston-Werner'
    assert s['database']['ports'][1] == 8001
    assert s['servers']['alpha']['dc'] == 'eqdc10'
    assert s['clients']['data'][1][0] == 1
    assert s['clients']['key3'] == 'The quick brown fox jumps over the lazy dog.'

    assert s['fruit'][0]['name'] == 'apple'
    assert s['fruit'][0]['physical']['color'] == 'red'
    assert s['fruit'][0]['physical']['shape'] == 'round'
    assert s['fruit'][0]['variety'][0]['name'] == 'red delicious'
    assert s['fruit'][0]['variety'][1]['name'] == 'granny smith'

    assert s['fruit'][1]['name'] == 'banana'
    assert s['fruit'][1]['variety'][0]['name'] == 'plantain'
    assert s['fruit'][1]['variety'][0]['points'][2]['y'] == 4
