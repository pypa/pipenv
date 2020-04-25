from __future__ import absolute_import

from copy import copy
from warnings import warn

from cerberus import errors
from cerberus.platform import (
    _str_type,
    Callable,
    Hashable,
    Mapping,
    MutableMapping,
    Sequence,
)
from cerberus.utils import (
    get_Validator_class,
    validator_factory,
    mapping_hash,
    TypeDefinition,
)


class _Abort(Exception):
    pass


class SchemaError(Exception):
    """ Raised when the validation schema is missing, has the wrong format or
        contains errors. """

    pass


class DefinitionSchema(MutableMapping):
    """ A dict-subclass for caching of validated schemas. """

    def __new__(cls, *args, **kwargs):
        if 'SchemaValidator' not in globals():
            global SchemaValidator
            SchemaValidator = validator_factory('SchemaValidator', SchemaValidatorMixin)
            types_mapping = SchemaValidator.types_mapping.copy()
            types_mapping.update(
                {
                    'callable': TypeDefinition('callable', (Callable,), ()),
                    'hashable': TypeDefinition('hashable', (Hashable,), ()),
                }
            )
            SchemaValidator.types_mapping = types_mapping

        return super(DefinitionSchema, cls).__new__(cls)

    def __init__(self, validator, schema):
        """
        :param validator: An instance of Validator-(sub-)class that uses this
                          schema.
        :param schema: A definition-schema as ``dict``. Defaults to an empty
                       one.
        """
        if not isinstance(validator, get_Validator_class()):
            raise RuntimeError('validator argument must be a Validator-' 'instance.')
        self.validator = validator

        if isinstance(schema, _str_type):
            schema = validator.schema_registry.get(schema, schema)

        if not isinstance(schema, Mapping):
            try:
                schema = dict(schema)
            except Exception:
                raise SchemaError(errors.SCHEMA_ERROR_DEFINITION_TYPE.format(schema))

        self.validation_schema = SchemaValidationSchema(validator)
        self.schema_validator = SchemaValidator(
            None,
            allow_unknown=self.validation_schema,
            error_handler=errors.SchemaErrorHandler,
            target_schema=schema,
            target_validator=validator,
        )

        schema = self.expand(schema)
        self.validate(schema)
        self.schema = schema

    def __delitem__(self, key):
        _new_schema = self.schema.copy()
        try:
            del _new_schema[key]
        except ValueError:
            raise SchemaError("Schema has no field '%s' defined" % key)
        except Exception as e:
            raise e
        else:
            del self.schema[key]

    def __getitem__(self, item):
        return self.schema[item]

    def __iter__(self):
        return iter(self.schema)

    def __len__(self):
        return len(self.schema)

    def __repr__(self):
        return str(self)

    def __setitem__(self, key, value):
        value = self.expand({0: value})[0]
        self.validate({key: value})
        self.schema[key] = value

    def __str__(self):
        if hasattr(self, "schema"):
            return str(self.schema)
        else:
            return "No schema data is set yet."

    def copy(self):
        return self.__class__(self.validator, self.schema.copy())

    @classmethod
    def expand(cls, schema):
        try:
            schema = cls._expand_logical_shortcuts(schema)
            schema = cls._expand_subschemas(schema)
        except Exception:
            pass

        # TODO remove this with the next major release
        schema = cls._rename_deprecated_rulenames(schema)

        return schema

    @classmethod
    def _expand_logical_shortcuts(cls, schema):
        """ Expand agglutinated rules in a definition-schema.

        :param schema: The schema-definition to expand.
        :return: The expanded schema-definition.
        """

        def is_of_rule(x):
            return isinstance(x, _str_type) and x.startswith(
                ('allof_', 'anyof_', 'noneof_', 'oneof_')
            )

        for field, rules in schema.items():
            for of_rule in [x for x in rules if is_of_rule(x)]:
                operator, rule = of_rule.split('_', 1)
                rules.update({operator: []})
                for value in rules[of_rule]:
                    rules[operator].append({rule: value})
                del rules[of_rule]
        return schema

    @classmethod
    def _expand_subschemas(cls, schema):
        def has_schema_rule():
            return isinstance(schema[field], Mapping) and 'schema' in schema[field]

        def has_mapping_schema():
            """ Tries to determine heuristically if the schema-constraints are
                aimed to mappings. """
            try:
                return all(
                    isinstance(x, Mapping) for x in schema[field]['schema'].values()
                )
            except TypeError:
                return False

        for field in schema:
            if not has_schema_rule():
                pass
            elif has_mapping_schema():
                schema[field]['schema'] = cls.expand(schema[field]['schema'])
            else:  # assumes schema-constraints for a sequence
                schema[field]['schema'] = cls.expand({0: schema[field]['schema']})[0]

            # TODO remove the last two values in the tuple with the next major release
            for rule in ('keysrules', 'valuesrules', 'keyschema', 'valueschema'):
                if rule in schema[field]:
                    schema[field][rule] = cls.expand({0: schema[field][rule]})[0]

            for rule in ('allof', 'anyof', 'items', 'noneof', 'oneof'):
                if rule in schema[field]:
                    if not isinstance(schema[field][rule], Sequence):
                        continue
                    new_rules_definition = []
                    for item in schema[field][rule]:
                        new_rules_definition.append(cls.expand({0: item})[0])
                    schema[field][rule] = new_rules_definition
        return schema

    def get(self, item, default=None):
        return self.schema.get(item, default)

    def items(self):
        return self.schema.items()

    def update(self, schema):
        try:
            schema = self.expand(schema)
            _new_schema = self.schema.copy()
            _new_schema.update(schema)
            self.validate(_new_schema)
        except ValueError:
            raise SchemaError(errors.SCHEMA_ERROR_DEFINITION_TYPE.format(schema))
        except Exception as e:
            raise e
        else:
            self.schema = _new_schema

    # TODO remove with next major release
    @staticmethod
    def _rename_deprecated_rulenames(schema):
        for field, rules in schema.items():

            if isinstance(rules, str):  # registry reference
                continue

            for old, new in (
                ('keyschema', 'keysrules'),
                ('validator', 'check_with'),
                ('valueschema', 'valuesrules'),
            ):

                if old not in rules:
                    continue

                if new in rules:
                    raise RuntimeError(
                        "The rule '{new}' is also present with its old "
                        "name '{old}' in the same set of rules."
                    )

                warn(
                    "The rule '{old}' was renamed to '{new}'. The old name will "
                    "not be available in the next major release of "
                    "Cerberus.".format(old=old, new=new),
                    DeprecationWarning,
                )
                schema[field][new] = schema[field][old]
                schema[field].pop(old)

        return schema

    def regenerate_validation_schema(self):
        self.validation_schema = SchemaValidationSchema(self.validator)

    def validate(self, schema=None):
        """ Validates a schema that defines rules against supported rules.

        :param schema: The schema to be validated as a legal cerberus schema
                       according to the rules of the assigned Validator object.
                       Raises a :class:`~cerberus.base.SchemaError` when an invalid
                       schema is encountered. """
        if schema is None:
            schema = self.schema
        _hash = (mapping_hash(schema), mapping_hash(self.validator.types_mapping))
        if _hash not in self.validator._valid_schemas:
            self._validate(schema)
            self.validator._valid_schemas.add(_hash)

    def _validate(self, schema):
        if isinstance(schema, _str_type):
            schema = self.validator.schema_registry.get(schema, schema)

        if schema is None:
            raise SchemaError(errors.SCHEMA_ERROR_MISSING)

        schema = copy(schema)
        for field in schema:
            if isinstance(schema[field], _str_type):
                schema[field] = rules_set_registry.get(schema[field], schema[field])

        if not self.schema_validator(schema, normalize=False):
            raise SchemaError(self.schema_validator.errors)


