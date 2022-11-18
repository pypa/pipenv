"""
    Extensible validation for Python dictionaries.

    :copyright: 2012-2021 by Nicola Iarocci.
    :license: ISC, see LICENSE for more details.

    Full documentation is available at https://python-cerberus.org/

"""

from __future__ import absolute_import

from pipenv.patched.pip._vendor.pkg_resources import get_distribution, DistributionNotFound

from pipenv.vendor.cerberus.validator import DocumentError, Validator
from pipenv.vendor.cerberus.schema import rules_set_registry, schema_registry, SchemaError
from pipenv.vendor.cerberus.utils import TypeDefinition


try:
    __version__ = get_distribution("Cerberus").version
except DistributionNotFound:
    __version__ = "unknown"

__all__ = [
    DocumentError.__name__,
    SchemaError.__name__,
    TypeDefinition.__name__,
    Validator.__name__,
    "schema_registry",
    "rules_set_registry",
]
