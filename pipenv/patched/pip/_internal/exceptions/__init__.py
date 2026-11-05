"""Package of exceptions used in the pip codebase.

This package used to be a single module, so many exceptions were
grandfathered into this module. In the future, more groups of exceptions
should be moved to their own submodules as needed.

This package MUST NOT try to import from anything within `pipenv.patched.pip._internal` to
operate. This is expected to be importable from any/all files within the
subpackage and, thus, should not depend on them.
"""

# NOTE: the pipenv.patched.pip._internal import restriction may change later if there is an
# exception group that does really need internal code to function (e.g.
# possibly network). In that case, said group should NOT be re-exported here.

from __future__ import annotations

import configparser
import contextlib
import locale
import logging
import pathlib
import sys
from collections.abc import Iterator
from typing import TYPE_CHECKING

from pipenv.patched.pip._vendor.packaging.requirements import InvalidRequirement
from pipenv.patched.pip._vendor.packaging.version import InvalidVersion
from pipenv.patched.pip._vendor.rich.markup import escape
from pipenv.patched.pip._vendor.rich.text import Text

from pipenv.patched.pip._internal.exceptions._base import (
    BlockedImportError,
    DiagnosticPipError,
    InstallationError,
    PipError,
)
from pipenv.patched.pip._internal.exceptions.build import (
    BackendUnavailableError,
    BuildDependencyInstallError,
    InstallationSubprocessError,
    VenvCreationError,
    VenvImportError,
)
from pipenv.patched.pip._internal.exceptions.hashes import (
    DirectoryUrlHashUnsupported,
    HashError,
    HashErrors,
    HashMismatch,
    HashMissing,
    HashUnpinned,
    VcsHashUnsupported,
)
from pipenv.patched.pip._internal.exceptions.network import (
    ConnectionFailedError,
    ConnectionTimeoutError,
    IncompleteDownloadError,
    NetworkConnectionError,
    ProxyConnectionError,
    SSLMissingError,
    SSLVerificationError,
)
from pipenv.patched.pip._internal.exceptions.pyproject import (
    InvalidPyProjectBuildRequires,
    MissingPyProjectBuildRequires,
)
from pipenv.patched.pip._internal.exceptions.uninstall import (
    LegacyDistutilsInstall,
    UninstallMissingRecord,
)
from pipenv.patched.pip._internal.exceptions.wheel import (
    InvalidWheel,
    InvalidWheelFilename,
    UnsupportedWheel,
)

if TYPE_CHECKING:
    from pipenv.patched.pip._internal.metadata import BaseDistribution
    from pipenv.patched.pip._internal.models.link import Link
    from pipenv.patched.pip._internal.req.req_install import InstallRequirement


__all__ = [
    # base
    "BlockedImportError",
    "DiagnosticPipError",
    "InstallationError",
    "PipError",
    # build
    "BackendUnavailableError",
    "BuildDependencyInstallError",
    "InstallationSubprocessError",
    "VenvCreationError",
    "VenvImportError",
    # hashes
    "DirectoryUrlHashUnsupported",
    "HashError",
    "HashErrors",
    "HashMismatch",
    "HashMissing",
    "HashUnpinned",
    "VcsHashUnsupported",
    # network
    "ConnectionFailedError",
    "ConnectionTimeoutError",
    "IncompleteDownloadError",
    "NetworkConnectionError",
    "ProxyConnectionError",
    "SSLMissingError",
    "SSLVerificationError",
    # pyproject
    "InvalidPyProjectBuildRequires",
    "MissingPyProjectBuildRequires",
    # uninstall
    "LegacyDistutilsInstall",
    "UninstallMissingRecord",
    # wheel
    "InvalidWheel",
    "InvalidWheelFilename",
    "UnsupportedWheel",
]

logger = logging.getLogger(__name__)


class ConfigurationError(PipError):
    """General exception in configuration"""


class FailedToPrepareCandidate(InstallationError):
    """Raised when we fail to prepare a candidate (i.e. fetch and generate metadata).

    This is intentionally not a diagnostic error, since the output will be presented
    above this error, when this occurs. This should instead present information to the
    user.
    """

    def __init__(
        self, *, package_name: str, requirement_chain: str, failed_step: str
    ) -> None:
        super().__init__(f"Failed to build '{package_name}' when {failed_step.lower()}")
        self.package_name = package_name
        self.requirement_chain = requirement_chain
        self.failed_step = failed_step


