from contoml.file.cascadedict import CascadeDict


def test_cascadedict():

    d1 = {'a': 1, 'b': 2, 'c': 3}
    d2 = {'b': 12, 'e': 4, 'f': 5}

    cascade = CascadeDict(d1, d2)

    # Test querying
    assert cascade['a'] == 1
    assert cascade['b'] == 2
    assert cascade['c'] == 3
    assert cascade['e'] == 4
    assert cascade.keys() == {'a', 'b', 'c', 'e', 'f'}
    assert set(cascade.items()) == {('a', 1), ('b', 2), ('c', 3), ('e', 4), ('f', 5)}

    # Test mutating
    cascade['a'] = 11
    cascade['f'] = 'fff'
    cascade['super'] = 'man'
    assert d1['a'] == 11
    assert d1['super'] == 'man'
    assert d1['f'] == 'fff'
