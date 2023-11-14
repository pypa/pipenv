import itertools
import sys
from collections import namedtuple
from traceback import format_tb

from pipenv.vendor import click
from pipenv.vendor.click.exceptions import ClickException, FileError, UsageError

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
    from pipenv import environments

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
            line = f"[{exception.__class__.__name__!s}]: {line}"
            formatted_lines.append(line)
        # use new exception prettification rules to format exceptions according to
        # UX rules
        click.echo(prettify_exc("\n".join(formatted_lines)), err=True)
        exception.show()


sys.excepthook = handle_exception


class PipenvException(ClickException):
    message = "{}: {{}}".format(click.style("ERROR", fg="red", bold=True))

    def __init__(self, message=None, **kwargs):
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        extra = kwargs.pop("extra", [])
        message = self.message.format(message)
        ClickException.__init__(self, message)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = sys.stderr
        if self.extra:
            if isinstance(self.extra, str):
                self.extra = [self.extra]
            for extra in self.extra:
                extra = f"[pipenv.exceptions.{self.__class__.__name__}]: {extra}"
                click.echo(extra, file=file)
        click.echo(f"{self.message}", file=file)


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
            file = sys.stderr
        click.echo(
            "{} {}".format(
                click.style("Error running command: ", fg="red"),
                click.style(f"$ {self.cmd}", bold=True),
            ),
            err=True,
            file=file,
        )
        if self.out:
            click.echo(
                "{} {}".format("OUTPUT: ", self.out),
                file=file,
                err=True,
            )
        if self.err:
            click.echo(
                "{} {}".format("STDERR: ", self.err),
                file=file,
                err=True,
            )


class JSONParseError(PipenvException):
    def __init__(self, contents="", error_text=""):
        self.error_text = error_text
        PipenvException.__init__(self, contents)

    def show(self, file=None):
        if file is None:
            file = sys.stderr
        message = "{}\n{}".format(
            click.style("Failed parsing JSON results:", bold=True),
            print(self.message.strip(), file=file),
        )
        click.echo(message, err=True)
        if self.error_text:
            click.echo(
                "{} {}".format(
                    click.style("ERROR TEXT:", bold=True),
                    print(self.error_text, file=file),
                ),
                err=True,
            )


class PipenvUsageError(UsageError):
    def __init__(self, message=None, ctx=None, **kwargs):
        formatted_message = "{0}: {1}"
        msg_prefix = click.style("ERROR:", fg="red", bold=True)
        if not message:
            message = "Pipenv encountered a problem and had to exit."
        message = formatted_message.format(msg_prefix, click.style(message, bold=True))
        self.message = message
        extra = kwargs.pop("extra", [])
        UsageError.__init__(self, message, ctx)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = sys.stderr
        color = None
        if self.ctx is not None:
            color = self.ctx.color
        if self.extra:
            if isinstance(self.extra, str):
                self.extra = [self.extra]
            for extra in self.extra:
                if color:
                    extra = click.style(extra, fg=color)
                click.echo(extra, file=file)
        hint = ""
        if self.cmd is not None and self.cmd.get_help_option(self.ctx) is not None:
            hint = f'Try "{self.ctx.command_path} {self.ctx.help_option_names[0]}" for help.\n'
        if self.ctx is not None:
            click.echo(self.ctx.get_usage() + "\n%s" % hint, file=file, color=color)
        click.echo(self.message, file=file)


class PipenvFileError(FileError):
    formatted_message = "{} {{}} {{}}".format(click.style("ERROR:", fg="red", bold=True))

    def __init__(self, filename, message=None, **kwargs):
        extra = kwargs.pop("extra", [])
        if not message:
            message = click.style("Please ensure that the file exists!", bold=True)
        message = self.formatted_message.format(
            click.style(f"{filename} not found!", bold=True), message
        )
        FileError.__init__(self, filename=filename, hint=message, **kwargs)
        self.extra = extra

    def show(self, file=None):
        if file is None:
            file = sys.stderr
        if self.extra:
            if isinstance(self.extra, str):
                self.extra = [self.extra]
            for extra in self.extra:
                click.echo(extra, file=file)
        click.echo(self.message, file=file)