class UnvalidatedSchema(DefinitionSchema):
    def __init__(self, schema={}):
        if not isinstance(schema, Mapping):
            schema = dict(schema)
        self.schema = schema

    def validate(self, schema):
        pass

    def copy(self):
        # Override ancestor's copy, because
        # UnvalidatedSchema does not have .validator:
        return self.__class__(self.schema.copy())


class SchemaValidationSchema(UnvalidatedSchema):
    def __init__(self, validator):
        self.schema = {
            'allow_unknown': False,
            'schema': validator.rules,
            'type': 'dict',
        }


class SchemaValidatorMixin(object):
    """ This validator mixin provides mechanics to validate schemas passed to a Cerberus
        validator. """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('known_rules_set_refs', set())
        kwargs.setdefault('known_schema_refs', set())
        super(SchemaValidatorMixin, self).__init__(*args, **kwargs)

    @property
    def known_rules_set_refs(self):
        """ The encountered references to rules set registry items. """
        return self._config['known_rules_set_refs']

    @property
    def known_schema_refs(self):
        """ The encountered references to schema registry items. """
        return self._config['known_schema_refs']

    @property
    def target_schema(self):
        """ The schema that is being validated. """
        return self._config['target_schema']

    @property
    def target_validator(self):
        """ The validator whose schema is being validated. """
        return self._config['target_validator']

    def _check_with_bulk_schema(self, field, value):
        # resolve schema registry reference
        if isinstance(value, _str_type):
            if value in self.known_rules_set_refs:
                return
            else:
                self.known_rules_set_refs.add(value)
            definition = self.target_validator.rules_set_registry.get(value)
            if definition is None:
                self._error(field, 'Rules set definition %s not found.' % value)
                return
            else:
                value = definition

        _hash = (
            mapping_hash({'turing': value}),
            mapping_hash(self.target_validator.types_mapping),
        )
        if _hash in self.target_validator._valid_schemas:
            return

        validator = self._get_child_validator(
            document_crumb=field,
            allow_unknown=False,
            schema=self.target_validator.rules,
        )
        validator(value, normalize=False)
        if validator._errors:
            self._error(validator._errors)
        else:
            self.target_validator._valid_schemas.add(_hash)

    def _check_with_dependencies(self, field, value):
        if isinstance(value, _str_type):
            pass
        elif isinstance(value, Mapping):
            validator = self._get_child_validator(
                document_crumb=field,
                schema={'valuesrules': {'type': 'list'}},
                allow_unknown=True,
            )
            if not validator(value, normalize=False):
                self._error(validator._errors)
        elif isinstance(value, Sequence):
            if not all(isinstance(x, Hashable) for x in value):
                path = self.document_path + (field,)
                self._error(path, 'All dependencies must be a hashable type.')

    def _check_with_items(self, field, value):
        for i, schema in enumerate(value):
            self._check_with_bulk_schema((field, i), schema)

    def _check_with_schema(self, field, value):
        try:
            value = self._handle_schema_reference_for_validator(field, value)
        except _Abort:
            return

        _hash = (mapping_hash(value), mapping_hash(self.target_validator.types_mapping))
        if _hash in self.target_validator._valid_schemas:
            return

        validator = self._get_child_validator(
            document_crumb=field, schema=None, allow_unknown=self.root_allow_unknown
        )
        validator(self._expand_rules_set_refs(value), normalize=False)
        if validator._errors:
            self._error(validator._errors)
        else:
            self.target_validator._valid_schemas.add(_hash)

    def _check_with_type(self, field, value):
        value = set((value,)) if isinstance(value, _str_type) else set(value)
        invalid_constraints = value - set(self.target_validator.types)
        if invalid_constraints:
            self._error(
                field, 'Unsupported types: {}'.format(', '.join(invalid_constraints))
            )

    def _expand_rules_set_refs(self, schema):
        result = {}
        for k, v in schema.items():
            if isinstance(v, _str_type):
                result[k] = self.target_validator.rules_set_registry.get(v)
            else:
                result[k] = v
        return result

    def _handle_schema_reference_for_validator(self, field, value):
        if not isinstance(value, _str_type):
            return value
        if value in self.known_schema_refs:
            raise _Abort

        self.known_schema_refs.add(value)
        definition = self.target_validator.schema_registry.get(value)
        if definition is None:
            path = self.document_path + (field,)
            self._error(path, 'Schema definition {} not found.'.format(value))
            raise _Abort
        return definition

    def _validate_logical(self, rule, field, value):
        """ {'allowed': ('allof', 'anyof', 'noneof', 'oneof')} """
        if not isinstance(value, Sequence):
            self._error(field, errors.BAD_TYPE)
            return

        validator = self._get_child_validator(
            document_crumb=rule,
            allow_unknown=False,
            schema=self.target_validator.validation_rules,
        )

        for constraints in value:
            _hash = (
                mapping_hash({'turing': constraints}),
                mapping_hash(self.target_validator.types_mapping),
            )
            if _hash in self.target_validator._valid_schemas:
                continue

            validator(constraints, normalize=False)
            if validator._errors:
                self._error(validator._errors)
            else:
                self.target_validator._valid_schemas.add(_hash)


