"""pyproject.toml related pip exceptions."""

from pipenv.patched.pip._vendor.rich.markup import escape
from pipenv.patched.pip._vendor.rich.text import Text

from pipenv.patched.pip._internal.exceptions._base import DiagnosticPipError


class MissingPyProjectBuildRequires(DiagnosticPipError):
    """Raised when pyproject.toml has `build-system`, but no `build-system.requires`."""

    reference = "missing-pyproject-build-system-requires"

    def __init__(self, *, package: str) -> None:
        super().__init__(
            message=f"Can not process {escape(package)}",
            context=Text(
                "This package has an invalid pyproject.toml file.\n"
                "The [build-system] table is missing the mandatory `requires` key."
            ),
            note_stmt="This is an issue with the package mentioned above, not pip.",
            hint_stmt=Text("See PEP 518 for the detailed specification."),
        )


class InvalidPyProjectBuildRequires(DiagnosticPipError):
    """Raised when pyproject.toml an invalid `build-system.requires`."""

    reference = "invalid-pyproject-build-system-requires"

    def __init__(self, *, package: str, reason: str) -> None:
        super().__init__(
            message=f"Can not process {escape(package)}",
            context=Text(
                "This package has an invalid `build-system.requires` key in "
                f"pyproject.toml.\n{reason}"
            ),
            note_stmt="This is an issue with the package mentioned above, not pip.",
            hint_stmt=Text("See PEP 518 for the detailed specification."),
        )
