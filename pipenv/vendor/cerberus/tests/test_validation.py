# -*- coding: utf-8 -*-

import re
import sys
from datetime import datetime, date
from random import choice
from string import ascii_lowercase

from pytest import mark

from cerberus import errors, Validator
from cerberus.tests import (
    assert_bad_type, assert_document_error, assert_fail, assert_has_error,
    assert_not_has_error, assert_success
)
from cerberus.tests.conftest import sample_schema


def test_empty_document():
    assert_document_error(None, sample_schema, None,
                          errors.DOCUMENT_MISSING)


def test_bad_document_type():
    document = "not a dict"
    assert_document_error(
        document, sample_schema, None,
        errors.DOCUMENT_FORMAT.format(document)
    )


def test_unknown_field(validator):
    field = 'surname'
    assert_fail({field: 'doe'}, validator=validator,
                error=(field, (), errors.UNKNOWN_FIELD, None))
    assert validator.errors == {field: ['unknown field']}


def test_empty_field_definition(document):
    field = 'name'
    schema = {field: {}}
    assert_success(document, schema)


def test_required_field(schema):
    field = 'a_required_string'
    required_string_extension = {
        'a_required_string': {'type': 'string',
                              'minlength': 2,
                              'maxlength': 10,
                              'required': True}}
    schema.update(required_string_extension)
    assert_fail({'an_integer': 1}, schema,
                error=(field, (field, 'required'), errors.REQUIRED_FIELD,
                       True))


def test_nullable_field():
    assert_success({'a_nullable_integer': None})
    assert_success({'a_nullable_integer': 3})
    assert_success({'a_nullable_field_without_type': None})
    assert_fail({'a_nullable_integer': "foo"})
    assert_fail({'an_integer': None})
    assert_fail({'a_not_nullable_field_without_type': None})


def test_readonly_field():
    field = 'a_readonly_string'
    assert_fail({field: 'update me if you can'},
                error=(field, (field, 'readonly'), errors.READONLY_FIELD, True))


def test_readonly_field_first_rule():
    # test that readonly rule is checked before any other rule, and blocks.
    # See #63.
    schema = {
        'a_readonly_number': {
            'type': 'integer',
            'readonly': True,
            'max': 1
        }
    }
    v = Validator(schema)
    v.validate({'a_readonly_number': 2})
    # it would be a list if there's more than one error; we get a dict
    # instead.
    assert 'read-only' in v.errors['a_readonly_number'][0]


def test_readonly_field_with_default_value():
    schema = {
        'created': {
            'type': 'string',
            'readonly': True,
            'default': 'today'
        },
        'modified': {
            'type': 'string',
            'readonly': True,
            'default_setter': lambda d: d['created']
        }
    }
    assert_success({}, schema)
    expected_errors = [('created', ('created', 'readonly'),
                        errors.READONLY_FIELD,
                        schema['created']['readonly']),
                       ('modified', ('modified', 'readonly'),
                        errors.READONLY_FIELD,
                        schema['modified']['readonly'])]
    assert_fail({'created': 'tomorrow', 'modified': 'today'},
                schema, errors=expected_errors)
    assert_fail({'created': 'today', 'modified': 'today'},
                schema, errors=expected_errors)


def test_nested_readonly_field_with_default_value():
    schema = {
        'some_field': {
            'type': 'dict',
            'schema': {
                'created': {
                    'type': 'string',
                    'readonly': True,
                    'default': 'today'
                },
                'modified': {
                    'type': 'string',
                    'readonly': True,
                    'default_setter': lambda d: d['created']
                }
            }
        }
    }
    assert_success({'some_field': {}}, schema)
    expected_errors = [
        (('some_field', 'created'),
         ('some_field', 'schema', 'created', 'readonly'),
         errors.READONLY_FIELD,
         schema['some_field']['schema']['created']['readonly']),
        (('some_field', 'modified'),
         ('some_field', 'schema', 'modified', 'readonly'),
         errors.READONLY_FIELD,
         schema['some_field']['schema']['modified']['readonly'])]
    assert_fail({'some_field': {'created': 'tomorrow', 'modified': 'now'}},
                schema, errors=expected_errors)
    assert_fail({'some_field': {'created': 'today', 'modified': 'today'}},
                schema, errors=expected_errors)


def test_repeated_readonly(validator):
    # https://github.com/pyeve/cerberus/issues/311
    validator.schema = {'id': {'readonly': True}}
    assert_fail({'id': 0}, validator=validator)
    assert_fail({'id': 0}, validator=validator)


def test_not_a_string():
    assert_bad_type('a_string', 'string', 1)


def test_not_a_binary():
    # 'u' literal prefix produces type `str` in Python 3
    assert_bad_type('a_binary', 'binary', u"i'm not a binary")


def test_not_a_integer():
    assert_bad_type('an_integer', 'integer', "i'm not an integer")


def test_not_a_boolean():
    assert_bad_type('a_boolean', 'boolean', "i'm not a boolean")


def test_not_a_datetime():
    assert_bad_type('a_datetime', 'datetime', "i'm not a datetime")


def test_not_a_float():
    assert_bad_type('a_float', 'float', "i'm not a float")


def test_not_a_number():
    assert_bad_type('a_number', 'number', "i'm not a number")


def test_not_a_list():
    assert_bad_type('a_list_of_values', 'list', "i'm not a list")


def test_not_a_dict():
    assert_bad_type('a_dict', 'dict', "i'm not a dict")


def test_bad_max_length(schema):
    field = 'a_string'
    max_length = schema[field]['maxlength']
    value = "".join(choice(ascii_lowercase) for i in range(max_length + 1))
    assert_fail({field: value},
                error=(field, (field, 'maxlength'), errors.MAX_LENGTH,
                       max_length, (len(value),)))


def test_bad_max_length_binary(schema):
    field = 'a_binary'
    max_length = schema[field]['maxlength']
    value = b'\x00' * (max_length + 1)
    assert_fail({field: value},
                error=(field, (field, 'maxlength'), errors.MAX_LENGTH,
                       max_length, (len(value),)))


def test_bad_min_length(schema):
    field = 'a_string'
    min_length = schema[field]['minlength']
    value = "".join(choice(ascii_lowercase) for i in range(min_length - 1))
    assert_fail({field: value},
                error=(field, (field, 'minlength'), errors.MIN_LENGTH,
                       min_length, (len(value),)))


def test_bad_min_length_binary(schema):
    field = 'a_binary'
    min_length = schema[field]['minlength']
    value = b'\x00' * (min_length - 1)
    assert_fail({field: value},
                error=(field, (field, 'minlength'), errors.MIN_LENGTH,
                       min_length, (len(value),)))


