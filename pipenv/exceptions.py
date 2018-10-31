# -*- coding=utf-8 -*-
from ._compat import fix_utf8
from .patched import crayons
from .vendor.click import echo as click_echo
from .vendor.click.exceptions import (
    Abort,
    BadOptionUsage,
    BadParameter,
    ClickException,
    Exit,
    FileError,
    MissingParameter,
    UsageError,
)


class PipenvException(ClickException):
    def __init__(self, message, *args, **kwargs):
        super(PipenvException, self).__init__(message, *args, **kwargs)


class PipfileNotFound(ClickException):
    message = "{0}: Pipfile is missing! Cannot proceed.".format(
        crayons.red("Error", bold=True)
    )


class LockfileNotFound(ClickException):
    message = "{0}: Pipfile.lock is missing! You need to run {1} first.".format(
        crayons.red("Error", bold=True), crayons.red("$ pipenv lock", bold=True)
    )


class DeployException(ClickException):
    message = crayons.normal("Aborting deploy", bold=True)


class PipenvOptionsError(BadOptionUsage):
    def format_message(self):
        return "{0}: {1}".format(crayons.red("Warning", bold=True), self.message)


class PipfileException(FileError):
    def __init__(self, hint=None):
        from .core import project

        hint = "{0} {1}".format(crayons.red("ERROR (PACKAGE NOT INSTALLED):"), hint)
        filename = project.pipfile_location
        super(PipfileException, self).__init__(filename, hint)


class SetupException(ClickException):
    pass


class VirtualenvException(ClickException):
    def __init__(self, message=None):
        if not message:
            message = (
                "There was an unexpected error while activating your virtualenv. "
                "Continuing anyway..."
            )
        message = fix_utf8(
            "{0}: {1}".format(crayons.red("Warning", bold=True), message)
        )
        super(VirtualenvException, self).__init__(message)


class VirtualenvActivationException(VirtualenvException):
    message = (
        "activate_this.py not found. Your environment is most certainly "
        "not activated. Continuing anyway…"
    )


class VirtualenvCreationException(VirtualenvException):
    message = "Failed to create virtual environment."
