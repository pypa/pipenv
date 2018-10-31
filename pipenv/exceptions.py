# -*- coding=utf-8 -*-

import six

from ._compat import fix_utf8
from .patched import crayons
from .vendor.click import echo as click_echo
from .vendor.click._compat import get_text_stderr
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
    message = "{0}: {{1}}".format(crayons.red("Error", bold=True))

    def __init__(self, *args, message=None, **kwargs):
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        extra = kwargs.pop("extra", [])
        message = self.message.format(message)
        ClickException.__init__(self, message)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(extra, file=file)
        super(PipenvException, self).show(file=file)


class PipenvUsageError(UsageError):
    message = "{0}: {{1}}".format(crayons.red("Error", bold=True))

    def __init__(self, *args, message=None, ctx=None, **kwargs):
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        self.message = self.message.format(message)
        extra = kwargs.pop("extra", [])
        UsageError.__init__(self, message, ctx)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(extra, file=file)
        super(PipenvUsageError, self).show(file=file)


class PipenvFileError(FileError):
    def __init__(self, filename, message=None, **kwargs):
        extra = kwargs.pop("extra", [])
        FileError.__init__(self, filename, hint=message, **kwargs)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(extra, file=file)
        super(PipenvException, self).show(file=file)


class PipfileNotFound(PipenvFileError):
    def __init__(self, extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = ("Cannot proceed. Please ensure that a Pipfile exists and is located "
        "in your project root directory.")
        filename = "Pipfile"
        PipenvFileError.__init__(filename, message=message, extra=extra, **kwargs)


class LockfileNotFound(PipenvFileError):
    def __init__(self, extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = "You need to run {0} before you can continue.".format(
            crayons.red("$ pipenv lock", bold=True)
        )
        filename = "Pipfile.lock"
        PipenvFileError.__init__(self, filename, message=message, extra=extra, **kwargs)


class DeployException(PipenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = crayons.normal("Aborting deploy", bold=True)
        extra = kwargs.pop("extra", None)
        PipenvException.__init__(self, message=message, extra=extra, **kwargs)


class PipenvOptionsError(BadOptionUsage):
    def __init__(self, message=None, *args, **kwargs):
        extra = kwargs.pop("extra", [])
        BadOptionUsage.__init__(self, message, *args, **kwargs)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(extra, file=file)
        click_echo("{0}: {1}".format(crayons.red("Warning", bold=True), self.message))


class PipfileException(PipenvFileError):
    def __init__(self, hint=None, **kwargs):
        from .core import project

        hint = "{0} {1}".format(crayons.red("ERROR (PACKAGE NOT INSTALLED):"), hint)
        filename = project.pipfile_location
        extra = kwargs.pop("extra", [])
        PipfileException.__init__(self, filename, hint, extra=extra, **kwargs)


class SetupException(PipenvException):
    def __init__(self, message=None, *args, **kwargs):
        PipenvException.__init__(message, *args, **kwargs)


class VirtualenvException(PipenvException):

    def __init__(self, message=None, **kwargs):
        if not message:
            message = (
                "There was an unexpected error while activating your virtualenv. "
                "Continuing anyway..."
            )
        PipenvException.__init__(self, message, **kwargs)

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(extra, file=file)
        click_echo(fix_utf8(
            "{0}: {1}".format(crayons.red("Warning", bold=True), self.message)
        ))


class VirtualenvActivationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = (
                "activate_this.py not found. Your environment is most certainly "
                "not activated. Continuing anyway…"
            )
        self.message = message
        VirtualenvException.__init__(self, message, **kwargs)


class VirtualenvCreationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = "Failed to create virtual environment."
        self.message = message
        VirtualenvException.__init__(self, message, **kwargs)
