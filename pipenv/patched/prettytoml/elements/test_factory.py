from collections import OrderedDict
from prettytoml.elements import factory
from prettytoml.elements.array import ArrayElement
from prettytoml.elements.atomic import AtomicElement
from prettytoml.elements.inlinetable import InlineTableElement


def test_creating_elements():

    atomic = factory.create_element(42)
    assert isinstance(atomic, AtomicElement)
    assert atomic.value == 42

    seq = factory.create_element(['a', 'p', 'p', 'l', 'e'])
    assert isinstance(seq, ArrayElement)
    assert seq.serialized() == '["a", "p", "p", "l", "e"]'
    assert ''.join(seq.primitive_value) == 'apple'

    mapping = factory.create_element(OrderedDict((('one', 1), ('two', 2))))
    assert isinstance(mapping, InlineTableElement)
    assert mapping.serialized() == '{one = 1, two = 2}'

