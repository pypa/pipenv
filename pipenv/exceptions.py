import itertools
import re
import sys
from collections import namedtuple
from traceback import format_tb

from pipenv import environments
from pipenv._compat import decode_for_output
from pipenv.patched import crayons
from pipenv.vendor import vistir
from pipenv.vendor.click.exceptions import ClickException, FileError, UsageError
from pipenv.vendor.vistir.misc import echo as click_echo

ANSI_REMOVAL_RE = re.compile(r"\033\[((?:\d|;)*)([a-zA-Z])", re.MULTILINE)
STRING_TYPES = ((str,), crayons.ColoredString)

if sys.version_info[:2] >= (3, 7):
    KnownException = namedtuple(
        "KnownException",
        ["exception_name", "match_string", "show_from_string", "prefix"],
        defaults=[None, None, None, ""],
    )
else:
    KnownException = namedtuple(
        "KnownException",
        ["exception_name", "match_string", "show_from_string", "prefix"],
    )
    KnownException.__new__.__defaults__ = (None, None, None, "")

KNOWN_EXCEPTIONS = [
    KnownException("PermissionError", prefix="Permission Denied:"),
    KnownException(
        "VirtualenvCreationException",
        match_string="do_create_virtualenv",
        show_from_string=None,
    ),
]


def handle_exception(exc_type, exception, traceback, hook=sys.excepthook):
    if environments.Setting().is_verbose() or not issubclass(exc_type, ClickException):
        hook(exc_type, exception, traceback)
    else:
        tb = format_tb(traceback, limit=-6)
        lines = itertools.chain.from_iterable([frame.splitlines() for frame in tb])
        formatted_lines = []
        for line in lines:
            line = line.strip("'").strip('"').strip("\n").strip()
            if not line.startswith("File"):
                line = f"      {line}"
            else:
                line = f"  {line}"
            line = "[{!s}]: {}".format(exception.__class__.__name__, line)
            formatted_lines.append(line)
        # use new exception prettification rules to format exceptions according to
        # UX rules
        click_echo(decode_for_output(prettify_exc("\n".join(formatted_lines))), err=True)
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
            file = vistir.misc.get_text_stderr()
        if self.extra:
            if isinstance(self.extra, STRING_TYPES):
                self.extra = [self.extra]
            for extra in self.extra:
                extra = "[pipenv.exceptions.{!s}]: {}".format(
                    self.__class__.__name__, extra
                )
                extra = decode_for_output(extra, file)
                click_echo(extra, file=file)
        click_echo(decode_for_output(f"{self.message}", file), file=file)


class PipenvCmdError(PipenvException):
    def __init__(self, cmd, out="", err="", exit_code=1):
        self.cmd = cmd
        self.out = out
        self.err = err
        self.exit_code = exit_code
        message = f"Error running command: {cmd}"
        PipenvException.__init__(self, message)

    def show(self, file=None):
        if file is None:
            file = vistir.misc.get_text_stderr()
        click_echo(
            "{} {}".format(
                crayons.red("Error running command: "),
                crayons.normal(decode_for_output(f"$ {self.cmd}", file), bold=True),
            ),
            err=True,
        )
        if self.out:
            click_echo(
                "{} {}".format(
                    crayons.normal("OUTPUT: "), decode_for_output(self.out, file)
                ),
                err=True,
            )
        if self.err:
            click_echo(
                "{} {}".format(
                    crayons.normal("STDERR: "), decode_for_output(self.err, file)
                ),
                err=True,
            )


class JSONParseError(PipenvException):
    def __init__(self, contents="", error_text=""):
        self.error_text = error_text
        PipenvException.__init__(self, contents)

    def show(self, file=None):
        if file is None:
            file = vistir.misc.get_text_stderr()
        message = "{}\n{}".format(
            crayons.normal("Failed parsing JSON results:", bold=True),
            decode_for_output(self.message.strip(), file),
        )
        click_echo(message, err=True)
        if self.error_text:
            click_echo(
                "{} {}".format(
                    crayons.normal("ERROR TEXT:", bold=True),
                    decode_for_output(self.error_text, file),
                ),
                err=True,
            )


