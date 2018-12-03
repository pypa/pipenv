# -*- coding=utf-8 -*-

import itertools
import sys

from pprint import pformat
from traceback import format_exception, format_tb

import six

from . import environments
from ._compat import decode_for_output
from .patched import crayons
from .vendor.click._compat import get_text_stderr
from .vendor.click.exceptions import (
    Abort, BadOptionUsage, BadParameter, ClickException, Exit, FileError,
    MissingParameter, UsageError
)
from .vendor.click.types import Path
from .vendor.click.utils import echo as click_echo


def handle_exception(exc_type, exception, traceback, hook=sys.excepthook):
    if environments.is_verbose() or not issubclass(exc_type, ClickException):
        hook(exc_type, exception, traceback)
    else:
        exc = format_exception(exc_type, exception, traceback)
        tb = format_tb(traceback, limit=-6)
        lines = itertools.chain.from_iterable([frame.splitlines() for frame in tb])
        for line in lines:
            line = line.strip("'").strip('"').strip("\n").strip()
            if not line.startswith("File"):
                line = "      {0}".format(line)
            else:
                line = "  {0}".format(line)
            line = "[{0!s}]: {1}".format(
                exception.__class__.__name__, line
            )
            click_echo(decode_for_output(line), err=True)
        exception.show()


sys.excepthook = handle_exception


class PipenvException(ClickException):
    message = "{0}: {{0}}".format(crayons.red("ERROR", bold=True))

    def __init__(self, message=None, **kwargs):
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
                extra = "[pipenv.exceptions.{0!s}]: {1}".format(
                    self.__class__.__name__, extra
                )
                extra = decode_for_output(extra, file)
                click_echo(extra, file=file)
        click_echo(decode_for_output("{0}".format(self.message), file), file=file)


class PipenvCmdError(PipenvException):
    def __init__(self, cmd, out="", err="", exit_code=1):
        self.cmd = cmd
        self.out = out
        self.err = err
        self.exit_code = exit_code
        message = "Error running command: {0}".format(cmd)
        PipenvException.__init__(self, message)

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        click_echo("{0} {1}".format(
            crayons.red("Error running command: "),
            crayons.white(decode_for_output("$ {0}".format(self.cmd), file), bold=True)
        ), err=True)
        if self.out:
            click_echo("{0} {1}".format(
                crayons.white("OUTPUT: "),
                decode_for_output(self.out, file)
            ), err=True)
        if self.err:
            click_echo("{0} {1}".format(
                crayons.white("STDERR: "),
                decode_for_output(self.err, file)
            ), err=True)


class JSONParseError(PipenvException):
    def __init__(self, contents="", error_text=""):
        self.error_text = error_text
        PipenvException.__init__(self, contents)

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        message = "{0}\n{1}".format(
            crayons.white("Failed parsing JSON results:", bold=True),
            decode_for_output(self.message.strip(), file)
        )
        click_echo(self.message, err=True)
        if self.error_text:
            click_echo("{0} {1}".format(
                crayons.white("ERROR TEXT:", bold=True),
                decode_for_output(self.error_text, file)
            ), err=True)


class PipenvUsageError(UsageError):

    def __init__(self, message=None, ctx=None, **kwargs):
        formatted_message = "{0}: {1}"
        msg_prefix = crayons.red("ERROR:", bold=True)
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        message = formatted_message.format(msg_prefix, crayons.white(message, bold=True))
        self.message = message
        extra = kwargs.pop("extra", [])
        UsageError.__init__(self, decode_for_output(message), ctx)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        color = None
        if self.ctx is not None:
            color = self.ctx.color
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                if color:
                    extra = getattr(crayons, color, "blue")(extra)
                click_echo(decode_for_output(extra, file), file=file)
        hint = ''
        if (self.cmd is not None and
                self.cmd.get_help_option(self.ctx) is not None):
            hint = ('Try "%s %s" for help.\n'
                    % (self.ctx.command_path, self.ctx.help_option_names[0]))
        if self.ctx is not None:
            click_echo(self.ctx.get_usage() + '\n%s' % hint, file=file, color=color)
        click_echo(self.message, file=file)


class PipenvFileError(FileError):
    formatted_message = "{0} {{0}} {{1}}".format(
        crayons.red("ERROR:", bold=True)
    )

    def __init__(self, filename, message=None, **kwargs):
        extra = kwargs.pop("extra", [])
        if not message:
            message = crayons.white("Please ensure that the file exists!", bold=True)
        message = self.formatted_message.format(
            crayons.white("{0} not found!".format(filename), bold=True),
            message
        )
        FileError.__init__(self, filename=filename, hint=decode_for_output(message), **kwargs)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = get_text_stderr()
        if self.extra:
            if isinstance(self.extra, six.string_types):
                self.extra = [self.extra,]
            for extra in self.extra:
                click_echo(decode_for_output(extra, file), file=file)
        click_echo(self.message, file=file)