def test_bad_max_value(schema):
    def assert_bad_max_value(field, inc):
        max_value = schema[field]['max']
        value = max_value + inc
        assert_fail({field: value},
                    error=(field, (field, 'max'), errors.MAX_VALUE, max_value))

    field = 'an_integer'
    assert_bad_max_value(field, 1)
    field = 'a_float'
    assert_bad_max_value(field, 1.0)
    field = 'a_number'
    assert_bad_max_value(field, 1)


def test_bad_min_value(schema):
    def assert_bad_min_value(field, inc):
        min_value = schema[field]['min']
        value = min_value - inc
        assert_fail({field: value},
                    error=(field, (field, 'min'),
                           errors.MIN_VALUE, min_value))

    field = 'an_integer'
    assert_bad_min_value(field, 1)
    field = 'a_float'
    assert_bad_min_value(field, 1.0)
    field = 'a_number'
    assert_bad_min_value(field, 1)


def test_bad_schema():
    field = 'a_dict'
    subschema_field = 'address'
    schema = {field: {'type': 'dict',
                      'schema': {subschema_field: {'type': 'string'},
                                 'city': {'type': 'string', 'required': True}}
                      }}
    document = {field: {subschema_field: 34}}
    validator = Validator(schema)

    assert_fail(
        document, validator=validator,
        error=(field, (field, 'schema'), errors.MAPPING_SCHEMA,
               validator.schema['a_dict']['schema']),
        child_errors=[
            ((field, subschema_field),
             (field, 'schema', subschema_field, 'type'),
             errors.BAD_TYPE, 'string'),
            ((field, 'city'), (field, 'schema', 'city', 'required'),
             errors.REQUIRED_FIELD, True)]
    )

    handler = errors.BasicErrorHandler
    assert field in validator.errors
    assert subschema_field in validator.errors[field][-1]
    assert handler.messages[errors.BAD_TYPE.code].format(constraint='string') \
        in validator.errors[field][-1][subschema_field]
    assert 'city' in validator.errors[field][-1]
    assert (handler.messages[errors.REQUIRED_FIELD.code]
            in validator.errors[field][-1]['city'])


def test_bad_valueschema():
    field = 'a_dict_with_valueschema'
    schema_field = 'a_string'
    value = {schema_field: 'not an integer'}

    exp_child_errors = [
        ((field, schema_field), (field, 'valueschema', 'type'), errors.BAD_TYPE,
         'integer')]
    assert_fail({field: value},
                error=(field, (field, 'valueschema'), errors.VALUESCHEMA,
                       {'type': 'integer'}), child_errors=exp_child_errors)


def test_bad_list_of_values(validator):
    field = 'a_list_of_values'
    value = ['a string', 'not an integer']
    assert_fail({field: value}, validator=validator,
                error=(field, (field, 'items'), errors.BAD_ITEMS,
                       [{'type': 'string'}, {'type': 'integer'}]),
                child_errors=[((field, 1), (field, 'items', 1, 'type'),
                               errors.BAD_TYPE, 'integer')])

    assert (errors.BasicErrorHandler.messages[errors.BAD_TYPE.code].
            format(constraint='integer')
            in validator.errors[field][-1][1])

    value = ['a string', 10, 'an extra item']
    assert_fail({field: value},
                error=(field, (field, 'items'), errors.ITEMS_LENGTH,
                       [{'type': 'string'}, {'type': 'integer'}], (2, 3)))


def test_bad_list_of_integers():
    field = 'a_list_of_integers'
    value = [34, 'not an integer']
    assert_fail({field: value})


def test_bad_list_of_dicts():
    field = 'a_list_of_dicts'
    map_schema = {'sku': {'type': 'string'},
                  'price': {'type': 'integer', 'required': True}}
    seq_schema = {'type': 'dict', 'schema': map_schema}
    schema = {field: {'type': 'list', 'schema': seq_schema}}
    validator = Validator(schema)
    value = [{'sku': 'KT123', 'price': '100'}]
    document = {field: value}

    assert_fail(document, validator=validator,
                error=(field, (field, 'schema'), errors.SEQUENCE_SCHEMA,
                       seq_schema),
                child_errors=[((field, 0), (field, 'schema', 'schema'),
                               errors.MAPPING_SCHEMA, map_schema)])

    assert field in validator.errors
    assert 0 in validator.errors[field][-1]
    assert 'price' in validator.errors[field][-1][0][-1]
    exp_msg = errors.BasicErrorHandler.messages[errors.BAD_TYPE.code] \
        .format(constraint='integer')
    assert exp_msg in validator.errors[field][-1][0][-1]['price']

    value = ["not a dict"]
    exp_child_errors = [((field, 0), (field, 'schema', 'type'),
                         errors.BAD_TYPE, 'dict', ())]
    assert_fail({field: value},
                error=(field, (field, 'schema'), errors.SEQUENCE_SCHEMA,
                       seq_schema),
                child_errors=exp_child_errors)


def test_array_unallowed():
    field = 'an_array'
    value = ['agent', 'client', 'profit']
    assert_fail({field: value},
                error=(field, (field, 'allowed'), errors.UNALLOWED_VALUES,
                       ['agent', 'client', 'vendor'], ['profit']))


def test_string_unallowed():
    field = 'a_restricted_string'
    value = 'profit'
    assert_fail({field: value},
                error=(field, (field, 'allowed'), errors.UNALLOWED_VALUE,
                       ['agent', 'client', 'vendor'], value))


def test_integer_unallowed():
    field = 'a_restricted_integer'
    value = 2
    assert_fail({field: value},
                error=(field, (field, 'allowed'), errors.UNALLOWED_VALUE,
                       [-1, 0, 1], value))


def test_integer_allowed():
    assert_success({'a_restricted_integer': -1})


def test_validate_update():
    assert_success({'an_integer': 100,
                    'a_dict': {'address': 'adr'},
                    'a_list_of_dicts': [{'sku': 'let'}]
                    }, update=True)


def test_string():
    assert_success({'a_string': 'john doe'})


def test_string_allowed():
    assert_success({'a_restricted_string': 'client'})


def test_integer():
    assert_success({'an_integer': 50})


def test_boolean():
    assert_success({'a_boolean': True})


def test_datetime():
    assert_success({'a_datetime': datetime.now()})


def test_float():
    assert_success({'a_float': 3.5})
    assert_success({'a_float': 1})


def test_number():
    assert_success({'a_number': 3.5})
    assert_success({'a_number': 3})


def test_array():
    assert_success({'an_array': ['agent', 'client']})


def test_set():
    assert_success({'a_set': set(['hello', 1])})


