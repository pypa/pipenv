# -*- coding: utf-8 -*-

from cerberus import Validator, errors
from cerberus.tests import assert_fail


ValidationError = errors.ValidationError


def test__error_1():
    v = Validator(schema={'foo': {'type': 'string'}})
    v.document = {'foo': 42}
    v._error('foo', errors.BAD_TYPE, 'string')
    error = v._errors[0]
    assert error.document_path == ('foo',)
    assert error.schema_path == ('foo', 'type')
    assert error.code == 0x24
    assert error.rule == 'type'
    assert error.constraint == 'string'
    assert error.value == 42
    assert error.info == ('string',)
    assert not error.is_group_error
    assert not error.is_logic_error


def test__error_2():
    v = Validator(schema={'foo': {'keysrules': {'type': 'integer'}}})
    v.document = {'foo': {'0': 'bar'}}
    v._error('foo', errors.KEYSRULES, ())
    error = v._errors[0]
    assert error.document_path == ('foo',)
    assert error.schema_path == ('foo', 'keysrules')
    assert error.code == 0x83
    assert error.rule == 'keysrules'
    assert error.constraint == {'type': 'integer'}
    assert error.value == {'0': 'bar'}
    assert error.info == ((),)
    assert error.is_group_error
    assert not error.is_logic_error


def test__error_3():
    valids = [
        {'type': 'string', 'regex': '0x[0-9a-f]{2}'},
        {'type': 'integer', 'min': 0, 'max': 255},
    ]
    v = Validator(schema={'foo': {'oneof': valids}})
    v.document = {'foo': '0x100'}
    v._error('foo', errors.ONEOF, (), 0, 2)
    error = v._errors[0]
    assert error.document_path == ('foo',)
    assert error.schema_path == ('foo', 'oneof')
    assert error.code == 0x92
    assert error.rule == 'oneof'
    assert error.constraint == valids
    assert error.value == '0x100'
    assert error.info == ((), 0, 2)
    assert error.is_group_error
    assert error.is_logic_error


def test_error_tree_from_subschema(validator):
    schema = {'foo': {'schema': {'bar': {'type': 'string'}}}}
    document = {'foo': {'bar': 0}}
    assert_fail(document, schema, validator=validator)
    d_error_tree = validator.document_error_tree
    s_error_tree = validator.schema_error_tree

    assert 'foo' in d_error_tree

    assert len(d_error_tree['foo'].errors) == 1, d_error_tree['foo']
    assert d_error_tree['foo'].errors[0].code == errors.MAPPING_SCHEMA.code
    assert 'bar' in d_error_tree['foo']
    assert d_error_tree['foo']['bar'].errors[0].value == 0
    assert d_error_tree.fetch_errors_from(('foo', 'bar'))[0].value == 0

    assert 'foo' in s_error_tree
    assert 'schema' in s_error_tree['foo']
    assert 'bar' in s_error_tree['foo']['schema']
    assert 'type' in s_error_tree['foo']['schema']['bar']
    assert s_error_tree['foo']['schema']['bar']['type'].errors[0].value == 0
    assert (
        s_error_tree.fetch_errors_from(('foo', 'schema', 'bar', 'type'))[0].value == 0
    )


def test_error_tree_from_anyof(validator):
    schema = {'foo': {'anyof': [{'type': 'string'}, {'type': 'integer'}]}}
    document = {'foo': []}
    assert_fail(document, schema, validator=validator)
    d_error_tree = validator.document_error_tree
    s_error_tree = validator.schema_error_tree
    assert 'foo' in d_error_tree
    assert d_error_tree['foo'].errors[0].value == []
    assert 'foo' in s_error_tree
    assert 'anyof' in s_error_tree['foo']
    assert 0 in s_error_tree['foo']['anyof']
    assert 1 in s_error_tree['foo']['anyof']
    assert 'type' in s_error_tree['foo']['anyof'][0]
    assert s_error_tree['foo']['anyof'][0]['type'].errors[0].value == []


