"""
    Extensible validation for Python dictionaries.
    This module implements Cerberus Validator class

    :copyright: 2012-2016 by Nicola Iarocci.
    :license: ISC, see LICENSE for more details.

    Full documentation is available at http://python-cerberus.org
"""

from __future__ import absolute_import

from ast import literal_eval
from copy import copy
from datetime import date, datetime
import re
from warnings import warn

from cerberus import errors
from cerberus.platform import (
    _int_types,
    _str_type,
    Container,
    Hashable,
    Iterable,
    Mapping,
    Sequence,
    Sized,
)
from cerberus.schema import (
    schema_registry,
    rules_set_registry,
    DefinitionSchema,
    SchemaError,
)
from cerberus.utils import drop_item_from_tuple, readonly_classproperty, TypeDefinition

toy_error_handler = errors.ToyErrorHandler()


def dummy_for_rule_validation(rule_constraints):
    def dummy(self, constraint, field, value):
        raise RuntimeError(
            'Dummy method called. Its purpose is to hold just'
            'validation constraints for a rule in its '
            'docstring.'
        )

    f = dummy
    f.__doc__ = rule_constraints
    return f


class DocumentError(Exception):
    """ Raised when the target document is missing or has the wrong format """

    pass


class _SchemaRuleTypeError(Exception):
    """ Raised when a schema (list) validation encounters a mapping.
        Not supposed to be used outside this module. """

    pass