def test_one_of_two_types(validator):
    field = 'one_or_more_strings'
    assert_success({field: 'foo'})
    assert_success({field: ['foo', 'bar']})
    exp_child_errors = [((field, 1), (field, 'schema', 'type'),
                         errors.BAD_TYPE, 'string')]
    assert_fail({field: ['foo', 23]}, validator=validator,
                error=(field, (field, 'schema'), errors.SEQUENCE_SCHEMA,
                       {'type': 'string'}),
                child_errors=exp_child_errors)
    assert_fail({field: 23},
                error=((field,), (field, 'type'), errors.BAD_TYPE,
                       ['string', 'list']))
    assert validator.errors == {field: [{1: ['must be of string type']}]}


def test_regex(validator):
    field = 'a_regex_email'
    assert_success({field: 'valid.email@gmail.com'}, validator=validator)
    assert_fail({field: 'invalid'}, update=True,
                error=(field, (field, 'regex'), errors.REGEX_MISMATCH,
                       '^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'))


def test_a_list_of_dicts():
    assert_success(
        {
            'a_list_of_dicts': [
                {'sku': 'AK345', 'price': 100},
                {'sku': 'YZ069', 'price': 25}
            ]
        }
    )


def test_a_list_of_values():
    assert_success({'a_list_of_values': ['hello', 100]})


def test_a_list_of_integers():
    assert_success({'a_list_of_integers': [99, 100]})


def test_a_dict(schema):
    assert_success({'a_dict': {'address': 'i live here',
                               'city': 'in my own town'}})
    assert_fail(
        {'a_dict': {'address': 8545}},
        error=('a_dict', ('a_dict', 'schema'), errors.MAPPING_SCHEMA,
               schema['a_dict']['schema']),
        child_errors=[(('a_dict', 'address'),
                       ('a_dict', 'schema', 'address', 'type'),
                       errors.BAD_TYPE, 'string'),
                      (('a_dict', 'city'),
                       ('a_dict', 'schema', 'city', 'required'),
                       errors.REQUIRED_FIELD, True)]
    )


def test_a_dict_with_valueschema(validator):
    assert_success({'a_dict_with_valueschema':
                   {'an integer': 99, 'another integer': 100}})

    error = (
        'a_dict_with_valueschema', ('a_dict_with_valueschema', 'valueschema'),
        errors.VALUESCHEMA, {'type': 'integer'})
    child_errors = [
        (('a_dict_with_valueschema', 'a string'),
         ('a_dict_with_valueschema', 'valueschema', 'type'),
         errors.BAD_TYPE, 'integer')]

    assert_fail({'a_dict_with_valueschema': {'a string': '99'}},
                validator=validator, error=error, child_errors=child_errors)

    assert 'valueschema' in \
           validator.schema_error_tree['a_dict_with_valueschema']
    v = validator.schema_error_tree
    assert len(v['a_dict_with_valueschema']['valueschema'].descendants) == 1


def test_a_dict_with_keyschema():
    assert_success({'a_dict_with_keyschema': {'key': 'value'}})
    assert_fail({'a_dict_with_keyschema': {'KEY': 'value'}})


def test_a_list_length(schema):
    field = 'a_list_length'
    min_length = schema[field]['minlength']
    max_length = schema[field]['maxlength']

    assert_fail({field: [1] * (min_length - 1)},
                error=(field, (field, 'minlength'), errors.MIN_LENGTH,
                       min_length, (min_length - 1,)))

    for i in range(min_length, max_length):
        value = [1] * i
        assert_success({field: value})

    assert_fail({field: [1] * (max_length + 1)},
                error=(field, (field, 'maxlength'), errors.MAX_LENGTH,
                       max_length, (max_length + 1,)))


def test_custom_datatype():
    class MyValidator(Validator):
        def _validate_type_objectid(self, value):
            if re.match('[a-f0-9]{24}', value):
                return True

    schema = {'test_field': {'type': 'objectid'}}
    validator = MyValidator(schema)
    assert_success({'test_field': '50ad188438345b1049c88a28'},
                   validator=validator)
    assert_fail({'test_field': 'hello'}, validator=validator,
                error=('test_field', ('test_field', 'type'), errors.BAD_TYPE,
                       'objectid'))


def test_custom_datatype_rule():
    class MyValidator(Validator):
        def _validate_min_number(self, min_number, field, value):
            """ {'type': 'number'} """
            if value < min_number:
                self._error(field, 'Below the min')

        # TODO replace with TypeDefintion in next major release
        def _validate_type_number(self, value):
            if isinstance(value, int):
                return True

    schema = {'test_field': {'min_number': 1, 'type': 'number'}}
    validator = MyValidator(schema)
    assert_fail({'test_field': '0'}, validator=validator,
                error=('test_field', ('test_field', 'type'), errors.BAD_TYPE,
                       'number'))
    assert_fail({'test_field': 0}, validator=validator,
                error=('test_field', (), errors.CUSTOM, None,
                       ('Below the min',)))
    assert validator.errors == {'test_field': ['Below the min']}


def test_custom_validator():
    class MyValidator(Validator):
        def _validate_isodd(self, isodd, field, value):
            """ {'type': 'boolean'} """
            if isodd and not bool(value & 1):
                self._error(field, 'Not an odd number')

    schema = {'test_field': {'isodd': True}}
    validator = MyValidator(schema)
    assert_success({'test_field': 7}, validator=validator)
    assert_fail({'test_field': 6}, validator=validator,
                error=('test_field', (), errors.CUSTOM, None,
                       ('Not an odd number',)))
    assert validator.errors == {'test_field': ['Not an odd number']}


@mark.parametrize('value, _type',
                  (('', 'string'), ((), 'list'), ({}, 'dict'), ([], 'list')))
def test_empty_values(value, _type):
    field = 'test'
    schema = {field: {'type': _type}}
    document = {field: value}

    assert_success(document, schema)

    schema[field]['empty'] = False
    assert_fail(document, schema,
                error=(field, (field, 'empty'),
                       errors.EMPTY_NOT_ALLOWED, False))

    schema[field]['empty'] = True
    assert_success(document, schema)


def test_empty_skips_regex(validator):
    schema = {'foo': {'empty': True, 'regex': r'\d?\d\.\d\d',
                      'type': 'string'}}
    assert validator({'foo': ''}, schema)


def test_ignore_none_values():
    field = 'test'
    schema = {field: {'type': 'string', 'empty': False, 'required': False}}
    document = {field: None}

    # Test normal behaviour
    validator = Validator(schema, ignore_none_values=False)
    assert_fail(document, validator=validator)
    validator.schema[field]['required'] = True
    validator.schema.validate()
    _errors = assert_fail(document, validator=validator)
    assert_not_has_error(_errors, field, (field, 'required'),
                         errors.REQUIRED_FIELD, True)

    # Test ignore None behaviour
    validator = Validator(schema, ignore_none_values=True)
    validator.schema[field]['required'] = False
    validator.schema.validate()
    assert_success(document, validator=validator)
    validator.schema[field]['required'] = True
    _errors = assert_fail(schema=schema, document=document, validator=validator)
    assert_has_error(_errors, field, (field, 'required'), errors.REQUIRED_FIELD,
                     True)
    assert_not_has_error(_errors, field, (field, 'type'), errors.BAD_TYPE,
                         'string')