def test_nested_error_paths(validator):
    # interpreters of the same version on some platforms showed different sort results
    # over various runs:
    def assert_has_all_errors(errors, *ref_errs):
        for ref_err in ref_errs:
            for error in errors:
                if error == ref_err:
                    break
            else:
                raise AssertionError

    schema = {
        'a_dict': {
            'keysrules': {'type': 'integer'},
            'valuesrules': {'regex': '[a-z]*'},
        },
        'a_list': {'schema': {'type': 'string', 'oneof_regex': ['[a-z]*$', '[A-Z]*']}},
    }
    document = {
        'a_dict': {0: 'abc', 'one': 'abc', 2: 'aBc', 'three': 'abC'},
        'a_list': [0, 'abc', 'abC'],
    }
    assert_fail(document, schema, validator=validator)

    det = validator.document_error_tree
    set = validator.schema_error_tree

    assert len(det.errors) == 0
    assert len(set.errors) == 0

    assert len(det['a_dict'].errors) == 2
    assert len(set['a_dict'].errors) == 0

    assert det['a_dict'][0] is None
    assert len(det['a_dict']['one'].errors) == 1
    assert len(det['a_dict'][2].errors) == 1
    assert len(det['a_dict']['three'].errors) == 2

    assert len(set['a_dict']['keysrules'].errors) == 1
    assert len(set['a_dict']['valuesrules'].errors) == 1

    assert len(set['a_dict']['keysrules']['type'].errors) == 2
    assert len(set['a_dict']['valuesrules']['regex'].errors) == 2

    ref_err1 = ValidationError(
        ('a_dict', 'one'),
        ('a_dict', 'keysrules', 'type'),
        errors.BAD_TYPE.code,
        'type',
        'integer',
        'one',
        (),
    )

    ref_err2 = ValidationError(
        ('a_dict', 2),
        ('a_dict', 'valuesrules', 'regex'),
        errors.REGEX_MISMATCH.code,
        'regex',
        '[a-z]*$',
        'aBc',
        (),
    )

    ref_err3 = ValidationError(
        ('a_dict', 'three'),
        ('a_dict', 'keysrules', 'type'),
        errors.BAD_TYPE.code,
        'type',
        'integer',
        'three',
        (),
    )
    ref_err4 = ValidationError(
        ('a_dict', 'three'),
        ('a_dict', 'valuesrules', 'regex'),
        errors.REGEX_MISMATCH.code,
        'regex',
        '[a-z]*$',
        'abC',
        (),
    )
    assert det['a_dict'][2].errors[0] == ref_err2
    assert det['a_dict']['one'].errors[0] == ref_err1
    assert_has_all_errors(det['a_dict']['three'].errors, ref_err3, ref_err4)
    assert_has_all_errors(set['a_dict']['keysrules']['type'].errors, ref_err1, ref_err3)
    assert_has_all_errors(
        set['a_dict']['valuesrules']['regex'].errors, ref_err2, ref_err4
    )

    assert len(det['a_list'].errors) == 1
    assert len(det['a_list'][0].errors) == 1
    assert det['a_list'][1] is None
    assert len(det['a_list'][2].errors) == 3
    assert len(set['a_list'].errors) == 0
    assert len(set['a_list']['schema'].errors) == 1
    assert len(set['a_list']['schema']['type'].errors) == 1
    assert len(set['a_list']['schema']['oneof'][0]['regex'].errors) == 1
    assert len(set['a_list']['schema']['oneof'][1]['regex'].errors) == 1

    ref_err5 = ValidationError(
        ('a_list', 0),
        ('a_list', 'schema', 'type'),
        errors.BAD_TYPE.code,
        'type',
        'string',
        0,
        (),
    )
    ref_err6 = ValidationError(
        ('a_list', 2),
        ('a_list', 'schema', 'oneof'),
        errors.ONEOF.code,
        'oneof',
        'irrelevant_at_this_point',
        'abC',
        (),
    )
    ref_err7 = ValidationError(
        ('a_list', 2),
        ('a_list', 'schema', 'oneof', 0, 'regex'),
        errors.REGEX_MISMATCH.code,
        'regex',
        '[a-z]*$',
        'abC',
        (),
    )
    ref_err8 = ValidationError(
        ('a_list', 2),
        ('a_list', 'schema', 'oneof', 1, 'regex'),
        errors.REGEX_MISMATCH.code,
        'regex',
        '[a-z]*$',
        'abC',
        (),
    )

    assert det['a_list'][0].errors[0] == ref_err5
    assert_has_all_errors(det['a_list'][2].errors, ref_err6, ref_err7, ref_err8)
    assert set['a_list']['schema']['oneof'].errors[0] == ref_err6
    assert set['a_list']['schema']['oneof'][0]['regex'].errors[0] == ref_err7
    assert set['a_list']['schema']['oneof'][1]['regex'].errors[0] == ref_err8
    assert set['a_list']['schema']['type'].errors[0] == ref_err5