class BareValidator(object):
    """ Validator class. Normalizes and/or validates any mapping against a
    validation-schema which is provided as an argument at class instantiation
    or upon calling the :meth:`~cerberus.Validator.validate`,
    :meth:`~cerberus.Validator.validated` or
    :meth:`~cerberus.Validator.normalized` method. An instance itself is
    callable and executes a validation.

    All instantiation parameters are optional.

    There are the introspective properties :attr:`types`, :attr:`validators`,
    :attr:`coercers`, :attr:`default_setters`, :attr:`rules`,
    :attr:`normalization_rules` and :attr:`validation_rules`.

    The attributes reflecting the available rules are assembled considering
    constraints that are defined in the docstrings of rules' methods and is
    effectively used as validation schema for :attr:`schema`.

    :param schema: See :attr:`~cerberus.Validator.schema`.
                   Defaults to :obj:`None`.
    :type schema: any :term:`mapping`
    :param ignore_none_values: See :attr:`~cerberus.Validator.ignore_none_values`.
                               Defaults to ``False``.
    :type ignore_none_values: :class:`bool`
    :param allow_unknown: See :attr:`~cerberus.Validator.allow_unknown`.
                          Defaults to ``False``.
    :type allow_unknown: :class:`bool` or any :term:`mapping`
    :param require_all: See :attr:`~cerberus.Validator.require_all`.
                        Defaults to ``False``.
    :type require_all: :class:`bool`
    :param purge_unknown: See :attr:`~cerberus.Validator.purge_unknown`.
                          Defaults to to ``False``.
    :type purge_unknown: :class:`bool`
    :param purge_readonly: Removes all fields that are defined as ``readonly`` in the
                           normalization phase.
    :type purge_readonly: :class:`bool`
    :param error_handler: The error handler that formats the result of
                          :attr:`~cerberus.Validator.errors`.
                          When given as two-value tuple with an error-handler
                          class and a dictionary, the latter is passed to the
                          initialization of the error handler.
                          Default: :class:`~cerberus.errors.BasicErrorHandler`.
    :type error_handler: class or instance based on
                         :class:`~cerberus.errors.BaseErrorHandler` or
                         :class:`tuple`
    """  # noqa: E501

    mandatory_validations = ('nullable',)
    """ Rules that are evaluated on any field, regardless whether defined in
        the schema or not.
        Type: :class:`tuple` """
    priority_validations = ('nullable', 'readonly', 'type', 'empty')
    """ Rules that will be processed in that order before any other.
        Type: :class:`tuple` """
    types_mapping = {
        'binary': TypeDefinition('binary', (bytes, bytearray), ()),
        'boolean': TypeDefinition('boolean', (bool,), ()),
        'container': TypeDefinition('container', (Container,), (_str_type,)),
        'date': TypeDefinition('date', (date,), ()),
        'datetime': TypeDefinition('datetime', (datetime,), ()),
        'dict': TypeDefinition('dict', (Mapping,), ()),
        'float': TypeDefinition('float', (float, _int_types), ()),
        'integer': TypeDefinition('integer', (_int_types,), ()),
        'list': TypeDefinition('list', (Sequence,), (_str_type,)),
        'number': TypeDefinition('number', (_int_types, float), (bool,)),
        'set': TypeDefinition('set', (set,), ()),
        'string': TypeDefinition('string', (_str_type), ()),
    }
    """ This mapping holds all available constraints for the type rule and
        their assigned :class:`~cerberus.TypeDefinition`. """
    _valid_schemas = set()
    """ A :class:`set` of hashes derived from validation schemas that are
        legit for a particular ``Validator`` class. """

    def __init__(self, *args, **kwargs):
        """ The arguments will be treated as with this signature:

        __init__(self, schema=None, ignore_none_values=False,
                 allow_unknown=False, require_all=False,
                 purge_unknown=False, purge_readonly=False,
                 error_handler=errors.BasicErrorHandler)
        """

        self.document = None
        """ The document that is or was recently processed.
            Type: any :term:`mapping` """
        self._errors = errors.ErrorList()
        """ The list of errors that were encountered since the last document
            processing was invoked.
            Type: :class:`~cerberus.errors.ErrorList` """
        self.recent_error = None
        """ The last individual error that was submitted.
            Type: :class:`~cerberus.errors.ValidationError` """
        self.document_error_tree = errors.DocumentErrorTree()
        """ A tree representiation of encountered errors following the
            structure of the document.
            Type: :class:`~cerberus.errors.DocumentErrorTree` """
        self.schema_error_tree = errors.SchemaErrorTree()
        """ A tree representiation of encountered errors following the
            structure of the schema.
            Type: :class:`~cerberus.errors.SchemaErrorTree` """
        self.document_path = ()
        """ The path within the document to the current sub-document.
            Type: :class:`tuple` """
        self.schema_path = ()
        """ The path within the schema to the current sub-schema.
            Type: :class:`tuple` """
        self.update = False
        self.error_handler = self.__init_error_handler(kwargs)
        """ The error handler used to format :attr:`~cerberus.Validator.errors`
            and process submitted errors with
            :meth:`~cerberus.Validator._error`.
            Type: :class:`~cerberus.errors.BaseErrorHandler` """
        self.__store_config(args, kwargs)
        self.schema = kwargs.get('schema', None)
        self.allow_unknown = kwargs.get('allow_unknown', False)
        self.require_all = kwargs.get('require_all', False)
        self._remaining_rules = []
        """ Keeps track of the rules that are next in line to be evaluated
            during the validation of a field.
            Type: :class:`list` """

        super(BareValidator, self).__init__()

    @staticmethod
    def __init_error_handler(kwargs):
        error_handler = kwargs.pop('error_handler', errors.BasicErrorHandler)
        if isinstance(error_handler, tuple):
            error_handler, eh_config = error_handler
        else:
            eh_config = {}
        if isinstance(error_handler, type) and issubclass(
            error_handler, errors.BaseErrorHandler
        ):
            return error_handler(**eh_config)
        elif isinstance(error_handler, errors.BaseErrorHandler):
            return error_handler
        else:
            raise RuntimeError('Invalid error_handler.')

    def __store_config(self, args, kwargs):
        """ Assign args to kwargs and store configuration. """
        signature = (
            'schema',
            'ignore_none_values',
            'allow_unknown',
            'require_all',
            'purge_unknown',
            'purge_readonly',
        )
        for i, p in enumerate(signature[: len(args)]):
            if p in kwargs:
                raise TypeError("__init__ got multiple values for argument " "'%s'" % p)
            else:
                kwargs[p] = args[i]
        self._config = kwargs
        """ This dictionary holds the configuration arguments that were used to
            initialize the :class:`Validator` instance except the
            ``error_handler``. """

    @classmethod
    def clear_caches(cls):
        """ Purge the cache of known valid schemas. """
        cls._valid_schemas.clear()

    def _error(self, *args):
        """ Creates and adds one or multiple errors.

        :param args: Accepts different argument's signatures.

                     *1. Bulk addition of errors:*

                     - :term:`iterable` of
                       :class:`~cerberus.errors.ValidationError`-instances

                     The errors will be added to
                     :attr:`~cerberus.Validator._errors`.

                     *2. Custom error:*

                     - the invalid field's name

                     - the error message

                     A custom error containing the message will be created and
                     added to :attr:`~cerberus.Validator._errors`.
                     There will however be fewer information contained in the
                     error (no reference to the violated rule and its
                     constraint).

                     *3. Defined error:*

                     - the invalid field's name

                     - the error-reference, see :mod:`cerberus.errors`

                     - arbitrary, supplemental information about the error

                     A :class:`~cerberus.errors.ValidationError` instance will
                     be created and added to
                     :attr:`~cerberus.Validator._errors`.
        """
        if len(args) == 1:
            self._errors.extend(args[0])
            self._errors.sort()
            for error in args[0]:
                self.document_error_tree.add(error)
                self.schema_error_tree.add(error)
                self.error_handler.emit(error)
        elif len(args) == 2 and isinstance(args[1], _str_type):
            self._error(args[0], errors.CUSTOM, args[1])
        elif len(args) >= 2:
            field = args[0]
            code = args[1].code
            rule = args[1].rule
            info = args[2:]

            document_path = self.document_path + (field,)

            schema_path = self.schema_path
            if code != errors.UNKNOWN_FIELD.code and rule is not None:
                schema_path += (field, rule)

            if not rule:
                constraint = None
            else:
                field_definitions = self._resolve_rules_set(self.schema[field])
                if rule == 'nullable':
                    constraint = field_definitions.get(rule, False)
                elif rule == 'required':
                    constraint = field_definitions.get(rule, self.require_all)
                    if rule not in field_definitions:
                        schema_path = "__require_all__"
                else:
                    constraint = field_definitions[rule]

            value = self.document.get(field)

            self.recent_error = errors.ValidationError(
                document_path, schema_path, code, rule, constraint, value, info
            )
            self._error([self.recent_error])

    def _get_child_validator(self, document_crumb=None, schema_crumb=None, **kwargs):
        """ Creates a new instance of Validator-(sub-)class. All initial
            parameters of the parent are passed to the initialization, unless
            a parameter is given as an explicit *keyword*-parameter.

        :param document_crumb: Extends the
                               :attr:`~cerberus.Validator.document_path`
                               of the child-validator.
        :type document_crumb: :class:`tuple` or :term:`hashable`
        :param schema_crumb: Extends the
                             :attr:`~cerberus.Validator.schema_path`
                             of the child-validator.
        :type schema_crumb: :class:`tuple` or hashable
        :param kwargs: Overriding keyword-arguments for initialization.
        :type kwargs: :class:`dict`

        :return: an instance of ``self.__class__``
        """
        child_config = self._config.copy()
        child_config.update(kwargs)
        if not self.is_child:
            child_config['is_child'] = True
            child_config['error_handler'] = toy_error_handler
            child_config['root_allow_unknown'] = self.allow_unknown
            child_config['root_require_all'] = self.require_all
            child_config['root_document'] = self.document
            child_config['root_schema'] = self.schema

        child_validator = self.__class__(**child_config)

        if document_crumb is None:
            child_validator.document_path = self.document_path
        else:
            if not isinstance(document_crumb, tuple):
                document_crumb = (document_crumb,)
            child_validator.document_path = self.document_path + document_crumb

        if schema_crumb is None:
            child_validator.schema_path = self.schema_path
        else:
            if not isinstance(schema_crumb, tuple):
                schema_crumb = (schema_crumb,)
            child_validator.schema_path = self.schema_path + schema_crumb

        return child_validator

    def __get_rule_handler(self, domain, rule):
        methodname = '_{0}_{1}'.format(domain, rule.replace(' ', '_'))
        result = getattr(self, methodname, None)
        if result is None:
            raise RuntimeError(
                "There's no handler for '{}' in the '{}' "
                "domain.".format(rule, domain)
            )
        return result

    def _drop_nodes_from_errorpaths(self, _errors, dp_items, sp_items):
        """ Removes nodes by index from an errorpath, relatively to the
            basepaths of self.

        :param errors: A list of :class:`errors.ValidationError` instances.
        :param dp_items: A list of integers, pointing at the nodes to drop from
                         the :attr:`document_path`.
        :param sp_items: Alike ``dp_items``, but for :attr:`schema_path`.
        """
        dp_basedepth = len(self.document_path)
        sp_basedepth = len(self.schema_path)
        for error in _errors:
            for i in sorted(dp_items, reverse=True):
                error.document_path = drop_item_from_tuple(
                    error.document_path, dp_basedepth + i
                )
            for i in sorted(sp_items, reverse=True):
                error.schema_path = drop_item_from_tuple(
                    error.schema_path, sp_basedepth + i
                )
            if error.child_errors:
                self._drop_nodes_from_errorpaths(error.child_errors, dp_items, sp_items)

    def _lookup_field(self, path):
        """ Searches for a field as defined by path. This method is used by the
            ``dependency`` evaluation logic.

        :param path: Path elements are separated by a ``.``. A leading ``^``
                     indicates that the path relates to the document root,
                     otherwise it relates to the currently evaluated document,
                     which is possibly a subdocument.
                     The sequence ``^^`` at the start will be interpreted as a
                     literal ``^``.
        :type path: :class:`str`
        :returns: Either the found field name and its value or :obj:`None` for
                  both.
        :rtype: A two-value :class:`tuple`.
        """
        if path.startswith('^'):
            path = path[1:]
            context = self.document if path.startswith('^') else self.root_document
        else:
            context = self.document

        parts = path.split('.')
        for part in parts:
            if part not in context:
                return None, None
            context = context.get(part, {})

        return parts[-1], context

    def _resolve_rules_set(self, rules_set):
        if isinstance(rules_set, Mapping):
            return rules_set
        elif isinstance(rules_set, _str_type):
            return self.rules_set_registry.get(rules_set)
        return None

    def _resolve_schema(self, schema):
        if isinstance(schema, Mapping):
            return schema
        elif isinstance(schema, _str_type):
            return self.schema_registry.get(schema)
        return None

    # Properties

    @property
    def allow_unknown(self):
        """ If ``True`` unknown fields that are not defined in the schema will
            be ignored. If a mapping with a validation schema is given, any
            undefined field will be validated against its rules.
            Also see :ref:`allowing-the-unknown`.
            Type: :class:`bool` or any :term:`mapping` """
        return self._config.get('allow_unknown', False)

    @allow_unknown.setter
    def allow_unknown(self, value):
        if not (self.is_child or isinstance(value, (bool, DefinitionSchema))):
            DefinitionSchema(self, {'allow_unknown': value})
        self._config['allow_unknown'] = value

    @property
    def require_all(self):
        """ If ``True`` known fields that are defined in the schema will
            be required.
            Type: :class:`bool` """
        return self._config.get('require_all', False)

    @require_all.setter
    def require_all(self, value):
        self._config['require_all'] = value

    @property
    def errors(self):
        """ The errors of the last processing formatted by the handler that is
            bound to :attr:`~cerberus.Validator.error_handler`. """
        return self.error_handler(self._errors)

    @property
    def ignore_none_values(self):
        """ Whether to not process :obj:`None`-values in a document or not.
            Type: :class:`bool` """
        return self._config.get('ignore_none_values', False)

    @ignore_none_values.setter
    def ignore_none_values(self, value):
        self._config['ignore_none_values'] = value

    @property
    def is_child(self):
        """ ``True`` for child-validators obtained with
        :meth:`~cerberus.Validator._get_child_validator`.
        Type: :class:`bool` """
        return self._config.get('is_child', False)

    @property
    def _is_normalized(self):
        """ ``True`` if the document is already normalized. """
        return self._config.get('_is_normalized', False)

    @_is_normalized.setter
    def _is_normalized(self, value):
        self._config['_is_normalized'] = value

    @property
    def purge_unknown(self):
        """ If ``True``, unknown fields will be deleted from the document
            unless a validation is called with disabled normalization.
            Also see :ref:`purging-unknown-fields`. Type: :class:`bool` """
        return self._config.get('purge_unknown', False)

    @purge_unknown.setter
    def purge_unknown(self, value):
        self._config['purge_unknown'] = value

    @property
    def purge_readonly(self):
        """ If ``True``, fields declared as readonly will be deleted from the
            document unless a validation is called with disabled normalization.
            Type: :class:`bool` """
        return self._config.get('purge_readonly', False)

    @purge_readonly.setter
    def purge_readonly(self, value):
        self._config['purge_readonly'] = value

    @property
    def root_allow_unknown(self):
        """ The :attr:`~cerberus.Validator.allow_unknown` attribute of the
            first level ancestor of a child validator. """
        return self._config.get('root_allow_unknown', self.allow_unknown)

    @property
    def root_require_all(self):
        """ The :attr:`~cerberus.Validator.require_all` attribute of
            the first level ancestor of a child validator. """
        return self._config.get('root_require_all', self.require_all)

    @property
    def root_document(self):
        """ The :attr:`~cerberus.Validator.document` attribute of the
            first level ancestor of a child validator. """
        return self._config.get('root_document', self.document)

    @property
    def rules_set_registry(self):
        """ The registry that holds referenced rules sets.
            Type: :class:`~cerberus.Registry` """
        return self._config.get('rules_set_registry', rules_set_registry)

    @rules_set_registry.setter
    def rules_set_registry(self, registry):
        self._config['rules_set_registry'] = registry

    @property
    def root_schema(self):
        """ The :attr:`~cerberus.Validator.schema` attribute of the
            first level ancestor of a child validator. """
        return self._config.get('root_schema', self.schema)

    @property
    def schema(self):
        """ The validation schema of a validator. When a schema is passed to
            a method, it replaces this attribute.
            Type: any :term:`mapping` or :obj:`None` """
        return self._schema

    @schema.setter
    def schema(self, schema):
        if schema is None:
            self._schema = None
        elif self.is_child or isinstance(schema, DefinitionSchema):
            self._schema = schema
        else:
            self._schema = DefinitionSchema(self, schema)

    @property
    def schema_registry(self):
        """ The registry that holds referenced schemas.
            Type: :class:`~cerberus.Registry` """
        return self._config.get('schema_registry', schema_registry)

    @schema_registry.setter
    def schema_registry(self, registry):
        self._config['schema_registry'] = registry

    # FIXME the returned method has the correct docstring, but doesn't appear
    #       in the API docs
    @readonly_classproperty
    def types(cls):
        """ The constraints that can be used for the 'type' rule.
            Type: A tuple of strings. """
        redundant_types = set(cls.types_mapping) & set(cls._types_from_methods)
        if redundant_types:
            warn(
                "These types are defined both with a method and in the"
                "'types_mapping' property of this validator: %s" % redundant_types
            )

        return tuple(cls.types_mapping) + cls._types_from_methods

    # Document processing

    def __init_processing(self, document, schema=None):
        self._errors = errors.ErrorList()
        self.recent_error = None
        self.document_error_tree = errors.DocumentErrorTree()
        self.schema_error_tree = errors.SchemaErrorTree()
        self.document = copy(document)
        if not self.is_child:
            self._is_normalized = False

        if schema is not None:
            self.schema = DefinitionSchema(self, schema)
        elif self.schema is None:
            if isinstance(self.allow_unknown, Mapping):
                self._schema = {}
            else:
                raise SchemaError(errors.SCHEMA_ERROR_MISSING)
        if document is None:
            raise DocumentError(errors.DOCUMENT_MISSING)
        if not isinstance(document, Mapping):
            raise DocumentError(errors.DOCUMENT_FORMAT.format(document))
        self.error_handler.start(self)

    def _drop_remaining_rules(self, *rules):
        """ Drops rules from the queue of the rules that still need to be
            evaluated for the currently processed field.
            If no arguments are given, the whole queue is emptied.
        """
        if rules:
            for rule in rules:
                try:
                    self._remaining_rules.remove(rule)
                except ValueError:
                    pass
        else:
            self._remaining_rules = []

    # # Normalizing

    def normalized(self, document, schema=None, always_return_document=False):
        """ Returns the document normalized according to the specified rules
        of a schema.

        :param document: The document to normalize.
        :type document: any :term:`mapping`
        :param schema: The validation schema. Defaults to :obj:`None`. If not
                       provided here, the schema must have been provided at
                       class instantiation.
        :type schema: any :term:`mapping`
        :param always_return_document: Return the document, even if an error
                                       occurred. Defaults to: ``False``.
        :type always_return_document: :class:`bool`
        :return: A normalized copy of the provided mapping or :obj:`None` if an
                 error occurred during normalization.
        """
        self.__init_processing(document, schema)
        self.__normalize_mapping(self.document, self.schema)
        self.error_handler.end(self)
        if self._errors and not always_return_document:
            return None
        else:
            return self.document

    def __normalize_mapping(self, mapping, schema):
        if isinstance(schema, _str_type):
            schema = self._resolve_schema(schema)
        schema = schema.copy()
        for field in schema:
            schema[field] = self._resolve_rules_set(schema[field])

        self.__normalize_rename_fields(mapping, schema)
        if self.purge_unknown and not self.allow_unknown:
            self._normalize_purge_unknown(mapping, schema)
        if self.purge_readonly:
            self.__normalize_purge_readonly(mapping, schema)
        # Check `readonly` fields before applying default values because
        # a field's schema definition might contain both `readonly` and
        # `default`.
        self.__validate_readonly_fields(mapping, schema)
        self.__normalize_default_fields(mapping, schema)
        self._normalize_coerce(mapping, schema)
        self.__normalize_containers(mapping, schema)
        self._is_normalized = True
        return mapping

    def _normalize_coerce(self, mapping, schema):
        """ {'oneof': [
                {'type': 'callable'},
                {'type': 'list',
                 'schema': {'oneof': [{'type': 'callable'},
                                      {'type': 'string'}]}},
                {'type': 'string'}
                ]} """

        error = errors.COERCION_FAILED
        for field in mapping:
            if field in schema and 'coerce' in schema[field]:
                mapping[field] = self.__normalize_coerce(
                    schema[field]['coerce'],
                    field,
                    mapping[field],
                    schema[field].get('nullable', False),
                    error,
                )
            elif (
                isinstance(self.allow_unknown, Mapping)
                and 'coerce' in self.allow_unknown
            ):
                mapping[field] = self.__normalize_coerce(
                    self.allow_unknown['coerce'],
                    field,
                    mapping[field],
                    self.allow_unknown.get('nullable', False),
                    error,
                )

    def __normalize_coerce(self, processor, field, value, nullable, error):
        if isinstance(processor, _str_type):
            processor = self.__get_rule_handler('normalize_coerce', processor)

        elif isinstance(processor, Iterable):
            result = value
            for p in processor:
                result = self.__normalize_coerce(p, field, result, nullable, error)
                if (
                    errors.COERCION_FAILED
                    in self.document_error_tree.fetch_errors_from(
                        self.document_path + (field,)
                    )
                ):
                    break
            return result

        try:
            return processor(value)
        except Exception as e:
            if not (nullable and value is None):
                self._error(field, error, str(e))
            return value

    def __normalize_containers(self, mapping, schema):
        for field in mapping:
            rules = set(schema.get(field, ()))

            # TODO: This check conflates validation and normalization
            if isinstance(mapping[field], Mapping):
                if 'keysrules' in rules:
                    self.__normalize_mapping_per_keysrules(
                        field, mapping, schema[field]['keysrules']
                    )
                if 'valuesrules' in rules:
                    self.__normalize_mapping_per_valuesrules(
                        field, mapping, schema[field]['valuesrules']
                    )
                if rules & set(
                    ('allow_unknown', 'purge_unknown', 'schema')
                ) or isinstance(self.allow_unknown, Mapping):
                    try:
                        self.__normalize_mapping_per_schema(field, mapping, schema)
                    except _SchemaRuleTypeError:
                        pass

            elif isinstance(mapping[field], _str_type):
                continue

            elif isinstance(mapping[field], Sequence):
                if 'schema' in rules:
                    self.__normalize_sequence_per_schema(field, mapping, schema)
                elif 'items' in rules:
                    self.__normalize_sequence_per_items(field, mapping, schema)

    def __normalize_mapping_per_keysrules(self, field, mapping, property_rules):
        schema = dict(((k, property_rules) for k in mapping[field]))
        document = dict(((k, k) for k in mapping[field]))
        validator = self._get_child_validator(
            document_crumb=field, schema_crumb=(field, 'keysrules'), schema=schema
        )
        result = validator.normalized(document, always_return_document=True)
        if validator._errors:
            self._drop_nodes_from_errorpaths(validator._errors, [], [2, 4])
            self._error(validator._errors)
        for k in result:
            if k == result[k]:
                continue
            if result[k] in mapping[field]:
                warn(
                    "Normalizing keys of {path}: {key} already exists, "
                    "its value is replaced.".format(
                        path='.'.join(str(x) for x in self.document_path + (field,)),
                        key=k,
                    )
                )
                mapping[field][result[k]] = mapping[field][k]
            else:
                mapping[field][result[k]] = mapping[field][k]
                del mapping[field][k]

    def __normalize_mapping_per_valuesrules(self, field, mapping, value_rules):
        schema = dict(((k, value_rules) for k in mapping[field]))
        validator = self._get_child_validator(
            document_crumb=field, schema_crumb=(field, 'valuesrules'), schema=schema
        )
        mapping[field] = validator.normalized(
            mapping[field], always_return_document=True
        )
        if validator._errors:
            self._drop_nodes_from_errorpaths(validator._errors, [], [2])
            self._error(validator._errors)

    def __normalize_mapping_per_schema(self, field, mapping, schema):
        rules = schema.get(field, {})
        if not rules and isinstance(self.allow_unknown, Mapping):
            rules = self.allow_unknown
        validator = self._get_child_validator(
            document_crumb=field,
            schema_crumb=(field, 'schema'),
            schema=rules.get('schema', {}),
            allow_unknown=rules.get('allow_unknown', self.allow_unknown),  # noqa: E501
            purge_unknown=rules.get('purge_unknown', self.purge_unknown),
            require_all=rules.get('require_all', self.require_all),
        )  # noqa: E501
        value_type = type(mapping[field])
        result_value = validator.normalized(mapping[field], always_return_document=True)
        mapping[field] = value_type(result_value)
        if validator._errors:
            self._error(validator._errors)

    def __normalize_sequence_per_schema(self, field, mapping, schema):
        schema = dict(
            ((k, schema[field]['schema']) for k in range(len(mapping[field])))
        )
        document = dict((k, v) for k, v in enumerate(mapping[field]))
        validator = self._get_child_validator(
            document_crumb=field, schema_crumb=(field, 'schema'), schema=schema
        )
        value_type = type(mapping[field])
        result = validator.normalized(document, always_return_document=True)
        mapping[field] = value_type(result.values())
        if validator._errors:
            self._drop_nodes_from_errorpaths(validator._errors, [], [2])
            self._error(validator._errors)

    def __normalize_sequence_per_items(self, field, mapping, schema):
        rules, values = schema[field]['items'], mapping[field]
        if len(rules) != len(values):
            return
        schema = dict(((k, v) for k, v in enumerate(rules)))
        document = dict((k, v) for k, v in enumerate(values))
        validator = self._get_child_validator(
            document_crumb=field, schema_crumb=(field, 'items'), schema=schema
        )
        value_type = type(mapping[field])
        result = validator.normalized(document, always_return_document=True)
        mapping[field] = value_type(result.values())
        if validator._errors:
            self._drop_nodes_from_errorpaths(validator._errors, [], [2])
            self._error(validator._errors)

    @staticmethod
    def __normalize_purge_readonly(mapping, schema):
        for field in [x for x in mapping if schema.get(x, {}).get('readonly', False)]:
            mapping.pop(field)
        return mapping

    @staticmethod
    def _normalize_purge_unknown(mapping, schema):
        """ {'type': 'boolean'} """
        for field in [x for x in mapping if x not in schema]:
            mapping.pop(field)
        return mapping

    def __normalize_rename_fields(self, mapping, schema):
        for field in tuple(mapping):
            if field in schema:
                self._normalize_rename(mapping, schema, field)
                self._normalize_rename_handler(mapping, schema, field)
            elif (
                isinstance(self.allow_unknown, Mapping)
                and 'rename_handler' in self.allow_unknown
            ):
                self._normalize_rename_handler(
                    mapping, {field: self.allow_unknown}, field
                )
        return mapping

    def _normalize_rename(self, mapping, schema, field):
        """ {'type': 'hashable'} """
        if 'rename' in schema[field]:
            mapping[schema[field]['rename']] = mapping[field]
            del mapping[field]

    def _normalize_rename_handler(self, mapping, schema, field):
        """ {'oneof': [
                {'type': 'callable'},
                {'type': 'list',
                 'schema': {'oneof': [{'type': 'callable'},
                                      {'type': 'string'}]}},
                {'type': 'string'}
                ]} """
        if 'rename_handler' not in schema[field]:
            return
        new_name = self.__normalize_coerce(
            schema[field]['rename_handler'], field, field, False, errors.RENAMING_FAILED
        )
        if new_name != field:
            mapping[new_name] = mapping[field]
            del mapping[field]

    def __validate_readonly_fields(self, mapping, schema):
        for field in (
            x
            for x in schema
            if x in mapping and self._resolve_rules_set(schema[x]).get('readonly')
        ):
            self._validate_readonly(schema[field]['readonly'], field, mapping[field])

    def __normalize_default_fields(self, mapping, schema):
        empty_fields = [
            x
            for x in schema
            if x not in mapping
            or (
                mapping[x] is None  # noqa: W503
                and not schema[x].get('nullable', False)
            )  # noqa: W503
        ]

        try:
            fields_with_default = [x for x in empty_fields if 'default' in schema[x]]
        except TypeError:
            raise _SchemaRuleTypeError
        for field in fields_with_default:
            self._normalize_default(mapping, schema, field)

        known_fields_states = set()
        fields_with_default_setter = [
            x for x in empty_fields if 'default_setter' in schema[x]
        ]
        while fields_with_default_setter:
            field = fields_with_default_setter.pop(0)
            try:
                self._normalize_default_setter(mapping, schema, field)
            except KeyError:
                fields_with_default_setter.append(field)
            except Exception as e:
                self._error(field, errors.SETTING_DEFAULT_FAILED, str(e))

            fields_processing_state = hash(tuple(fields_with_default_setter))
            if fields_processing_state in known_fields_states:
                for field in fields_with_default_setter:
                    self._error(
                        field,
                        errors.SETTING_DEFAULT_FAILED,
                        'Circular dependencies of default setters.',
                    )
                break
            else:
                known_fields_states.add(fields_processing_state)

    def _normalize_default(self, mapping, schema, field):
        """ {'nullable': True} """
        mapping[field] = schema[field]['default']

    def _normalize_default_setter(self, mapping, schema, field):
        """ {'oneof': [
                {'type': 'callable'},
                {'type': 'string'}
                ]} """
        if 'default_setter' in schema[field]:
            setter = schema[field]['default_setter']
            if isinstance(setter, _str_type):
                setter = self.__get_rule_handler('normalize_default_setter', setter)
            mapping[field] = setter(mapping)

    # # Validating

    def validate(self, document, schema=None, update=False, normalize=True):
        """ Normalizes and validates a mapping against a validation-schema of
        defined rules.

        :param document: The document to normalize.
        :type document: any :term:`mapping`
        :param schema: The validation schema. Defaults to :obj:`None`. If not
                       provided here, the schema must have been provided at
                       class instantiation.
        :type schema: any :term:`mapping`
        :param update: If ``True``, required fields won't be checked.
        :type update: :class:`bool`
        :param normalize: If ``True``, normalize the document before validation.
        :type normalize: :class:`bool`

        :return: ``True`` if validation succeeds, otherwise ``False``. Check
                 the :func:`errors` property for a list of processing errors.
        :rtype: :class:`bool`
        """
        self.update = update
        self._unrequired_by_excludes = set()

        self.__init_processing(document, schema)
        if normalize:
            self.__normalize_mapping(self.document, self.schema)

        for field in self.document:
            if self.ignore_none_values and self.document[field] is None:
                continue
            definitions = self.schema.get(field)
            if definitions is not None:
                self.__validate_definitions(definitions, field)
            else:
                self.__validate_unknown_fields(field)

        if not self.update:
            self.__validate_required_fields(self.document)

        self.error_handler.end(self)

        return not bool(self._errors)

    __call__ = validate

    def validated(self, *args, **kwargs):
        """ Wrapper around :meth:`~cerberus.Validator.validate` that returns
            the normalized and validated document or :obj:`None` if validation
            failed. """
        always_return_document = kwargs.pop('always_return_document', False)
        self.validate(*args, **kwargs)
        if self._errors and not always_return_document:
            return None
        else:
            return self.document

    def __validate_unknown_fields(self, field):
        if self.allow_unknown:
            value = self.document[field]
            if isinstance(self.allow_unknown, (Mapping, _str_type)):
                # validate that unknown fields matches the schema
                # for unknown_fields
                schema_crumb = 'allow_unknown' if self.is_child else '__allow_unknown__'
                validator = self._get_child_validator(
                    schema_crumb=schema_crumb, schema={field: self.allow_unknown}
                )
                if not validator({field: value}, normalize=False):
                    self._error(validator._errors)
        else:
            self._error(field, errors.UNKNOWN_FIELD)

    def __validate_definitions(self, definitions, field):
        """ Validate a field's value against its defined rules. """

        def validate_rule(rule):
            validator = self.__get_rule_handler('validate', rule)
            return validator(definitions.get(rule, None), field, value)

        definitions = self._resolve_rules_set(definitions)
        value = self.document[field]

        rules_queue = [
            x
            for x in self.priority_validations
            if x in definitions or x in self.mandatory_validations
        ]
        rules_queue.extend(
            x for x in self.mandatory_validations if x not in rules_queue
        )
        rules_queue.extend(
            x
            for x in definitions
            if x not in rules_queue
            and x not in self.normalization_rules
            and x not in ('allow_unknown', 'require_all', 'meta', 'required')
        )
        self._remaining_rules = rules_queue

        while self._remaining_rules:
            rule = self._remaining_rules.pop(0)
            try:
                result = validate_rule(rule)
                # TODO remove on next breaking release
                if result:
                    break
            except _SchemaRuleTypeError:
                break

        self._drop_remaining_rules()

    # Remember to keep the validation methods below this line
    # sorted alphabetically

    _validate_allow_unknown = dummy_for_rule_validation(
        """ {'oneof': [{'type': 'boolean'},
                       {'type': ['dict', 'string'],
                        'check_with': 'bulk_schema'}]} """
    )

    def _validate_allowed(self, allowed_values, field, value):
        """ {'type': 'container'} """
        if isinstance(value, Iterable) and not isinstance(value, _str_type):
            unallowed = set(value) - set(allowed_values)
            if unallowed:
                self._error(field, errors.UNALLOWED_VALUES, list(unallowed))
        else:
            if value not in allowed_values:
                self._error(field, errors.UNALLOWED_VALUE, value)

    def _validate_check_with(self, checks, field, value):
        """ {'oneof': [
                {'type': 'callable'},
                {'type': 'list',
                 'schema': {'oneof': [{'type': 'callable'},
                                      {'type': 'string'}]}},
                {'type': 'string'}
                ]} """
        if isinstance(checks, _str_type):
            try:
                value_checker = self.__get_rule_handler('check_with', checks)
            # TODO remove on next major release
            except RuntimeError:
                value_checker = self.__get_rule_handler('validator', checks)
                warn(
                    "The 'validator' rule was renamed to 'check_with'. Please update "
                    "your schema and method names accordingly.",
                    DeprecationWarning,
                )
            value_checker(field, value)
        elif isinstance(checks, Iterable):
            for v in checks:
                self._validate_check_with(v, field, value)
        else:
            checks(field, value, self._error)

    def _validate_contains(self, expected_values, field, value):
        """ {'empty': False } """
        if not isinstance(value, Iterable):
            return

        if not isinstance(expected_values, Iterable) or isinstance(
            expected_values, _str_type
        ):
            expected_values = set((expected_values,))
        else:
            expected_values = set(expected_values)

        missing_values = expected_values - set(value)
        if missing_values:
            self._error(field, errors.MISSING_MEMBERS, missing_values)

    def _validate_dependencies(self, dependencies, field, value):
        """ {'type': ('dict', 'hashable', 'list'),
             'check_with': 'dependencies'} """
        if isinstance(dependencies, _str_type) or not isinstance(
            dependencies, (Iterable, Mapping)
        ):
            dependencies = (dependencies,)

        if isinstance(dependencies, Sequence):
            self.__validate_dependencies_sequence(dependencies, field)
        elif isinstance(dependencies, Mapping):
            self.__validate_dependencies_mapping(dependencies, field)

        if (
            self.document_error_tree.fetch_node_from(
                self.schema_path + (field, 'dependencies')
            )
            is not None
        ):
            return True

    def __validate_dependencies_mapping(self, dependencies, field):
        validated_dependencies_counter = 0
        error_info = {}
        for dependency_name, dependency_values in dependencies.items():
            if not isinstance(dependency_values, Sequence) or isinstance(
                dependency_values, _str_type
            ):
                dependency_values = [dependency_values]

            wanted_field, wanted_field_value = self._lookup_field(dependency_name)
            if wanted_field_value in dependency_values:
                validated_dependencies_counter += 1
            else:
                error_info.update({dependency_name: wanted_field_value})

        if validated_dependencies_counter != len(dependencies):
            self._error(field, errors.DEPENDENCIES_FIELD_VALUE, error_info)

    def __validate_dependencies_sequence(self, dependencies, field):
        for dependency in dependencies:
            if self._lookup_field(dependency)[0] is None:
                self._error(field, errors.DEPENDENCIES_FIELD, dependency)

    def _validate_empty(self, empty, field, value):
        """ {'type': 'boolean'} """
        if isinstance(value, Sized) and len(value) == 0:
            self._drop_remaining_rules(
                'allowed',
                'forbidden',
                'items',
                'minlength',
                'maxlength',
                'regex',
                'check_with',
            )
            if not empty:
                self._error(field, errors.EMPTY_NOT_ALLOWED)

    def _validate_excludes(self, excluded_fields, field, value):
        """ {'type': ('hashable', 'list'),
             'schema': {'type': 'hashable'}} """
        if isinstance(excluded_fields, Hashable):
            excluded_fields = [excluded_fields]

        # Mark the currently evaluated field as not required for now if it actually is.
        # One of the so marked will be needed to pass when required fields are checked.
        if self.schema[field].get('required', self.require_all):
            self._unrequired_by_excludes.add(field)

        for excluded_field in excluded_fields:
            if excluded_field in self.schema and self.schema[field].get(
                'required', self.require_all
            ):

                self._unrequired_by_excludes.add(excluded_field)

        if any(excluded_field in self.document for excluded_field in excluded_fields):
            exclusion_str = ', '.join(
                "'{0}'".format(field) for field in excluded_fields
            )
            self._error(field, errors.EXCLUDES_FIELD, exclusion_str)

    def _validate_forbidden(self, forbidden_values, field, value):
        """ {'type': 'list'} """
        if isinstance(value, Sequence) and not isinstance(value, _str_type):
            forbidden = set(value) & set(forbidden_values)
            if forbidden:
                self._error(field, errors.FORBIDDEN_VALUES, list(forbidden))
        else:
            if value in forbidden_values:
                self._error(field, errors.FORBIDDEN_VALUE, value)

    def _validate_items(self, items, field, values):
        """ {'type': 'list', 'check_with': 'items'} """
        if len(items) != len(values):
            self._error(field, errors.ITEMS_LENGTH, len(items), len(values))
        else:
            schema = dict(
                (i, definition) for i, definition in enumerate(items)
            )  # noqa: E501
            validator = self._get_child_validator(
                document_crumb=field,
                schema_crumb=(field, 'items'),  # noqa: E501
                schema=schema,
            )
            if not validator(
                dict((i, value) for i, value in enumerate(values)),
                update=self.update,
                normalize=False,
            ):
                self._error(field, errors.BAD_ITEMS, validator._errors)

    def __validate_logical(self, operator, definitions, field, value):
        """ Validates value against all definitions and logs errors according
            to the operator. """
        valid_counter = 0
        _errors = errors.ErrorList()

        for i, definition in enumerate(definitions):
            schema = {field: definition.copy()}
            for rule in ('allow_unknown', 'type'):
                if rule not in schema[field] and rule in self.schema[field]:
                    schema[field][rule] = self.schema[field][rule]
            if 'allow_unknown' not in schema[field]:
                schema[field]['allow_unknown'] = self.allow_unknown

            validator = self._get_child_validator(
                schema_crumb=(field, operator, i), schema=schema, allow_unknown=True
            )
            if validator(self.document, update=self.update, normalize=False):
                valid_counter += 1
            else:
                self._drop_nodes_from_errorpaths(validator._errors, [], [3])
                _errors.extend(validator._errors)

        return valid_counter, _errors

    def _validate_anyof(self, definitions, field, value):
        """ {'type': 'list', 'logical': 'anyof'} """
        valids, _errors = self.__validate_logical('anyof', definitions, field, value)
        if valids < 1:
            self._error(field, errors.ANYOF, _errors, valids, len(definitions))

    def _validate_allof(self, definitions, field, value):
        """ {'type': 'list', 'logical': 'allof'} """
        valids, _errors = self.__validate_logical('allof', definitions, field, value)
        if valids < len(definitions):
            self._error(field, errors.ALLOF, _errors, valids, len(definitions))

    def _validate_noneof(self, definitions, field, value):
        """ {'type': 'list', 'logical': 'noneof'} """
        valids, _errors = self.__validate_logical('noneof', definitions, field, value)
        if valids > 0:
            self._error(field, errors.NONEOF, _errors, valids, len(definitions))

    def _validate_oneof(self, definitions, field, value):
        """ {'type': 'list', 'logical': 'oneof'} """
        valids, _errors = self.__validate_logical('oneof', definitions, field, value)
        if valids != 1:
            self._error(field, errors.ONEOF, _errors, valids, len(definitions))

    def _validate_max(self, max_value, field, value):
        """ {'nullable': False } """
        try:
            if value > max_value:
                self._error(field, errors.MAX_VALUE)
        except TypeError:
            pass

    def _validate_min(self, min_value, field, value):
        """ {'nullable': False } """
        try:
            if value < min_value:
                self._error(field, errors.MIN_VALUE)
        except TypeError:
            pass

    def _validate_maxlength(self, max_length, field, value):
        """ {'type': 'integer'} """
        if isinstance(value, Iterable) and len(value) > max_length:
            self._error(field, errors.MAX_LENGTH, len(value))

    _validate_meta = dummy_for_rule_validation('')

    def _validate_minlength(self, min_length, field, value):
        """ {'type': 'integer'} """
        if isinstance(value, Iterable) and len(value) < min_length:
            self._error(field, errors.MIN_LENGTH, len(value))

    def _validate_nullable(self, nullable, field, value):
        """ {'type': 'boolean'} """
        if value is None:
            if not nullable:
                self._error(field, errors.NOT_NULLABLE)
            self._drop_remaining_rules(
                'allowed',
                'empty',
                'forbidden',
                'items',
                'keysrules',
                'min',
                'max',
                'minlength',
                'maxlength',
                'regex',
                'schema',
                'type',
                'valuesrules',
            )

    def _validate_keysrules(self, schema, field, value):
        """ {'type': ['dict', 'string'], 'check_with': 'bulk_schema',
            'forbidden': ['rename', 'rename_handler']} """
        if isinstance(value, Mapping):
            validator = self._get_child_validator(
                document_crumb=field,
                schema_crumb=(field, 'keysrules'),
                schema=dict(((k, schema) for k in value.keys())),
            )
            if not validator(dict(((k, k) for k in value.keys())), normalize=False):
                self._drop_nodes_from_errorpaths(validator._errors, [], [2, 4])
                self._error(field, errors.KEYSRULES, validator._errors)

    def _validate_readonly(self, readonly, field, value):
        """ {'type': 'boolean'} """
        if readonly:
            if not self._is_normalized:
                self._error(field, errors.READONLY_FIELD)
            # If the document was normalized (and therefore already been
            # checked for readonly fields), we still have to return True
            # if an error was filed.
            has_error = (
                errors.READONLY_FIELD
                in self.document_error_tree.fetch_errors_from(
                    self.document_path + (field,)
                )
            )
            if self._is_normalized and has_error:
                self._drop_remaining_rules()

    def _validate_regex(self, pattern, field, value):
        """ {'type': 'string'} """
        if not isinstance(value, _str_type):
            return
        if not pattern.endswith('$'):
            pattern += '$'
        re_obj = re.compile(pattern)
        if not re_obj.match(value):
            self._error(field, errors.REGEX_MISMATCH)

    _validate_required = dummy_for_rule_validation(""" {'type': 'boolean'} """)

    _validate_require_all = dummy_for_rule_validation(""" {'type': 'boolean'} """)

    def __validate_required_fields(self, document):
        """ Validates that required fields are not missing.

        :param document: The document being validated.
        """
        try:
            required = set(
                field
                for field, definition in self.schema.items()
                if self._resolve_rules_set(definition).get('required', self.require_all)
                is True
            )
        except AttributeError:
            if self.is_child and self.schema_path[-1] == 'schema':
                raise _SchemaRuleTypeError
            else:
                raise
        required -= self._unrequired_by_excludes
        missing = required - set(
            field
            for field in document
            if document.get(field) is not None or not self.ignore_none_values
        )

        for field in missing:
            self._error(field, errors.REQUIRED_FIELD)

        # At least one field from self._unrequired_by_excludes should be present in
        # document.
        if self._unrequired_by_excludes:
            fields = set(field for field in document if document.get(field) is not None)
            if self._unrequired_by_excludes.isdisjoint(fields):
                for field in self._unrequired_by_excludes - fields:
                    self._error(field, errors.REQUIRED_FIELD)

    def _validate_schema(self, schema, field, value):
        """ {'type': ['dict', 'string'],
             'anyof': [{'check_with': 'schema'},
                       {'check_with': 'bulk_schema'}]} """
        if schema is None:
            return

        if isinstance(value, Sequence) and not isinstance(value, _str_type):
            self.__validate_schema_sequence(field, schema, value)
        elif isinstance(value, Mapping):
            self.__validate_schema_mapping(field, schema, value)

    def __validate_schema_mapping(self, field, schema, value):
        schema = self._resolve_schema(schema)
        allow_unknown = self.schema[field].get('allow_unknown', self.allow_unknown)
        require_all = self.schema[field].get('require_all', self.require_all)
        validator = self._get_child_validator(
            document_crumb=field,
            schema_crumb=(field, 'schema'),
            schema=schema,
            allow_unknown=allow_unknown,
            require_all=require_all,
        )
        try:
            if not validator(value, update=self.update, normalize=False):
                self._error(field, errors.MAPPING_SCHEMA, validator._errors)
        except _SchemaRuleTypeError:
            self._error(field, errors.BAD_TYPE_FOR_SCHEMA)
            raise

    def __validate_schema_sequence(self, field, schema, value):
        schema = dict(((i, schema) for i in range(len(value))))
        validator = self._get_child_validator(
            document_crumb=field,
            schema_crumb=(field, 'schema'),
            schema=schema,
            allow_unknown=self.allow_unknown,
        )
        validator(
            dict(((i, v) for i, v in enumerate(value))),
            update=self.update,
            normalize=False,
        )

        if validator._errors:
            self._drop_nodes_from_errorpaths(validator._errors, [], [2])
            self._error(field, errors.SEQUENCE_SCHEMA, validator._errors)

    def _validate_type(self, data_type, field, value):
        """ {'type': ['string', 'list'],
             'check_with': 'type'} """
        if not data_type:
            return

        types = (data_type,) if isinstance(data_type, _str_type) else data_type

        for _type in types:
            # TODO remove this block on next major release
            # this implementation still supports custom type validation methods
            type_definition = self.types_mapping.get(_type)
            if type_definition is not None:
                matched = isinstance(
                    value, type_definition.included_types
                ) and not isinstance(value, type_definition.excluded_types)
            else:
                type_handler = self.__get_rule_handler('validate_type', _type)
                matched = type_handler(value)
            if matched:
                return

            # TODO uncomment this block on next major release
            #      when _validate_type_* methods were deprecated:
            # type_definition = self.types_mapping[_type]
            # if isinstance(value, type_definition.included_types) \
            #         and not isinstance(value, type_definition.excluded_types):  # noqa 501
            #     return

        self._error(field, errors.BAD_TYPE)
        self._drop_remaining_rules()

    def _validate_valuesrules(self, schema, field, value):
        """ {'type': ['dict', 'string'], 'check_with': 'bulk_schema',
            'forbidden': ['rename', 'rename_handler']} """
        schema_crumb = (field, 'valuesrules')
        if isinstance(value, Mapping):
            validator = self._get_child_validator(
                document_crumb=field,
                schema_crumb=schema_crumb,
                schema=dict((k, schema) for k in value),
            )
            validator(value, update=self.update, normalize=False)
            if validator._errors:
                self._drop_nodes_from_errorpaths(validator._errors, [], [2])
                self._error(field, errors.VALUESRULES, validator._errors)


