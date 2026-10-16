"""
build - A simple, correct Python build frontend
"""

from __future__ import annotations


__lazy_modules__ = {
    f'{__spec__.parent}._builder',
    f'{__spec__.parent}._exceptions',
    f'{__spec__.parent}._types',
    f'{__spec__.parent}._util',
}

from ._builder import ProjectBuilder
from ._exceptions import (
    BuildBackendException,
    BuildException,
    BuildSystemTableValidationError,
    FailedProcessError,
    TypoWarning,
)
from ._types import ConfigSettings as ConfigSettingsType
from ._types import Distribution as DistributionType
from ._types import SubprocessRunner as RunnerType
from ._util import check_dependency


__version__ = '1.6.1'

__all__ = [
    'BuildBackendException',
    'BuildException',
    'BuildSystemTableValidationError',
    'ConfigSettingsType',
    'DistributionType',
    'FailedProcessError',
    'ProjectBuilder',
    'RunnerType',
    'TypoWarning',
    '__version__',
    'check_dependency',
]


def __dir__() -> list[str]:
    return __all__