def test_unknown_keys():
    schema = {}

    # test that unknown fields are allowed when allow_unknown is True.
    v = Validator(allow_unknown=True, schema=schema)
    assert_success({"unknown1": True, "unknown2": "yes"}, validator=v)

    # test that unknown fields are allowed only if they meet the
    # allow_unknown schema when provided.
    v.allow_unknown = {'type': 'string'}
    assert_success(document={'name': 'mark'}, validator=v)
    assert_fail({"name": 1}, validator=v)

    # test that unknown fields are not allowed if allow_unknown is False
    v.allow_unknown = False
    assert_fail({'name': 'mark'}, validator=v)


def test_unknown_key_dict(validator):
    # https://github.com/pyeve/cerberus/issues/177
    validator.allow_unknown = True
    document = {'a_dict': {'foo': 'foo_value', 'bar': 25}}
    assert_success(document, {}, validator=validator)


def test_unknown_key_list(validator):
    # https://github.com/pyeve/cerberus/issues/177
    validator.allow_unknown = True
    document = {'a_dict': ['foo', 'bar']}
    assert_success(document, {}, validator=validator)


def test_unknown_keys_list_of_dicts(validator):
    # test that allow_unknown is honored even for subdicts in lists.
    # https://github.com/pyeve/cerberus/issues/67.
    validator.allow_unknown = True
    document = {'a_list_of_dicts': [{'sku': 'YZ069', 'price': 25,
                                     'extra': True}]}
    assert_success(document, validator=validator)


def test_unknown_keys_retain_custom_rules():
    # test that allow_unknown schema respect custom validation rules.
    # https://github.com/pyeve/cerberus/issues/#66.
    class CustomValidator(Validator):
        def _validate_type_foo(self, value):
            if value == "foo":
                return True

    validator = CustomValidator({})
    validator.allow_unknown = {"type": "foo"}
    assert_success(document={"fred": "foo", "barney": "foo"},
                   validator=validator)


def test_nested_unknown_keys():
    schema = {
        'field1': {
            'type': 'dict',
            'allow_unknown': True,
            'schema': {'nested1': {'type': 'string'}}
        }
    }
    document = {
        'field1': {
            'nested1': 'foo',
            'arb1': 'bar',
            'arb2': 42
        }
    }
    assert_success(document=document, schema=schema)

    schema['field1']['allow_unknown'] = {'type': 'string'}
    assert_fail(document=document, schema=schema)


def test_novalidate_noerrors(validator):
    """
    In v0.1.0 and below `self.errors` raised an exception if no
    validation had been performed yet.
    """
    assert validator.errors == {}


def test_callable_validator():
    """
    Validator instance is callable, functions as a shorthand
    passthrough to validate()
    """
    schema = {'test_field': {'type': 'string'}}
    v = Validator(schema)
    assert v.validate({'test_field': 'foo'})
    assert v({'test_field': 'foo'})
    assert not v.validate({'test_field': 1})
    assert not v({'test_field': 1})


def test_dependencies_field():
    schema = {'test_field': {'dependencies': 'foo'},
              'foo': {'type': 'string'}}
    assert_success({'test_field': 'foobar', 'foo': 'bar'}, schema)
    assert_fail({'test_field': 'foobar'}, schema)


def test_dependencies_list():
    schema = {
        'test_field': {'dependencies': ['foo', 'bar']},
        'foo': {'type': 'string'},
        'bar': {'type': 'string'}
    }
    assert_success({'test_field': 'foobar', 'foo': 'bar', 'bar': 'foo'},
                   schema)
    assert_fail({'test_field': 'foobar', 'foo': 'bar'}, schema)


def test_dependencies_list_with_required_field():
    schema = {
        'test_field': {'required': True, 'dependencies': ['foo', 'bar']},
        'foo': {'type': 'string'},
        'bar': {'type': 'string'}
    }
    # False: all dependencies missing
    assert_fail({'test_field': 'foobar'}, schema)
    # False: one of dependencies missing
    assert_fail({'test_field': 'foobar', 'foo': 'bar'}, schema)
    # False: one of dependencies missing
    assert_fail({'test_field': 'foobar', 'bar': 'foo'}, schema)
    # False: dependencies are validated and field is required
    assert_fail({'foo': 'bar', 'bar': 'foo'}, schema)
    # False: All dependencies are optional but field is still required
    assert_fail({}, schema)
    # True: dependency missing
    assert_fail({'foo': 'bar'}, schema)
    # True: dependencies are validated but field is not required
    schema['test_field']['required'] = False
    assert_success({'foo': 'bar', 'bar': 'foo'}, schema)


def test_dependencies_list_with_subodcuments_fields():
    schema = {
        'test_field': {'dependencies': ['a_dict.foo', 'a_dict.bar']},
        'a_dict': {
            'type': 'dict',
            'schema': {
                'foo': {'type': 'string'},
                'bar': {'type': 'string'}
            }
        }
    }
    assert_success({'test_field': 'foobar',
                    'a_dict': {'foo': 'foo', 'bar': 'bar'}}, schema)
    assert_fail({'test_field': 'foobar', 'a_dict': {}}, schema)
    assert_fail({'test_field': 'foobar',
                 'a_dict': {'foo': 'foo'}}, schema)


def test_dependencies_dict():
    schema = {
        'test_field': {'dependencies': {'foo': 'foo', 'bar': 'bar'}},
        'foo': {'type': 'string'},
        'bar': {'type': 'string'}
    }
    assert_success({'test_field': 'foobar', 'foo': 'foo', 'bar': 'bar'},
                   schema)
    assert_fail({'test_field': 'foobar', 'foo': 'foo'}, schema)
    assert_fail({'test_field': 'foobar', 'foo': 'bar'}, schema)
    assert_fail({'test_field': 'foobar', 'bar': 'bar'}, schema)
    assert_fail({'test_field': 'foobar', 'bar': 'foo'}, schema)
    assert_fail({'test_field': 'foobar'}, schema)