class PipfileNotFound(PipenvFileError):
    def __init__(self, filename="Pipfile", extra=None, **kwargs):
        extra = kwargs.pop("extra", [])
        message = "{} {}".format(
            click.style("Aborting!", bold=True, fg="red"),
            click.style(
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
            click.style("You need to run", bold=True),
            click.style("$ pipenv lock", bold=True, fg="red"),
            click.style("before you can continue.", bold=True),
        )
        super().__init__(filename, message=message, extra=extra, **kwargs)


class DeployException(PipenvUsageError):
    def __init__(self, message=None, **kwargs):
        if not message:
            message = click.style("Aborting deploy", bold=True)
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
                click.style("Warning", bold=True, fg="red")
            ),
        ]
        if message is None:
            message = "{} --deploy flag".format(
                click.style("See also: {}", fg="cyan"),
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
        if extra is not None and isinstance(extra, str):
            extra = click.unstyle(f"{extra}")
            if "KeyboardInterrupt" in extra:
                extra = click.style(
                    "Virtualenv creation interrupted by user", fg="red", bold=True
                )
            self.extra = extra = [extra]
        VirtualenvException.__init__(self, message, extra=extra)


class UninstallError(PipenvException):
    def __init__(self, package, command, return_values, return_code, **kwargs):
        extra = [
            "{} {}".format(
                click.style("Attempted to run command: ", fg="cyan"),
                click.style(f"$ {command!r}", bold=True, fg="yellow"),
            )
        ]
        extra.extend(
            [click.style(line.strip(), fg="cyan") for line in return_values.splitlines()]
        )
        if isinstance(package, (tuple, list, set)):
            package = " ".join(package)
        message = "{!s} {!s}...".format(
            click.style("Failed to uninstall package(s)", fg="reset"),
            click.style(f"{package}!s", bold=True, fg="yellow"),
        )
        self.exit_code = return_code
        PipenvException.__init__(self, message=message, extra=extra)
        self.extra = extra


class InstallError(PipenvException):
    def __init__(self, package, **kwargs):
        package_message = ""
        if package is not None:
            package_message = "Couldn't install package: {}\n".format(
                click.style(f"{package!s}", bold=True)
            )
        message = "{} {}".format(
            f"{package_message}",
            click.style("Package installation failed...", fg="yellow"),
        )
        extra = kwargs.pop("extra", [])
        PipenvException.__init__(self, message=message, extra=extra, **kwargs)


class CacheError(PipenvException):
    def __init__(self, path, **kwargs):
        message = "{} {}\n{}".format(
            click.style("Corrupt cache file", fg="cyan"),
            click.style(f"{path!s}", fg="reset", bg="reset"),
            click.style('Consider trying "pipenv lock --clear" to clear the cache.'),
        )
        PipenvException.__init__(self, message=message)


class DependencyConflict(PipenvException):
    def __init__(self, message):
        extra = [
            "{} {}".format(
                click.style("The operation failed...", bold=True, fg="red"),
                click.style(
                    "A dependency conflict was detected and could not be resolved.",
                    fg="red",
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
            "{} to inspect the versions actually installed in the virtualenv.\n  "
            "Hint: try {} if it is a pre-release dependency."
            "".format(
                click.style("Warning", fg="red", bold=True),
                click.style("$ pipenv run pip install <requirement_name>", fg="yellow"),
                click.style("$ pipenv graph", fg="yellow"),
                click.style("$ pipenv lock --pre", fg="yellow"),
            ),
        )
        if "no version found at all" in message:
            no_version_found = True
        message = click.style(f"{message}", fg="yellow")
        if no_version_found:
            message = "{}\n{}".format(
                message,
                click.style(
                    "Please check your version specifier and version number. "
                    "See PEP440 for more information.",
                    fg="cyan",
                ),
            )
        PipenvException.__init__(self, message, extra=extra)


class RequirementError(PipenvException):
    def __init__(self, req=None):
        from pipenv.utils.constants import VCS_LIST

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
        message = click.style(
            f"Failed creating requirement instance {req_value}",
            bold=False,
            fg="reset",
            bg="reset",
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
        return error

    return "\n".join(errors)
