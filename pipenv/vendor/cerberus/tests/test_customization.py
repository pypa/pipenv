# -*- coding: utf-8 -*-

import cerberus
from cerberus.tests import assert_fail, assert_success
from cerberus.tests.conftest import sample_schema


def test_contextual_data_preservation():

    class InheritedValidator(cerberus.Validator):
        def __init__(self, *args, **kwargs):
            if 'working_dir' in kwargs:
                self.working_dir = kwargs['working_dir']
            super(InheritedValidator, self).__init__(*args, **kwargs)

        def _validate_type_test(self, value):
            if self.working_dir:
                return True

    assert 'test' in InheritedValidator.types
    v = InheritedValidator({'test': {'type': 'list',
                                     'schema': {'type': 'test'}}},
                           working_dir='/tmp')
    assert_success({'test': ['foo']}, validator=v)


def test_docstring_parsing():
    class CustomValidator(cerberus.Validator):
        def _validate_foo(self, argument, field, value):
            """ {'type': 'zap'} """
            pass

        def _validate_bar(self, value):
            """ Test the barreness of a value.

            The rule's arguments are validated against this schema:
                {'type': 'boolean'}
            """
            pass

    assert 'foo' in CustomValidator.validation_rules
    assert 'bar' in CustomValidator.validation_rules


def test_issue_265():
    class MyValidator(cerberus.Validator):
        def _validator_oddity(self, field, value):
            if not value & 1:
                self._error(field, "Must be an odd number")

    v = MyValidator(schema={'amount': {'validator': 'oddity'}})
    assert_success(document={'amount': 1}, validator=v)
    assert_fail(document={'amount': 2}, validator=v,
                error=('amount', (), cerberus.errors.CUSTOM, None,
                       ('Must be an odd number',)))


def test_schema_validation_can_be_disabled_in_schema_setter():

    class NonvalidatingValidator(cerberus.Validator):
        """
        Skips schema validation to speed up initialization
        """
        @cerberus.Validator.schema.setter
        def schema(self, schema):
            if schema is None:
                self._schema = None
            elif self.is_child:
                self._schema = schema
            elif isinstance(schema, cerberus.schema.DefinitionSchema):
                self._schema = schema
            else:
                self._schema = cerberus.schema.UnvalidatedSchema(schema)

    v = NonvalidatingValidator(schema=sample_schema)
    assert v.validate(document={'an_integer': 1})
    assert not v.validate(document={'an_integer': 'a'})