def test_dependencies_dict_with_required_field():
    schema = {
        'test_field': {
            'required': True,
            'dependencies': {'foo': 'foo', 'bar': 'bar'}
        },
        'foo': {'type': 'string'},
        'bar': {'type': 'string'}
    }
    # False: all dependencies missing
    assert_fail({'test_field': 'foobar'}, schema)
    # False: one of dependencies missing
    assert_fail({'test_field': 'foobar', 'foo': 'foo'}, schema)
    assert_fail({'test_field': 'foobar', 'bar': 'bar'}, schema)
    # False: dependencies are validated and field is required
    assert_fail({'foo': 'foo', 'bar': 'bar'}, schema)
    # False: All dependencies are optional, but field is still required
    assert_fail({}, schema)
    # False: dependency missing
    assert_fail({'foo': 'bar'}, schema)

    assert_success({'test_field': 'foobar', 'foo': 'foo', 'bar': 'bar'},
                   schema)

    # True: dependencies are validated but field is not required
    schema['test_field']['required'] = False
    assert_success({'foo': 'bar', 'bar': 'foo'}, schema)


def test_dependencies_field_satisfy_nullable_field():
    # https://github.com/pyeve/cerberus/issues/305
    schema = {
        'foo': {'nullable': True},
        'bar': {'dependencies': 'foo'}
    }

    assert_success({'foo': None, 'bar': 1}, schema)
    assert_success({'foo': None}, schema)
    assert_fail({'bar': 1}, schema)


def test_dependencies_field_with_mutually_dependent_nullable_fields():
    # https://github.com/pyeve/cerberus/pull/306
    schema = {
        'foo': {'dependencies': 'bar', 'nullable': True},
        'bar': {'dependencies': 'foo', 'nullable': True}
    }
    assert_success({'foo': None, 'bar': None}, schema)
    assert_success({'foo': 1, 'bar': 1}, schema)
    assert_success({'foo': None, 'bar': 1}, schema)
    assert_fail({'foo': None}, schema)
    assert_fail({'foo': 1}, schema)


def test_dependencies_dict_with_subdocuments_fields():
    schema = {
        'test_field': {'dependencies': {'a_dict.foo': ['foo', 'bar'],
                                        'a_dict.bar': 'bar'}},
        'a_dict': {
            'type': 'dict',
            'schema': {
                'foo': {'type': 'string'},
                'bar': {'type': 'string'}
            }
        }
    }
    assert_success({'test_field': 'foobar',
                    'a_dict': {'foo': 'foo', 'bar': 'bar'}}, schema)
    assert_success({'test_field': 'foobar',
                    'a_dict': {'foo': 'bar', 'bar': 'bar'}}, schema)
    assert_fail({'test_field': 'foobar', 'a_dict': {}}, schema)
    assert_fail({'test_field': 'foobar',
                 'a_dict': {'foo': 'foo', 'bar': 'foo'}}, schema)
    assert_fail({'test_field': 'foobar', 'a_dict': {'bar': 'foo'}},
                schema)
    assert_fail({'test_field': 'foobar', 'a_dict': {'bar': 'bar'}},
                schema)


def test_root_relative_dependencies():
    # https://github.com/pyeve/cerberus/issues/288
    subschema = {'version': {'dependencies': '^repo'}}
    schema = {'package': {'allow_unknown': True, 'schema': subschema},
              'repo': {}}
    assert_fail(
        {'package': {'repo': 'somewhere', 'version': 0}}, schema,
        error=('package', ('package', 'schema'),
               errors.MAPPING_SCHEMA, subschema),
        child_errors=[(
            ('package', 'version'),
            ('package', 'schema', 'version', 'dependencies'),
            errors.DEPENDENCIES_FIELD, '^repo', ('^repo',)
        )]
    )
    assert_success({'repo': 'somewhere', 'package': {'version': 1}}, schema)


def test_dependencies_errors():
    v = Validator({'field1': {'required': False},
                   'field2': {'required': True,
                              'dependencies': {'field1': ['one', 'two']}}})
    assert_fail({'field1': 'three', 'field2': 7}, validator=v,
                error=('field2', ('field2', 'dependencies'),
                       errors.DEPENDENCIES_FIELD_VALUE,
                       {'field1': ['one', 'two']}, ({'field1': 'three'},)))


def test_options_passed_to_nested_validators(validator):
    validator.schema = {'sub_dict': {'type': 'dict',
                                     'schema': {'foo': {'type': 'string'}}}}
    validator.allow_unknown = True
    assert_success({'sub_dict': {'foo': 'bar', 'unknown': True}},
                   validator=validator)


def test_self_root_document():
    """ Make sure self.root_document is always the root document.
    See:
    * https://github.com/pyeve/cerberus/pull/42
    * https://github.com/pyeve/eve/issues/295
    """

    class MyValidator(Validator):
        def _validate_root_doc(self, root_doc, field, value):
            """ {'type': 'boolean'} """
            if ('sub' not in self.root_document or
                    len(self.root_document['sub']) != 2):
                self._error(field, 'self.context is not the root doc!')

    schema = {
        'sub': {
            'type': 'list',
            'root_doc': True,
            'schema': {
                'type': 'dict',
                'schema': {
                    'foo': {
                        'type': 'string',
                        'root_doc': True
                    }
                }
            }
        }
    }
    assert_success({'sub': [{'foo': 'bar'}, {'foo': 'baz'}]},
                   validator=MyValidator(schema))


def test_validator_rule(validator):
    def validate_name(field, value, error):
        if not value.islower():
            error(field, 'must be lowercase')

    validator.schema = {
        'name': {'validator': validate_name},
        'age': {'type': 'integer'}
    }

    assert_fail({'name': 'ItsMe', 'age': 2}, validator=validator,
                error=('name', (), errors.CUSTOM, None, ('must be lowercase',)))
    assert validator.errors == {'name': ['must be lowercase']}
    assert_success({'name': 'itsme', 'age': 2}, validator=validator)


def test_validated(validator):
    validator.schema = {'property': {'type': 'string'}}
    document = {'property': 'string'}
    assert validator.validated(document) == document
    document = {'property': 0}
    assert validator.validated(document) is None