class PipenvUsageError(UsageError):
    def __init__(self, message=None, ctx=None, **kwargs):
        formatted_message = "{0}: {1}"
        msg_prefix = crayons.red("ERROR:", bold=True)
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        message = formatted_message.format(msg_prefix, crayons.normal(message, bold=True))
        self.message = message
        extra = kwargs.pop("extra", [])
        UsageError.__init__(self, decode_for_output(message), ctx)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = vistir.misc.get_text_stderr()
        color = None
        if self.ctx is not None:
            color = self.ctx.color
        if self.extra:
            if isinstance(self.extra, STRING_TYPES):
                self.extra = [self.extra]
            for extra in self.extra:
                if color:
                    extra = getattr(crayons, color, "blue")(extra)
                click_echo(decode_for_output(extra, file), file=file)
        hint = ""
        if self.cmd is not None and self.cmd.get_help_option(self.ctx) is not None:
            hint = 'Try "%s %s" for help.\n' % (
                self.ctx.command_path,
                self.ctx.help_option_names[0],
            )
        if self.ctx is not None:
            click_echo(self.ctx.get_usage() + "\n%s" % hint, file=file, color=color)
        click_echo(self.message, file=file)


class PipenvFileError(FileError):
    formatted_message = "{0} {{0}} {{1}}".format(crayons.red("ERROR:", bold=True))

    def __init__(self, filename, message=None, **kwargs):
        extra = kwargs.pop("extra", [])
        if not message:
            message = crayons.normal("Please ensure that the file exists!", bold=True)
        message = self.formatted_message.format(
            crayons.normal(f"{filename} not found!", bold=True), message
        )
        FileError.__init__(
            self, filename=filename, hint=decode_for_output(message), **kwargs
        )
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = vistir.misc.get_text_stderr()
        if self.extra:
            if isinstance(self.extra, STRING_TYPES):
                self.extra = [self.extra]
            for extra in self.extra:
                click_echo(decode_for_output(extra, file), file=file)
        click_echo(self.message, file=file)