class NoneMetadataError(PipError):
    """Raised when accessing a Distribution's "METADATA" or "PKG-INFO".

    This signifies an inconsistency, when the Distribution claims to have
    the metadata file (if not, raise ``FileNotFoundError`` instead), but is
    not actually able to produce its content. This may be due to permission
    errors.
    """

    def __init__(
        self,
        dist: BaseDistribution,
        metadata_name: str,
    ) -> None:
        """
        :param dist: A Distribution object.
        :param metadata_name: The name of the metadata being accessed
            (can be "METADATA" or "PKG-INFO").
        """
        self.dist = dist
        self.metadata_name = metadata_name

    def __str__(self) -> str:
        # Use `dist` in the error message because its stringification
        # includes more information, like the version and location.
        return f"None {self.metadata_name} metadata found for distribution: {self.dist}"


class UserInstallationInvalid(InstallationError):
    """A --user install is requested on an environment without user site."""

    def __str__(self) -> str:
        return "User base directory is not specified"


class InvalidSchemeCombination(InstallationError):
    def __str__(self) -> str:
        before = ", ".join(str(a) for a in self.args[:-1])
        return f"Cannot set {before} and {self.args[-1]} together"


class DistributionNotFound(InstallationError):
    """Raised when a distribution cannot be found to satisfy a requirement"""


class RequirementsFileParseError(InstallationError):
    """Raised when a general error occurs parsing a requirements file line."""


class BestVersionAlreadyInstalled(PipError):
    """Raised when the most up-to-date version of a package is already
    installed."""


class BadCommand(PipError):
    """Raised when virtualenv or a command is not found"""


class CommandError(PipError):
    """Raised when there is an error in command-line arguments"""


class PreviousBuildDirError(PipError):
    """Raised when there's a previous conflicting build directory"""


class MetadataInconsistent(InstallationError):
    """Built metadata contains inconsistent information.

    This is raised when the metadata contains values (e.g. name and version)
    that do not match the information previously obtained from sdist filename,
    user-supplied ``#egg=`` value, or an install requirement name.
    """

    def __init__(
        self, ireq: InstallRequirement, field: str, f_val: str, m_val: str
    ) -> None:
        self.ireq = ireq
        self.field = field
        self.f_val = f_val
        self.m_val = m_val

    def __str__(self) -> str:
        return (
            f"Requested {self.ireq} has inconsistent {self.field}: "
            f"expected {self.f_val!r}, but metadata has {self.m_val!r}"
        )


class SidecarMetadataInconsistent(MetadataInconsistent):
    """The wheel's METADATA disagrees with its PEP 658 ``.metadata`` file.

    Raised after the wheel has been downloaded and hash-verified, when a
    resolver-affecting field in the wheel's embedded ``METADATA`` does not
    match the value taken from the remote ``.metadata`` sidecar that drove
    resolution. ``f_val`` is the sidecar value, ``m_val`` is the wheel value.
    """

    def __str__(self) -> str:
        return (
            f"Requested {self.ireq} has inconsistent {self.field} between "
            f"its PEP 658 .metadata file and the wheel's METADATA: "
            f"sidecar has {self.f_val!r}, wheel has {self.m_val!r}"
        )


class MetadataInvalid(InstallationError):
    """Metadata is invalid."""

    def __init__(self, ireq: InstallRequirement, error: str) -> None:
        self.ireq = ireq
        self.error = error

    def __str__(self) -> str:
        return f"Requested {self.ireq} has invalid metadata: {self.error}"


class MetadataGenerationFailed(DiagnosticPipError, InstallationError):
    reference = "metadata-generation-failed"

    def __init__(
        self,
        *,
        package_details: str,
    ) -> None:
        super().__init__(
            message="Encountered error while generating package metadata.",
            context=escape(package_details),
            hint_stmt="See above for details.",
            note_stmt="This is an issue with the package mentioned above, not pip.",
        )

    def __str__(self) -> str:
        return "metadata generation failed"


class UnsupportedPythonVersion(InstallationError):
    """Unsupported python version according to Requires-Python package
    metadata."""


class ConfigurationFileCouldNotBeLoaded(ConfigurationError):
    """When there are errors while loading a configuration file"""

    def __init__(
        self,
        reason: str = "could not be loaded",
        fname: str | None = None,
        error: configparser.Error | None = None,
    ) -> None:
        super().__init__(error)
        self.reason = reason
        self.fname = fname
        self.error = error

    def __str__(self) -> str:
        if self.fname is not None:
            message_part = f" in {self.fname}."
        else:
            assert self.error is not None
            message_part = f".\n{self.error}\n"
        return f"Configuration file {self.reason}{message_part}"


_DEFAULT_EXTERNALLY_MANAGED_ERROR = f"""\
The Python environment under {sys.prefix} is managed externally, and may not be
manipulated by the user. Please use specific tooling from the distributor of
the Python installation to interact with this environment instead.
"""