def test_anyof():
    # prop1 must be either a number between 0 and 10
    schema = {'prop1': {'min': 0, 'max': 10}}
    doc = {'prop1': 5}

    assert_success(doc, schema)

    # prop1 must be either a number between 0 and 10 or 100 and 110
    schema = {'prop1': {'anyof':
                        [{'min': 0, 'max': 10}, {'min': 100, 'max': 110}]}}
    doc = {'prop1': 105}

    assert_success(doc, schema)

    # prop1 must be either a number between 0 and 10 or 100 and 110
    schema = {'prop1': {'anyof':
                        [{'min': 0, 'max': 10}, {'min': 100, 'max': 110}]}}
    doc = {'prop1': 50}

    assert_fail(doc, schema)

    # prop1 must be an integer that is either be
    # greater than or equal to 0, or greater than or equal to 10
    schema = {'prop1': {'type': 'integer',
                        'anyof': [{'min': 0}, {'min': 10}]}}
    assert_success({'prop1': 10}, schema)
    # test that intermediate schemas do not sustain
    assert 'type' not in schema['prop1']['anyof'][0]
    assert 'type' not in schema['prop1']['anyof'][1]
    assert 'allow_unknown' not in schema['prop1']['anyof'][0]
    assert 'allow_unknown' not in schema['prop1']['anyof'][1]
    assert_success({'prop1': 5}, schema)

    exp_child_errors = [
        (('prop1',), ('prop1', 'anyof', 0, 'min'), errors.MIN_VALUE, 0),
        (('prop1',), ('prop1', 'anyof', 1, 'min'), errors.MIN_VALUE, 10)
    ]
    assert_fail({'prop1': -1}, schema,
                error=(('prop1',), ('prop1', 'anyof'), errors.ANYOF,
                       [{'min': 0}, {'min': 10}]),
                child_errors=exp_child_errors)
    doc = {'prop1': 5.5}
    assert_fail(doc, schema)
    doc = {'prop1': '5.5'}
    assert_fail(doc, schema)


def test_allof():
    # prop1 has to be a float between 0 and 10
    schema = {'prop1': {'allof': [
        {'type': 'float'}, {'min': 0}, {'max': 10}]}}
    doc = {'prop1': -1}
    assert_fail(doc, schema)
    doc = {'prop1': 5}
    assert_success(doc, schema)
    doc = {'prop1': 11}
    assert_fail(doc, schema)

    # prop1 has to be a float and an integer
    schema = {'prop1': {'allof': [{'type': 'float'}, {'type': 'integer'}]}}
    doc = {'prop1': 11}
    assert_success(doc, schema)
    doc = {'prop1': 11.5}
    assert_fail(doc, schema)
    doc = {'prop1': '11'}
    assert_fail(doc, schema)


def test_unicode_allowed():
    # issue 280
    doc = {'letters': u'♄εℓł☺'}

    schema = {'letters': {'type': 'string', 'allowed': ['a', 'b', 'c']}}
    assert_fail(doc, schema)

    schema = {'letters': {'type': 'string', 'allowed': [u'♄εℓł☺']}}
    assert_success(doc, schema)

    schema = {'letters': {'type': 'string', 'allowed': ['♄εℓł☺']}}
    doc = {'letters': '♄εℓł☺'}
    assert_success(doc, schema)


@mark.skipif(sys.version_info[0] < 3,
             reason='requires python 3.x')
def test_unicode_allowed_py3():
    """ All strings are unicode in Python 3.x. Input doc and schema
    have equal strings and validation yield success."""

    # issue 280
    doc = {'letters': u'♄εℓł☺'}
    schema = {'letters': {'type': 'string', 'allowed': ['♄εℓł☺']}}
    assert_success(doc, schema)


@mark.skipif(sys.version_info[0] > 2,
             reason='requires python 2.x')
def test_unicode_allowed_py2():
    """ Python 2.x encodes value of allowed using default encoding if
    the string includes characters outside ASCII range. Produced string
    does not match input which is an unicode string."""

    # issue 280
    doc = {'letters': u'♄εℓł☺'}
    schema = {'letters': {'type': 'string', 'allowed': ['♄εℓł☺']}}
    assert_fail(doc, schema)


def test_oneof():
    # prop1 can only only be:
    # - greater than 10
    # - greater than 0
    # - equal to -5, 5, or 15

    schema = {'prop1': {'type': 'integer', 'oneof': [
        {'min': 0},
        {'min': 10},
        {'allowed': [-5, 5, 15]}]}}

    # document is not valid
    # prop1 not greater than 0, 10 or equal to -5
    doc = {'prop1': -1}
    assert_fail(doc, schema)

    # document is valid
    # prop1 is less then 0, but is -5
    doc = {'prop1': -5}
    assert_success(doc, schema)

    # document is valid
    # prop1 greater than 0
    doc = {'prop1': 1}
    assert_success(doc, schema)

    # document is not valid
    # prop1 is greater than 0
    # and equal to 5
    doc = {'prop1': 5}
    assert_fail(doc, schema)

    # document is not valid
    # prop1 is greater than 0
    # and greater than 10
    doc = {'prop1': 11}
    assert_fail(doc, schema)

    # document is not valid
    # prop1 is greater than 0
    # and greater than 10
    # and equal to 15
    doc = {'prop1': 15}
    assert_fail(doc, schema)


def test_noneof():
    # prop1 can not be:
    # - greater than 10
    # - greater than 0
    # - equal to -5, 5, or 15

    schema = {'prop1': {'type': 'integer', 'noneof': [
        {'min': 0},
        {'min': 10},
        {'allowed': [-5, 5, 15]}]}}

    # document is valid
    doc = {'prop1': -1}
    assert_success(doc, schema)

    # document is not valid
    # prop1 is equal to -5
    doc = {'prop1': -5}
    assert_fail(doc, schema)

    # document is not valid
    # prop1 greater than 0
    doc = {'prop1': 1}
    assert_fail(doc, schema)

    # document is not valid
    doc = {'prop1': 5}
    assert_fail(doc, schema)

    # document is not valid
    doc = {'prop1': 11}
    assert_fail(doc, schema)

    # document is not valid
    # and equal to 15
    doc = {'prop1': 15}
    assert_fail(doc, schema)


def test_anyof_allof():
    # prop1 can be any number outside of [0-10]
    schema = {'prop1': {'allof': [{'anyof': [{'type': 'float'},
                                             {'type': 'integer'}]},
                                  {'anyof': [{'min': 10},
                                             {'max': 0}]}
                                  ]}}

    doc = {'prop1': 11}
    assert_success(doc, schema)
    doc = {'prop1': -1}
    assert_success(doc, schema)
    doc = {'prop1': 5}
    assert_fail(doc, schema)

    doc = {'prop1': 11.5}
    assert_success(doc, schema)
    doc = {'prop1': -1.5}
    assert_success(doc, schema)
    doc = {'prop1': 5.5}
    assert_fail(doc, schema)

    doc = {'prop1': '5.5'}
    assert_fail(doc, schema)