class PipfileNotFound(PipenvFileError):
    def __init__(self, filename="Pipfile", extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = "{} {}".format(
            crayons.red("Aborting!", bold=True),
            crayons.normal(
                "Please ensure that the file exists and is located in your"
                " project root directory.",
                bold=True,
            ),
        )
        super().__init__(filename, message=message, extra=extra, **kwargs)


class LockfileNotFound(PipenvFileError):
    def __init__(self, filename="Pipfile.lock", extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = "{} {} {}".format(
            crayons.normal("You need to run", bold=True),
            crayons.red("$ pipenv lock", bold=True),
            crayons.normal("before you can continue.", bold=True),
        )
        super().__init__(filename, message=message, extra=extra, **kwargs)


class DeployException(PipenvUsageError):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = str(crayons.normal("Aborting deploy", bold=True))
        extra = kwargs.pop("extra", [])
        PipenvUsageError.__init__(self, message=message, extra=extra, **kwargs)


class PipenvOptionsError(PipenvUsageError):
    def __init__(self, option_name, message=None, ctx=None, **kwargs):
        extra = kwargs.pop("extra", [])
        PipenvUsageError.__init__(self, message=message, ctx=ctx, **kwargs)
        self.extra = extra
        self.option_name = option_name


class SystemUsageError(PipenvOptionsError):
    def __init__(self, option_name="system", message=None, ctx=None, **kwargs):
        extra = kwargs.pop("extra", [])
        extra += [
            "{}: --system is intended to be used for Pipfile installation, "
            "not installation of specific packages. Aborting.".format(
                crayons.red("Warning", bold=True)
            ),
        ]
        if message is None:
            message = str(
                crayons.cyan("See also: {}".format(crayons.normal("--deploy flag.")))
            )
        super().__init__(option_name, message=message, ctx=ctx, extra=extra, **kwargs)


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
        PipenvException.__init__(self, message, **kwargs)


class VirtualenvActivationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = (
                "activate_this.py not found. Your environment is most certainly "
                "not activated. Continuing anyway..."
            )
        self.message = message
        VirtualenvException.__init__(self, message, **kwargs)


class VirtualenvCreationException(VirtualenvException):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = "Failed to create virtual environment."
        self.message = message
        extra = kwargs.pop("extra", None)
        if extra is not None and isinstance(extra, STRING_TYPES):
            # note we need the format interpolation because ``crayons.ColoredString``
            # is not an actual string type but is only a preparation for interpolation
            # so replacement or parsing requires this step
            extra = ANSI_REMOVAL_RE.sub("", f"{extra}")
            if "KeyboardInterrupt" in extra:
                extra = str(
                    crayons.red("Virtualenv creation interrupted by user", bold=True)
                )
            self.extra = extra = [extra]
        VirtualenvException.__init__(self, message, extra=extra)


class UninstallError(PipenvException):
    def __init__(self, package, command, return_values, return_code, **kwargs):
        extra = [
            "{} {}".format(
                crayons.cyan("Attempted to run command: "),
                crayons.yellow(f"$ {command!r}", bold=True),
            )
        ]
        extra.extend([crayons.cyan(line.strip()) for line in return_values.splitlines()])
        if isinstance(package, (tuple, list, set)):
            package = " ".join(package)
        message = "{!s} {!s}...".format(
            crayons.normal("Failed to uninstall package(s)"),
            crayons.yellow(f"{package}!s", bold=True),
        )
        self.exit_code = return_code
        PipenvException.__init__(self, message=message, extra=extra)
        self.extra = extra


class InstallError(PipenvException):
    def __init__(self, package, **kwargs):
        package_message = ""
        if package is not None:
            package_message = "Couldn't install package: {}\n".format(
                crayons.normal(f"{package!s}", bold=True)
            )
        message = "{} {}".format(
            f"{package_message}", crayons.yellow("Package installation failed...")
        )
        extra = kwargs.pop("extra", [])
        PipenvException.__init__(self, message=message, extra=extra, **kwargs)


class CacheError(PipenvException):
    def __init__(self, path, **kwargs):
        message = "{} {}\n{}".format(
            crayons.cyan("Corrupt cache file"),
            crayons.normal(f"{path!s}"),
            crayons.normal('Consider trying "pipenv lock --clear" to clear the cache.'),
        )
        PipenvException.__init__(self, message=message)


class DependencyConflict(PipenvException):
    def __init__(self, message):
        extra = [
            "{} {}".format(
                crayons.red("The operation failed...", bold=True),
                crayons.red(
                    "A dependency conflict was detected and could not be resolved."
                ),
            )
        ]
        PipenvException.__init__(self, message, extra=extra)


class ResolutionFailure(PipenvException):
    def __init__(self, message, no_version_found=False):
        extra = (
            "{}: Your dependencies could not be resolved. You likely have a "
            "mismatch in your sub-dependencies.\n  "
            "You can use {} to bypass this mechanism, then run "
            "{} to inspect the situation.\n  "
            "Hint: try {} if it is a pre-release dependency."
            "".format(
                crayons.red("Warning", bold=True),
                crayons.yellow("$ pipenv install --skip-lock"),
                crayons.yellow("$ pipenv graph"),
                crayons.yellow("$ pipenv lock --pre"),
            ),
        )
        if "no version found at all" in message:
            no_version_found = True
        message = crayons.yellow(f"{message}")
        if no_version_found:
            message = "{}\n{}".format(
                message,
                crayons.cyan(
                    "Please check your version specifier and version number. "
                    "See PEP440 for more information."
                ),
            )
        PipenvException.__init__(self, message, extra=extra)


class RequirementError(PipenvException):
    def __init__(self, req=None):
        from .utils import VCS_LIST

        keys = (
            (
                "name",
                "path",
            )
            + VCS_LIST
            + ("line", "uri", "url", "relpath")
        )
        if req is not None:
            possible_display_values = [getattr(req, value, None) for value in keys]
            req_value = next(
                iter(val for val in possible_display_values if val is not None), None
            )
            if not req_value:
                getstate_fn = getattr(req, "__getstate__", None)
                slots = getattr(req, "__slots__", None)
                keys_fn = getattr(req, "keys", None)
                if getstate_fn:
                    req_value = getstate_fn()
                elif slots:
                    slot_vals = [
                        (k, getattr(req, k, None)) for k in slots if getattr(req, k, None)
                    ]
                    req_value = "\n".join([f"    {k}: {v}" for k, v in slot_vals])
                elif keys_fn:
                    values = [(k, req.get(k)) for k in keys_fn() if req.get(k)]
                    req_value = "\n".join([f"    {k}: {v}" for k, v in values])
                else:
                    req_value = getattr(req.line_instance, "line", None)
        message = "{} {}".format(
            crayons.normal(decode_for_output("Failed creating requirement instance")),
            crayons.normal(decode_for_output(f"{req_value!r}")),
        )
        extra = [str(req)]
        PipenvException.__init__(self, message, extra=extra)


def prettify_exc(error):
    """Catch known errors and prettify them instead of showing the
    entire traceback, for better UX"""
    errors = []
    for exc in KNOWN_EXCEPTIONS:
        search_string = exc.match_string if exc.match_string else exc.exception_name
        split_string = (
            exc.show_from_string if exc.show_from_string else exc.exception_name
        )
        if search_string in error:
            # for known exceptions with no display rules and no prefix
            # we should simply show nothing
            if not exc.show_from_string and not exc.prefix:
                errors.append("")
                continue
            elif exc.prefix and exc.prefix in error:
                _, error, info = error.rpartition(exc.prefix)
            else:
                _, error, info = error.rpartition(split_string)
            errors.append(f"{error} {info}")
    if not errors:
        return f"{vistir.misc.decode_for_output(error)}"

    return "\n".join(errors)