class ExternallyManagedEnvironment(DiagnosticPipError):
    """The current environment is externally managed.

    This is raised when the current environment is externally managed, as
    defined by `PEP 668`_. The ``EXTERNALLY-MANAGED`` configuration is checked
    and displayed when the error is bubbled up to the user.

    :param error: The error message read from ``EXTERNALLY-MANAGED``.
    """

    reference = "externally-managed-environment"

    def __init__(self, error: str | None) -> None:
        if error is None:
            context = Text(_DEFAULT_EXTERNALLY_MANAGED_ERROR)
        else:
            context = Text(error)
        super().__init__(
            message="This environment is externally managed",
            context=context,
            note_stmt=(
                "If you believe this is a mistake, please contact your "
                "Python installation or OS distribution provider. "
                "You can override this, at the risk of breaking your Python "
                "installation or OS, by passing --break-system-packages."
            ),
            hint_stmt=Text("See PEP 668 for the detailed specification."),
        )

    @staticmethod
    def _iter_externally_managed_error_keys() -> Iterator[str]:
        # LC_MESSAGES is in POSIX, but not the C standard. The most common
        # platform that does not implement this category is Windows, where
        # using other categories for console message localization is equally
        # unreliable, so we fall back to the locale-less vendor message. This
        # can always be re-evaluated when a vendor proposes a new alternative.
        try:
            category = locale.LC_MESSAGES
        except AttributeError:
            lang: str | None = None
        else:
            lang, _ = locale.getlocale(category)
        if lang is not None:
            yield f"Error-{lang}"
            for sep in ("-", "_"):
                before, found, _ = lang.partition(sep)
                if not found:
                    continue
                yield f"Error-{before}"
        yield "Error"

    @classmethod
    def from_config(
        cls,
        config: pathlib.Path | str,
    ) -> ExternallyManagedEnvironment:
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read(config, encoding="utf-8")
            section = parser["externally-managed"]
            for key in cls._iter_externally_managed_error_keys():
                with contextlib.suppress(KeyError):
                    return cls(section[key])
        except KeyError:
            pass
        except (OSError, UnicodeDecodeError, configparser.ParsingError):
            from pipenv.patched.pip._internal.utils._log import VERBOSE

            exc_info = logger.isEnabledFor(VERBOSE)
            logger.warning("Failed to read %s", config, exc_info=exc_info)
        return cls(None)


class InvalidInstalledPackage(DiagnosticPipError):
    reference = "invalid-installed-package"

    def __init__(
        self,
        *,
        dist: BaseDistribution,
        invalid_exc: InvalidRequirement | InvalidVersion,
    ) -> None:
        installed_location = dist.installed_location

        if isinstance(invalid_exc, InvalidRequirement):
            invalid_type = "requirement"
        else:
            invalid_type = "version"

        super().__init__(
            message=Text(
                f"Cannot process installed package {dist} "
                + (f"in {installed_location!r} " if installed_location else "")
                + f"because it has an invalid {invalid_type}:\n{invalid_exc.args[0]}"
            ),
            context=(
                "Starting with pip 24.1, packages with invalid "
                f"{invalid_type}s can not be processed."
            ),
            hint_stmt="To proceed this package must be uninstalled.",
        )


class ResolutionTooDeepError(DiagnosticPipError):
    """Raised when the dependency resolver exceeds the maximum recursion depth."""

    reference = "resolution-too-deep"

    def __init__(self) -> None:
        super().__init__(
            message="Dependency resolution exceeded maximum depth",
            context=(
                "Pip cannot resolve the current dependencies as the dependency graph "
                "is too complex for pip to solve efficiently."
            ),
            hint_stmt=(
                "Try adding lower bounds to constrain your dependencies, "
                "for example: 'package>=2.0.0' instead of just 'package'. "
            ),
            link="https://pip.pypa.io/en/stable/topics/dependency-resolution/#handling-resolution-too-deep-errors",
        )


class InstallWheelBuildError(DiagnosticPipError):
    reference = "failed-wheel-build-for-install"

    def __init__(self, failed: list[InstallRequirement]) -> None:
        super().__init__(
            message=(
                "Failed to build installable wheels for some "
                "pyproject.toml based projects"
            ),
            context=", ".join(r.name for r in failed),  # type: ignore
            hint_stmt=None,
        )


class InvalidEggFragment(DiagnosticPipError):
    reference = "invalid-egg-fragment"

    def __init__(self, link: Link, fragment: str) -> None:
        hint = ""
        if ">" in fragment or "=" in fragment or "<" in fragment:
            hint = (
                "Version specifiers are silently ignored for URL references. "
                "Remove them. "
            )
        if "[" in fragment and "]" in fragment:
            hint += "Try using the Direct URL requirement syntax: 'name[extra] @ URL'"

        if not hint:
            hint = "Egg fragments can only be a valid project name."

        super().__init__(
            message=f"The '{escape(fragment)}' egg fragment is invalid",
            context=f"from '{escape(str(link))}'",
            hint_stmt=escape(hint),
        )