RULE_SCHEMA_SEPARATOR = "The rule's arguments are validated against this schema:"


class InspectedValidator(type):
    """ Metaclass for all validators """

    def __new__(cls, *args):
        if '__doc__' not in args[2]:
            args[2].update({'__doc__': args[1][0].__doc__})
        return super(InspectedValidator, cls).__new__(cls, *args)

    def __init__(cls, *args):
        def attributes_with_prefix(prefix):
            return tuple(
                x[len(prefix) + 2 :]
                for x in dir(cls)
                if x.startswith('_' + prefix + '_')
            )

        super(InspectedValidator, cls).__init__(*args)

        cls._types_from_methods, cls.validation_rules = (), {}
        for attribute in attributes_with_prefix('validate'):
            # TODO remove inspection of type test methods in next major release
            if attribute.startswith('type_'):
                cls._types_from_methods += (attribute[len('type_') :],)
            else:
                cls.validation_rules[attribute] = cls.__get_rule_schema(
                    '_validate_' + attribute
                )

        # TODO remove on next major release
        if cls._types_from_methods:
            warn(
                "Methods for type testing are deprecated, use TypeDefinition "
                "and the 'types_mapping'-property of a Validator-instance "
                "instead.",
                DeprecationWarning,
            )

        # TODO remove second summand on next major release
        cls.checkers = tuple(x for x in attributes_with_prefix('check_with')) + tuple(
            x for x in attributes_with_prefix('validator')
        )
        x = cls.validation_rules['check_with']['oneof']
        x[1]['schema']['oneof'][1]['allowed'] = x[2]['allowed'] = cls.checkers

        for rule in (x for x in cls.mandatory_validations if x != 'nullable'):
            cls.validation_rules[rule]['required'] = True

        cls.coercers, cls.default_setters, cls.normalization_rules = (), (), {}
        for attribute in attributes_with_prefix('normalize'):
            if attribute.startswith('coerce_'):
                cls.coercers += (attribute[len('coerce_') :],)
            elif attribute.startswith('default_setter_'):
                cls.default_setters += (attribute[len('default_setter_') :],)
            else:
                cls.normalization_rules[attribute] = cls.__get_rule_schema(
                    '_normalize_' + attribute
                )

        for rule in ('coerce', 'rename_handler'):
            x = cls.normalization_rules[rule]['oneof']
            x[1]['schema']['oneof'][1]['allowed'] = x[2]['allowed'] = cls.coercers
        cls.normalization_rules['default_setter']['oneof'][1][
            'allowed'
        ] = cls.default_setters

        cls.rules = {}
        cls.rules.update(cls.validation_rules)
        cls.rules.update(cls.normalization_rules)

    def __get_rule_schema(cls, method_name):
        docstring = getattr(cls, method_name).__doc__
        if docstring is None:
            result = {}
        else:
            if RULE_SCHEMA_SEPARATOR in docstring:
                docstring = docstring.split(RULE_SCHEMA_SEPARATOR)[1]
            try:
                result = literal_eval(docstring.strip())
            except Exception:
                result = {}

        if not result and method_name != '_validate_meta':
            warn(
                "No validation schema is defined for the arguments of rule "
                "'%s'" % method_name.split('_', 2)[-1]
            )

        return result


Validator = InspectedValidator('Validator', (BareValidator,), {})