class PipfileNotFound(PipenvFileError):
    def __init__(self, filename="Pipfile", extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = ("{0} {1}".format(
                crayons.red("Aborting!", bold=True),
                crayons.white("Please ensure that the file exists and is located in your"
                              " project root directory.", bold=True)
            )
        )
        super(PipfileNotFound, self).__init__(filename, message=decode_for_output(message), extra=extra, **kwargs)


class LockfileNotFound(PipenvFileError):
    def __init__(self, filename="Pipfile.lock", extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = "{0} {1} {2}".format(
            crayons.white("You need to run", bold=True),
            crayons.red("$ pipenv lock", bold=True),
            crayons.white("before you can continue.", bold=True)
        )
        super(LockfileNotFound, self).__init__(filename, message=decode_for_output(message), extra=extra, **kwargs)


class DeployException(PipenvUsageError):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = crayons.normal("Aborting deploy", bold=True)
        extra = kwargs.pop("extra", [])
        PipenvUsageError.__init__(self, message=decode_for_output(message), extra=extra, **kwargs)


class PipenvOptionsError(PipenvUsageError):
    def __init__(self, option_name, message=None, ctx=None, **kwargs):
        extra = kwargs.pop("extra", [])
        PipenvUsageError.__init__(self, message=decode_for_output(message), ctx=ctx, **kwargs)
        self.extra = extra
        self.option_name = option_name


class SystemUsageError(PipenvOptionsError):
    def __init__(self, option_name="system", message=None, ctx=None, **kwargs):
        extra = kwargs.pop("extra", [])
        extra += [
            "{0}: --system is intended to be used for Pipfile installation, "
            "not installation of specific packages. Aborting.".format(
                crayons.red("Warning", bold=True)
            ),
        ]
        if message is None:
            message = crayons.blue("See also: {0}".format(crayons.white("--deploy flag.")))
        super(SystemUsageError, self).__init__(option_name, message=message, ctx=ctx, extra=extra, **kwargs)


class PipfileException(PipenvFileError):
    def __init__(self, hint=None, **kwargs):
        from .core import project

        if not hint:
            hint = "{0} {1}".format(crayons.red("ERROR (PACKAGE NOT INSTALLED):"), hint)
        filename = project.pipfile_location
        extra = kwargs.pop("extra", [])
        PipenvFileError.__init__(self, filename, decode_for_output(hint), extra=extra, **kwargs)


class SetupException(PipenvException):
    def __init__(self, message=None, **kwargs):
        PipenvException.__init__(self, message, **kwargs)


class VirtualenvException(PipenvException):

    def __init__(self, message=None, **kwargs):
        if not message:
            message = (
                "There was an unexpected error while activating your virtualenv. "
                "Continuing anyway..."
            )
        PipenvException.__init__(self, decode_for_output(message), **kwargs)


class VirtualenvActivationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = (
                "activate_this.py not found. Your environment is most certainly "
                "not activated. Continuing anyway…"
            )
        self.message = message
        VirtualenvException.__init__(self, decode_for_output(message), **kwargs)


class VirtualenvCreationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = "Failed to create virtual environment."
        self.message = message
        VirtualenvException.__init__(self, decode_for_output(message), **kwargs)


class UninstallError(PipenvException):
    def __init__(self, package, command, return_values, return_code, **kwargs):
        extra = [crayons.blue("Attempted to run command: {0}".format(
            crayons.yellow("$ {0}".format(command), bold=True)
        )),]
        extra.extend([crayons.blue(line.strip()) for line in return_values.splitlines()])
        if isinstance(package, (tuple, list, set)):
            package = " ".join(package)
        message = "{0!s} {1!s}...".format(
            crayons.normal("Failed to uninstall package(s)"),
            crayons.yellow(str(package), bold=True)
        )
        self.exit_code = return_code
        PipenvException.__init__(self, message=decode_for_output(message), extra=extra)
        self.extra = extra


class InstallError(PipenvException):
    def __init__(self, package, **kwargs):
        package_message = ""
        if package is not None:
            package_message = crayons.normal("Couldn't install package {0}\n".format(
                crayons.white(package, bold=True)
            ))
        message = "{0} {1} {2}".format(
            crayons.red("ERROR:", bold=True),
            package_message,
            crayons.yellow("Package installation failed...")
        )
        extra = kwargs.pop("extra", [])
        PipenvException.__init__(self, message=decode_for_output(message), extra=extra, **kwargs)


class CacheError(PipenvException):
    def __init__(self, path, **kwargs):
        message = "{0} {1} {2}\n{0}".format(
            crayons.red("ERROR:", bold=True),
            crayons.blue("Corrupt cache file"),
            crayons.white(path),
            crayons.white('Consider trying "pipenv lock --clear" to clear the cache.')
        )
        PipenvException.__init__(self, message=decode_for_output(message))


class ResolutionFailure(PipenvException):
    def __init__(self, message, no_version_found=False):
        extra = (
            "{0}: Your dependencies could not be resolved. You likely have a "
            "mismatch in your sub-dependencies.\n  "
            "First try clearing your dependency cache with {1}, then try the original command again.\n "
            "Alternatively, you can use {2} to bypass this mechanism, then run "
            "{3} to inspect the situation.\n  "
            "Hint: try {4} if it is a pre-release dependency."
            "".format(
                crayons.red("Warning", bold=True),
                crayons.red("$ pipenv lock --clear"),
                crayons.red("$ pipenv install --skip-lock"),
                crayons.red("$ pipenv graph"),
                crayons.red("$ pipenv lock --pre"),
            ),
        )
        if "no version found at all" in message:
            no_version_found = True
        message = "{0} {1}".format(
            crayons.red("ERROR:", bold=True), crayons.yellow(message)
        )
        if no_version_found:
            message = "{0}\n{1}".format(
                message,
                crayons.blue(
                    "Please check your version specifier and version number. "
                    "See PEP440 for more information."
                )
            )
        super(ResolutionFailure, self).__init__(decode_for_output(message), extra=extra)