def test_path_resolution_for_registry_references():
    class CustomValidator(Validator):
        def _normalize_coerce_custom(self, value):
            raise Exception("Failed coerce")

    validator = CustomValidator()
    validator.schema_registry.add(
        "schema1", {"child": {"type": "boolean", "coerce": "custom"}}
    )
    validator.schema = {"parent": {"schema": "schema1"}}
    validator.validate({"parent": {"child": "["}})

    expected = {
        'parent': [
            {
                'child': [
                    "must be of boolean type",
                    "field 'child' cannot be coerced: Failed coerce",
                ]
            }
        ]
    }
    assert validator.errors == expected


def test_queries():
    schema = {'foo': {'type': 'dict', 'schema': {'bar': {'type': 'number'}}}}
    document = {'foo': {'bar': 'zero'}}
    validator = Validator(schema)
    validator(document)

    assert 'foo' in validator.document_error_tree
    assert 'bar' in validator.document_error_tree['foo']
    assert 'foo' in validator.schema_error_tree
    assert 'schema' in validator.schema_error_tree['foo']

    assert errors.MAPPING_SCHEMA in validator.document_error_tree['foo'].errors
    assert errors.MAPPING_SCHEMA in validator.document_error_tree['foo']
    assert errors.BAD_TYPE in validator.document_error_tree['foo']['bar']
    assert errors.MAPPING_SCHEMA in validator.schema_error_tree['foo']['schema']
    assert (
        errors.BAD_TYPE in validator.schema_error_tree['foo']['schema']['bar']['type']
    )

    assert (
        validator.document_error_tree['foo'][errors.MAPPING_SCHEMA].child_errors[0].code
        == errors.BAD_TYPE.code
    )


def test_basic_error_handler():
    handler = errors.BasicErrorHandler()
    _errors, ref = [], {}

    _errors.append(ValidationError(['foo'], ['foo'], 0x63, 'readonly', True, None, ()))
    ref.update({'foo': [handler.messages[0x63]]})
    assert handler(_errors) == ref

    _errors.append(ValidationError(['bar'], ['foo'], 0x42, 'min', 1, 2, ()))
    ref.update({'bar': [handler.messages[0x42].format(constraint=1)]})
    assert handler(_errors) == ref

    _errors.append(
        ValidationError(
            ['zap', 'foo'], ['zap', 'schema', 'foo'], 0x24, 'type', 'string', True, ()
        )
    )
    ref.update({'zap': [{'foo': [handler.messages[0x24].format(constraint='string')]}]})
    assert handler(_errors) == ref

    _errors.append(
        ValidationError(
            ['zap', 'foo'],
            ['zap', 'schema', 'foo'],
            0x41,
            'regex',
            '^p[äe]ng$',
            'boom',
            (),
        )
    )
    ref['zap'][0]['foo'].append(handler.messages[0x41].format(constraint='^p[äe]ng$'))
    assert handler(_errors) == ref


def test_basic_error_of_errors(validator):
    schema = {'foo': {'oneof': [{'type': 'integer'}, {'type': 'string'}]}}
    document = {'foo': 23.42}
    error = ('foo', ('foo', 'oneof'), errors.ONEOF, schema['foo']['oneof'], ())
    child_errors = [
        (error[0], error[1] + (0, 'type'), errors.BAD_TYPE, 'integer'),
        (error[0], error[1] + (1, 'type'), errors.BAD_TYPE, 'string'),
    ]
    assert_fail(
        document, schema, validator=validator, error=error, child_errors=child_errors
    )
    assert validator.errors == {
        'foo': [
            errors.BasicErrorHandler.messages[0x92],
            {
                'oneof definition 0': ['must be of integer type'],
                'oneof definition 1': ['must be of string type'],
            },
        ]
    }


def test_wrong_amount_of_items(validator):
    # https://github.com/pyeve/cerberus/issues/505
    validator.schema = {
        'test_list': {
            'type': 'list',
            'required': True,
            'items': [{'type': 'string'}, {'type': 'string'}],
        }
    }
    validator({'test_list': ['test']})
    assert validator.errors == {'test_list': ["length of list should be 2, it is 1"]}
