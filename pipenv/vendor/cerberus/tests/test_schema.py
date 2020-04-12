# -*- coding: utf-8 -*-

import re

import pytest

from cerberus import Validator, errors, SchemaError
from cerberus.schema import UnvalidatedSchema
from cerberus.tests import assert_schema_error


def test_empty_schema():
    validator = Validator()
    with pytest.raises(SchemaError, match=errors.SCHEMA_ERROR_MISSING):
        validator({}, schema=None)


def test_bad_schema_type(validator):
    schema = "this string should really be dict"
    msg = errors.SCHEMA_ERROR_DEFINITION_TYPE.format(schema)
    with pytest.raises(SchemaError, match=msg):
        validator.schema = schema


def test_bad_schema_type_field(validator):
    field = 'foo'
    schema = {field: {'schema': {'bar': {'type': 'strong'}}}}
    with pytest.raises(SchemaError):
        validator.schema = schema


def test_unknown_rule(validator):
    msg = "{'foo': [{'unknown': ['unknown rule']}]}"
    with pytest.raises(SchemaError, match=re.escape(msg)):
        validator.schema = {'foo': {'unknown': 'rule'}}


def test_unknown_type(validator):
    msg = str({'foo': [{'type': ['Unsupported types: unknown']}]})
    with pytest.raises(SchemaError, match=re.escape(msg)):
        validator.schema = {'foo': {'type': 'unknown'}}


def test_bad_schema_definition(validator):
    field = 'name'
    msg = str({field: ['must be of dict type']})
    with pytest.raises(SchemaError, match=re.escape(msg)):
        validator.schema = {field: 'this should really be a dict'}


def test_bad_of_rules():
    schema = {'foo': {'anyof': {'type': 'string'}}}
    assert_schema_error({}, schema)


def test_normalization_rules_are_invalid_in_of_rules():
    schema = {0: {'anyof': [{'coerce': lambda x: x}]}}
    assert_schema_error({}, schema)


def test_anyof_allof_schema_validate():
    # make sure schema with 'anyof' and 'allof' constraints are checked
    # correctly
    schema = {
        'doc': {'type': 'dict', 'anyof': [{'schema': [{'param': {'type': 'number'}}]}]}
    }
    assert_schema_error({'doc': 'this is my document'}, schema)

    schema = {
        'doc': {'type': 'dict', 'allof': [{'schema': [{'param': {'type': 'number'}}]}]}
    }
    assert_schema_error({'doc': 'this is my document'}, schema)


def test_repr():
    v = Validator({'foo': {'type': 'string'}})
    assert repr(v.schema) == "{'foo': {'type': 'string'}}"


def test_validated_schema_cache():
    v = Validator({'foozifix': {'coerce': int}})
    cache_size = len(v._valid_schemas)

    v = Validator({'foozifix': {'type': 'integer'}})
    cache_size += 1
    assert len(v._valid_schemas) == cache_size

    v = Validator({'foozifix': {'coerce': int}})
    assert len(v._valid_schemas) == cache_size

    max_cache_size = 161
    assert cache_size <= max_cache_size, (
        "There's an unexpected high amount (%s) of cached valid "
        "definition schemas. Unless you added further tests, "
        "there are good chances that something is wrong. "
        "If you added tests with new schemas, you can try to "
        "adjust the variable `max_cache_size` according to "
        "the added schemas." % cache_size
    )


def test_expansion_in_nested_schema():
    schema = {'detroit': {'schema': {'anyof_regex': ['^Aladdin', 'Sane$']}}}
    v = Validator(schema)
    assert v.schema['detroit']['schema'] == {
        'anyof': [{'regex': '^Aladdin'}, {'regex': 'Sane$'}]
    }


def test_unvalidated_schema_can_be_copied():
    schema = UnvalidatedSchema()
    schema_copy = schema.copy()
    assert schema_copy == schema


# TODO remove with next major release
def test_deprecated_rule_names_in_valueschema():
    def check_with(field, value, error):
        pass

    schema = {
        "field_1": {
            "type": "dict",
            "valueschema": {
                "type": "dict",
                "keyschema": {"type": "string"},
                "valueschema": {"type": "string"},
            },
        },
        "field_2": {
            "type": "list",
            "items": [
                {"keyschema": {}},
                {"validator": check_with},
                {"valueschema": {}},
            ],
        },
    }

    validator = Validator(schema)

    assert validator.schema == {
        "field_1": {
            "type": "dict",
            "valuesrules": {
                "type": "dict",
                "keysrules": {"type": "string"},
                "valuesrules": {"type": "string"},
            },
        },
        "field_2": {
            "type": "list",
            "items": [
                {"keysrules": {}},
                {"check_with": check_with},
                {"valuesrules": {}},
            ],
        },
    }


def test_anyof_check_with():
    def foo(field, value, error):
        pass

    def bar(field, value, error):
        pass

    schema = {'field': {'anyof_check_with': [foo, bar]}}
    validator = Validator(schema)

    assert validator.schema == {
        'field': {'anyof': [{'check_with': foo}, {'check_with': bar}]}
    }