def test_anyof_schema(validator):
    # test that a list of schemas can be specified.

    valid_parts = [{'schema': {'model number': {'type': 'string'},
                               'count': {'type': 'integer'}}},
                   {'schema': {'serial number': {'type': 'string'},
                               'count': {'type': 'integer'}}}]
    valid_item = {'type': ['dict', 'string'], 'anyof': valid_parts}
    schema = {'parts': {'type': 'list', 'schema': valid_item}}
    document = {'parts': [{'model number': 'MX-009', 'count': 100},
                          {'serial number': '898-001'},
                          'misc']}

    # document is valid. each entry in 'parts' matches a type or schema
    assert_success(document, schema, validator=validator)

    document['parts'].append({'product name': "Monitors", 'count': 18})
    # document is invalid. 'product name' does not match any valid schemas
    assert_fail(document, schema, validator=validator)

    document['parts'].pop()
    # document is valid again
    assert_success(document, schema, validator=validator)

    document['parts'].append({'product name': "Monitors", 'count': 18})
    document['parts'].append(10)
    # and invalid. numbers are not allowed.

    exp_child_errors = [
        (('parts', 3), ('parts', 'schema', 'anyof'), errors.ANYOF,
         valid_parts),
        (('parts', 4), ('parts', 'schema', 'type'), errors.BAD_TYPE,
         ['dict', 'string'])
    ]

    _errors = assert_fail(document, schema, validator=validator,
                          error=('parts', ('parts', 'schema'),
                                 errors.SEQUENCE_SCHEMA, valid_item),
                          child_errors=exp_child_errors)
    assert_not_has_error(_errors, ('parts', 4), ('parts', 'schema', 'anyof'),
                         errors.ANYOF, valid_parts)

    # tests errors.BasicErrorHandler's tree representation
    v_errors = validator.errors
    assert 'parts' in v_errors
    assert 3 in v_errors['parts'][-1]
    assert v_errors['parts'][-1][3][0] == "no definitions validate"
    scope = v_errors['parts'][-1][3][-1]
    assert 'anyof definition 0' in scope
    assert 'anyof definition 1' in scope
    assert scope['anyof definition 0'] == [{"product name": ["unknown field"]}]
    assert scope['anyof definition 1'] == [{"product name": ["unknown field"]}]
    assert v_errors['parts'][-1][4] == ["must be of ['dict', 'string'] type"]


def test_anyof_2():
    # these two schema should be the same
    schema1 = {'prop': {'anyof': [{'type': 'dict',
                                   'schema': {
                                       'val': {'type': 'integer'}}},
                                  {'type': 'dict',
                                   'schema': {
                                       'val': {'type': 'string'}}}]}}
    schema2 = {'prop': {'type': 'dict', 'anyof': [
        {'schema': {'val': {'type': 'integer'}}},
        {'schema': {'val': {'type': 'string'}}}]}}

    doc = {'prop': {'val': 0}}
    assert_success(doc, schema1)
    assert_success(doc, schema2)

    doc = {'prop': {'val': '0'}}
    assert_success(doc, schema1)
    assert_success(doc, schema2)

    doc = {'prop': {'val': 1.1}}
    assert_fail(doc, schema1)
    assert_fail(doc, schema2)


def test_anyof_type():
    schema = {'anyof_type': {'anyof_type': ['string', 'integer']}}
    assert_success({'anyof_type': 'bar'}, schema)
    assert_success({'anyof_type': 23}, schema)


def test_oneof_schema():
    schema = {'oneof_schema': {'type': 'dict',
                               'oneof_schema':
                                   [{'digits': {'type': 'integer',
                                                'min': 0, 'max': 99}},
                                    {'text': {'type': 'string',
                                              'regex': '^[0-9]{2}$'}}]}}
    assert_success({'oneof_schema': {'digits': 19}}, schema)
    assert_success({'oneof_schema': {'text': '84'}}, schema)
    assert_fail({'oneof_schema': {'digits': 19, 'text': '84'}}, schema)


def test_nested_oneof_type():
    schema = {'nested_oneof_type':
              {'valueschema': {'oneof_type': ['string', 'integer']}}}
    assert_success({'nested_oneof_type': {'foo': 'a'}}, schema)
    assert_success({'nested_oneof_type': {'bar': 3}}, schema)


def test_nested_oneofs(validator):
    validator.schema = {'abc': {
        'type': 'dict',
        'oneof_schema': [
            {'foo': {
                'type': 'dict',
                'schema': {'bar': {'oneof_type': ['integer', 'float']}}
            }},
            {'baz': {'type': 'string'}}
        ]}}

    document = {'abc': {'foo': {'bar': 'bad'}}}

    expected_errors = {
        'abc': [
            'none or more than one rule validate',
            {'oneof definition 0': [
                {'foo': [{'bar': [
                    'none or more than one rule validate',
                    {'oneof definition 0': ['must be of integer type'],
                     'oneof definition 1': ['must be of float type']}
                ]}]}],
             'oneof definition 1': [{'foo': ['unknown field']}]}
        ]
    }

    assert_fail(document, validator=validator)
    assert validator.errors == expected_errors


def test_no_of_validation_if_type_fails(validator):
    valid_parts = [{'schema': {'model number': {'type': 'string'},
                               'count': {'type': 'integer'}}},
                   {'schema': {'serial number': {'type': 'string'},
                               'count': {'type': 'integer'}}}]
    validator.schema = {'part': {'type': ['dict', 'string'],
                                 'anyof': valid_parts}}
    document = {'part': 10}
    _errors = assert_fail(document, validator=validator)
    assert len(_errors) == 1


def test_issue_107(validator):
    schema = {'info': {'type': 'dict',
                       'schema': {'name': {'type': 'string',
                                           'required': True}}}}
    document = {'info': {'name': 'my name'}}
    assert_success(document, schema, validator=validator)

    v = Validator(schema)
    assert_success(document, schema, v)
    # it once was observed that this behaves other than the previous line
    assert v.validate(document)


def test_dont_type_validate_nulled_values(validator):
    assert_fail({'an_integer': None}, validator=validator)
    assert validator.errors == {'an_integer': ['null value not allowed']}


def test_dependencies_error(validator):
    schema = {'field1': {'required': False},
              'field2': {'required': True,
                         'dependencies': {'field1': ['one', 'two']}}}
    validator.validate({'field2': 7}, schema)
    exp_msg = errors.BasicErrorHandler \
        .messages[errors.DEPENDENCIES_FIELD_VALUE.code] \
        .format(field='field2', constraint={'field1': ['one', 'two']})
    assert validator.errors == {'field2': [exp_msg]}


def test_dependencies_on_boolean_field_with_one_value():
    # https://github.com/pyeve/cerberus/issues/138
    schema = {'deleted': {'type': 'boolean'},
              'text': {'dependencies': {'deleted': False}}}
    try:
        assert_success({'text': 'foo', 'deleted': False}, schema)
        assert_fail({'text': 'foo', 'deleted': True}, schema)
        assert_fail({'text': 'foo'}, schema)
    except TypeError as e:
        if str(e) == "argument of type 'bool' is not iterable":
            raise AssertionError(
                "Bug #138 still exists, couldn't use boolean in dependency "
                "without putting it in a list.\n"
                "'some_field': True vs 'some_field: [True]")
        else:
            raise