####


class Registry(object):
    """ A registry to store and retrieve schemas and parts of it by a name
    that can be used in validation schemas.

    :param definitions: Optional, initial definitions.
    :type definitions: any :term:`mapping` """

    def __init__(self, definitions={}):
        self._storage = {}
        self.extend(definitions)

    def add(self, name, definition):
        """ Register a definition to the registry. Existing definitions are
        replaced silently.

        :param name: The name which can be used as reference in a validation
                     schema.
        :type name: :class:`str`
        :param definition: The definition.
        :type definition: any :term:`mapping` """
        self._storage[name] = self._expand_definition(definition)

    def all(self):
        """ Returns a :class:`dict` with all registered definitions mapped to
        their name. """
        return self._storage

    def clear(self):
        """ Purge all definitions in the registry. """
        self._storage.clear()

    def extend(self, definitions):
        """ Add several definitions at once. Existing definitions are
        replaced silently.

        :param definitions: The names and definitions.
        :type definitions: a :term:`mapping` or an :term:`iterable` with
                           two-value :class:`tuple` s """
        for name, definition in dict(definitions).items():
            self.add(name, definition)

    def get(self, name, default=None):
        """ Retrieve a definition from the registry.

        :param name: The reference that points to the definition.
        :type name: :class:`str`
        :param default: Return value if the reference isn't registered. """
        return self._storage.get(name, default)

    def remove(self, *names):
        """ Unregister definitions from the registry.

        :param names: The names of the definitions that are to be
                      unregistered. """
        for name in names:
            self._storage.pop(name, None)


class SchemaRegistry(Registry):
    @classmethod
    def _expand_definition(cls, definition):
        return DefinitionSchema.expand(definition)


class RulesSetRegistry(Registry):
    @classmethod
    def _expand_definition(cls, definition):
        return DefinitionSchema.expand({0: definition})[0]


schema_registry, rules_set_registry = SchemaRegistry(), RulesSetRegistry()
