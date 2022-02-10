from __future__ import absolute_import

from collections import namedtuple

from pipenv.vendor.cerberus.platform import _int_types, _str_type, Mapping, Sequence, Set


TypeDefinition = namedtuple('TypeDefinition', 'name,included_types,excluded_types')
"""
This class is used to define types that can be used as value in the
:attr:`~cerberus.Validator.types_mapping` property.
The ``name`` should be descriptive and match the key it is going to be assigned
to.
A value that is validated against such definition must be an instance of any of
the types contained in ``included_types`` and must not match any of the types
contained in ``excluded_types``.
"""


def compare_paths_lt(x, y):
    min_length = min(len(x), len(y))

    if x[:min_length] == y[:min_length]:
        return len(x) == min_length

    for i in range(min_length):
        a, b = x[i], y[i]

        for _type in (_int_types, _str_type, tuple):
            if isinstance(a, _type):
                if isinstance(b, _type):
                    break
                else:
                    return True

        if a == b:
            continue
        elif a < b:
            return True
        else:
            return False

    raise RuntimeError


def drop_item_from_tuple(t, i):
    return t[:i] + t[i + 1 :]


def get_Validator_class():
    global Validator
    if 'Validator' not in globals():
        from pipenv.vendor.cerberus.validator import Validator
    return Validator


def mapping_hash(schema):
    return hash(mapping_to_frozenset(schema))


def mapping_to_frozenset(mapping):
    """
    Be aware that this treats any sequence type with the equal members as equal. As it
    is used to identify equality of schemas, this can be considered okay as definitions
    are semantically equal regardless the container type.
    """

    aggregation = {}

    for key, value in mapping.items():
        if isinstance(value, Mapping):
            aggregation[key] = mapping_to_frozenset(value)
        elif isinstance(value, Sequence):
            value = list(value)
            for i, item in enumerate(value):
                if isinstance(item, Mapping):
                    value[i] = mapping_to_frozenset(item)
            aggregation[key] = tuple(value)
        elif isinstance(value, Set):
            aggregation[key] = frozenset(value)
        else:
            aggregation[key] = value

    return frozenset(aggregation.items())


def quote_string(value):
    if isinstance(value, _str_type):
        return '"%s"' % value
    else:
        return value


class readonly_classproperty(property):
    def __get__(self, instance, owner):
        return super(readonly_classproperty, self).__get__(owner)

    def __set__(self, instance, value):
        raise RuntimeError('This is a readonly class property.')

    def __delete__(self, instance):
        raise RuntimeError('This is a readonly class property.')


def validator_factory(name, bases=None, namespace={}):
    """
    Dynamically create a :class:`~cerberus.Validator` subclass.
    Docstrings of mixin-classes will be added to the resulting class' one if ``__doc__``
    is not in :obj:`namespace`.

    :param name: The name of the new class.
    :type name: :class:`str`
    :param bases: Class(es) with additional and overriding attributes.
    :type bases: :class:`tuple` of or a single :term:`class`
    :param namespace: Attributes for the new class.
    :type namespace: :class:`dict`
    :return: The created class.
    """
    Validator = get_Validator_class()

    if bases is None:
        bases = (Validator,)
    elif isinstance(bases, tuple):
        bases += (Validator,)
    else:
        bases = (bases, Validator)

    docstrings = [x.__doc__ for x in bases if x.__doc__]
    if len(docstrings) > 1 and '__doc__' not in namespace:
        namespace.update({'__doc__': '\n'.join(docstrings)})

    return type(name, bases, namespace)