def test_dependencies_on_boolean_field_with_value_in_list():
    # https://github.com/pyeve/cerberus/issues/138
    schema = {'deleted': {'type': 'boolean'},
              'text': {'dependencies': {'deleted': [False]}}}

    assert_success({'text': 'foo', 'deleted': False}, schema)
    assert_fail({'text': 'foo', 'deleted': True}, schema)
    assert_fail({'text': 'foo'}, schema)


def test_document_path():
    class DocumentPathTester(Validator):
        def _validate_trail(self, constraint, field, value):
            """ {'type': 'boolean'} """
            test_doc = self.root_document
            for crumb in self.document_path:
                test_doc = test_doc[crumb]
            assert test_doc == self.document

    v = DocumentPathTester()
    schema = {'foo': {'schema': {'bar': {'trail': True}}}}
    document = {'foo': {'bar': {}}}
    assert_success(document, schema, validator=v)


def test_excludes():
    schema = {'this_field': {'type': 'dict',
                             'excludes': 'that_field'},
              'that_field': {'type': 'dict'}}
    assert_success({'this_field': {}}, schema)
    assert_success({'that_field': {}}, schema)
    assert_success({}, schema)
    assert_fail({'that_field': {}, 'this_field': {}}, schema)


def test_mutual_excludes():
    schema = {'this_field': {'type': 'dict',
                             'excludes': 'that_field'},
              'that_field': {'type': 'dict',
                             'excludes': 'this_field'}}
    assert_success({'this_field': {}}, schema)
    assert_success({'that_field': {}}, schema)
    assert_success({}, schema)
    assert_fail({'that_field': {}, 'this_field': {}}, schema)


def test_required_excludes():
    schema = {'this_field': {'type': 'dict',
                             'excludes': 'that_field',
                             'required': True},
              'that_field': {'type': 'dict',
                             'excludes': 'this_field',
                             'required': True}}
    assert_success({'this_field': {}}, schema, update=False)
    assert_success({'that_field': {}}, schema, update=False)
    assert_fail({}, schema)
    assert_fail({'that_field': {}, 'this_field': {}}, schema)


def test_multiples_exclusions():
    schema = {'this_field': {'type': 'dict',
                             'excludes': ['that_field', 'bazo_field']},
              'that_field': {'type': 'dict',
                             'excludes': 'this_field'},
              'bazo_field': {'type': 'dict'}}
    assert_success({'this_field': {}}, schema)
    assert_success({'that_field': {}}, schema)
    assert_fail({'this_field': {}, 'that_field': {}}, schema)
    assert_fail({'this_field': {}, 'bazo_field': {}}, schema)
    assert_fail({'that_field': {}, 'this_field': {}, 'bazo_field': {}}, schema)
    assert_success({'that_field': {}, 'bazo_field': {}}, schema)


def test_bad_excludes_fields(validator):
    validator.schema = {'this_field': {'type': 'dict',
                                       'excludes': ['that_field', 'bazo_field'],
                                       'required': True},
                        'that_field': {'type': 'dict',
                                       'excludes': 'this_field',
                                       'required': True}}
    assert_fail({'that_field': {}, 'this_field': {}}, validator=validator)
    handler = errors.BasicErrorHandler
    assert (validator.errors ==
            {'that_field':
                [handler.messages[errors.EXCLUDES_FIELD.code].format(
                    "'this_field'", field="that_field")],
                'this_field':
                    [handler.messages[errors.EXCLUDES_FIELD.code].format(
                        "'that_field', 'bazo_field'", field="this_field")]})


def test_boolean_is_not_a_number():
    # https://github.com/pyeve/cerberus/issues/144
    assert_fail({'value': True}, {'value': {'type': 'number'}})


def test_min_max_date():
    schema = {'date': {'min': date(1900, 1, 1), 'max': date(1999, 12, 31)}}
    assert_success({'date': date(1945, 5, 8)}, schema)
    assert_fail({'date': date(1871, 5, 10)}, schema)


def test_dict_length():
    schema = {'dict': {'minlength': 1}}
    assert_fail({'dict': {}}, schema)
    assert_success({'dict': {'foo': 'bar'}}, schema)


def test_forbidden():
    schema = {'user': {'forbidden': ['root', 'admin']}}
    assert_fail({'user': 'admin'}, schema)
    assert_success({'user': 'alice'}, schema)


def test_mapping_with_sequence_schema():
    schema = {'list': {'schema': {'allowed': ['a', 'b', 'c']}}}
    document = {'list': {'is_a': 'mapping'}}
    assert_fail(document, schema,
                error=('list', ('list', 'schema'), errors.BAD_TYPE_FOR_SCHEMA,
                       schema['list']['schema']))


def test_sequence_with_mapping_schema():
    schema = {'list': {'schema': {'foo': {'allowed': ['a', 'b', 'c']}},
                       'type': 'dict'}}
    document = {'list': ['a', 'b', 'c']}
    assert_fail(document, schema)


def test_type_error_aborts_validation():
    schema = {'foo': {'type': 'string', 'allowed': ['a']}}
    document = {'foo': 0}
    assert_fail(document, schema,
                error=('foo', ('foo', 'type'), errors.BAD_TYPE, 'string'))


def test_dependencies_in_oneof():
    # https://github.com/pyeve/cerberus/issues/241
    schema = {'a': {'type': 'integer',
                    'oneof': [
                        {'allowed': [1], 'dependencies': 'b'},
                        {'allowed': [2], 'dependencies': 'c'}
                    ]},
              'b': {},
              'c': {}}
    assert_success({'a': 1, 'b': 'foo'}, schema)
    assert_success({'a': 2, 'c': 'bar'}, schema)
    assert_fail({'a': 1, 'c': 'foo'}, schema)
    assert_fail({'a': 2, 'b': 'bar'}, schema)


def test_allow_unknown_with_oneof_rules(validator):
    # https://github.com/pyeve/cerberus/issues/251
    schema = {
        'test': {
            'oneof': [
                {
                    'type': 'dict',
                    'allow_unknown': True,
                    'schema': {'known': {'type': 'string'}}
                },
                {
                    'type': 'dict',
                    'schema': {'known': {'type': 'string'}}
                },
            ]
        }
    }
    # check regression and that allow unknown does not cause any different
    # than expected behaviour for one-of.
    document = {'test': {'known': 's'}}
    validator(document, schema)
    _errors = validator._errors
    assert len(_errors) == 1
    assert_has_error(_errors, 'test', ('test', 'oneof'),
                     errors.ONEOF, schema['test']['oneof'])
    assert len(_errors[0].child_errors) == 0
    # check that allow_unknown is actually applied
    document = {'test': {'known': 's', 'unknown': 'asd'}}
    assert_success(document, validator=validator)
