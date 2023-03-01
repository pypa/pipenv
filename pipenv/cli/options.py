import os
import re

from pipenv.project import Project
from pipenv.utils.internet import is_valid_url
from pipenv.vendor import click
from pipenv.vendor.click import (
    BadArgumentUsage,
    BadParameter,
    Group,
    Option,
    argument,
    echo,
    make_pass_decorator,
    option,
)
from pipenv.vendor.click import types as click_types
from pipenv.vendor.click_didyoumean import DYMMixin

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "auto_envvar_prefix": "PIPENV"}


class PipenvGroup(DYMMixin, Group):
    """Custom Group class provides formatted main help"""

    def get_help_option(self, ctx):
        from pipenv.utils.display import format_help

        """Override for showing formatted main help via --help and -h options"""
        help_options = self.get_help_option_names(ctx)
        if not help_options or not self.add_help_option:
            return

        def show_help(ctx, param, value):
            if value and not ctx.resilient_parsing:
                if not ctx.invoked_subcommand:
                    # legit main help
                    echo(format_help(ctx.get_help()))
                else:
                    # legit sub-command help
                    echo(ctx.get_help(), color=ctx.color)
                ctx.exit()

        return Option(
            help_options,
            is_flag=True,
            is_eager=True,
            expose_value=False,
            callback=show_help,
            help="Show this message and exit.",
        )

    def main(self, *args, **kwargs):
        """
        to specify the windows_expand_args option to avoid exceptions on Windows
        see: https://github.com/pallets/click/issues/1901
        """
        return super().main(*args, **kwargs, windows_expand_args=False)


class State:
    def __init__(self):
        self.index = None
        self.verbose = False
        self.quiet = False
        self.pypi_mirror = None
        self.python = None
        self.site_packages = None
        self.clear = False
        self.system = False
        self.project = Project()
        self.installstate = InstallState()
        self.lockoptions = LockOptions()


class InstallState:
    def __init__(self):
        self.dev = False
        self.pre = False
        self.selective_upgrade = False
        self.keep_outdated = False
        self.skip_lock = False
        self.ignore_pipfile = False
        self.code = False
        self.requirementstxt = None
        self.deploy = False
        self.packages = []
        self.editables = []
        self.extra_pip_args = []
        self.categories = []


class LockOptions:
    def __init__(self):
        self.dev_only = False


pass_state = make_pass_decorator(State, ensure=True)


def index_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.index = value
        return value

    return option(
        "-i",
        "--index",
        expose_value=False,
        envvar="PIP_INDEX_URL",
        help="Specify target package index by url or index name from Pipfile.",
        nargs=1,
        callback=callback,
    )(f)


def editable_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.editables.extend(value)
        return value

    return option(
        "-e",
        "--editable",
        expose_value=False,
        multiple=True,
        callback=callback,
        type=click_types.Path(file_okay=False),
        help="An editable Python package URL or path, often to a VCS repository.",
    )(f)


def skip_lock_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.skip_lock = value
        return value

    return option(
        "--skip-lock",
        is_flag=True,
        default=False,
        expose_value=False,
        help="Skip locking mechanisms and use the Pipfile instead during operation.",
        envvar="PIPENV_SKIP_LOCK",
        callback=callback,
        type=click_types.BOOL,
        show_envvar=True,
    )(f)


def keep_outdated_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.keep_outdated = value
        if value:
            click.secho(
                "The flag --keep-outdated has been deprecated for removal.  "
                "The flag does not respect package resolver results and leads to inconsistent lock files.  "
                "Consider using the new `pipenv upgrade` command to selectively upgrade packages.",
                fg="yellow",
                bold=True,
                err=True,
            )
        return value

    return option(
        "--keep-outdated",
        is_flag=True,
        default=False,
        expose_value=False,
        help="Keep out-dated dependencies from being updated in Pipfile.lock.",
        callback=callback,
        type=click_types.BOOL,
        show_envvar=True,
    )(f)


def selective_upgrade_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.selective_upgrade = value
        if value:
            click.secho(
                "The flag --selective-upgrade has been deprecated for removal.  "
                "The flag is buggy and leads to inconsistent lock files.  "
                "Consider using the new `pipenv upgrade` command to selectively upgrade packages.",
                fg="yellow",
                bold=True,
                err=True,
            )
        return value

    return option(
        "--selective-upgrade",
        is_flag=True,
        default=False,
        type=click_types.BOOL,
        help="Update specified packages.",
        callback=callback,
        expose_value=False,
    )(f)


def ignore_pipfile_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.ignore_pipfile = value
        return value

    return option(
        "--ignore-pipfile",
        is_flag=True,
        default=False,
        expose_value=False,
        help="Ignore Pipfile when installing, using the Pipfile.lock.",
        callback=callback,
        type=click_types.BOOL,
        show_envvar=True,
    )(f)


def _dev_option(f, help_text):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.dev = value
        return value

    return option(
        "--dev",
        "-d",
        is_flag=True,
        default=False,
        type=click_types.BOOL,
        help=help_text,
        callback=callback,
        expose_value=False,
        show_envvar=True,
    )(f)


def categories_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            for opt in re.split(r", *| ", value):
                state.installstate.categories.append(opt)
        return value

    return option(
        "--categories",
        nargs=1,
        required=False,
        callback=callback,
        expose_value=True,
        type=click_types.STRING,
    )(f)


def install_dev_option(f):
    return _dev_option(f, "Install both develop and default packages")


def lock_dev_option(f):
    return _dev_option(f, "Generate both develop and default requirements")


def uninstall_dev_option(f):
    return _dev_option(
        f, "Deprecated (as it has no effect). May be removed in a future release."
    )


def pre_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.pre = value
        return value

    return option(
        "--pre",
        is_flag=True,
        default=False,
        help="Allow pre-releases.",
        callback=callback,
        type=click_types.BOOL,
        expose_value=False,
    )(f)


def package_arg(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.packages.extend(value)
        return value

    return argument(
        "packages",
        nargs=-1,
        callback=callback,
        expose_value=True,
        type=click_types.STRING,
    )(f)


def extra_pip_args(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            for opt in value.split(" "):
                state.installstate.extra_pip_args.append(opt)
        return value

    return option(
        "--extra-pip-args",
        nargs=1,
        required=False,
        callback=callback,
        expose_value=True,
        type=click_types.STRING,
    )(f)


def python_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.python = validate_python_path(ctx, param, value)
        return value

    return option(
        "--python",
        default="",
        nargs=1,
        callback=callback,
        help="Specify which version of Python virtualenv should use.",
        expose_value=False,
        allow_from_autoenv=False,
        type=click_types.STRING,
    )(f)


def pypi_mirror_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        value = value or state.project.s.PIPENV_PYPI_MIRROR
        if value is not None:
            state.pypi_mirror = validate_pypi_mirror(ctx, param, value)
        return value

    return option(
        "--pypi-mirror",
        nargs=1,
        callback=callback,
        help="Specify a PyPI mirror.",
        expose_value=False,
    )(f)


def verbose_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            if state.quiet:
                raise BadArgumentUsage(
                    "--verbose and --quiet are mutually exclusive! Please choose one!",
                    ctx=ctx,
                )
            state.verbose = True
            setup_verbosity(ctx, param, 1)

    return option(
        "--verbose",
        "-v",
        is_flag=True,
        expose_value=False,
        callback=callback,
        help="Verbose mode.",
        type=click_types.BOOL,
    )(f)


def quiet_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            if state.verbose:
                raise BadArgumentUsage(
                    "--verbose and --quiet are mutually exclusive! Please choose one!",
                    ctx=ctx,
                )
            state.quiet = True
            setup_verbosity(ctx, param, -1)

    return option(
        "--quiet",
        "-q",
        is_flag=True,
        expose_value=False,
        callback=callback,
        help="Quiet mode.",
        type=click_types.BOOL,
    )(f)


def site_packages_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        validate_bool_or_none(ctx, param, value)
        state.site_packages = value
        return value

    return option(
        "--site-packages/--no-site-packages",
        is_flag=True,
        default=None,
        help="Enable site-packages for the virtualenv.",
        callback=callback,
        expose_value=False,
        show_envvar=True,
    )(f)


def clear_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.clear = value
        return value

    return option(
        "--clear",
        is_flag=True,
        callback=callback,
        type=click_types.BOOL,
        help="Clears caches (pipenv, pip).",
        expose_value=False,
        show_envvar=True,
    )(f)


def system_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.system = value
        return value

    return option(
        "--system",
        is_flag=True,
        default=False,
        help="System pip management.",
        callback=callback,
        type=click_types.BOOL,
        expose_value=False,
        show_envvar=True,
    )(f)


def requirementstxt_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.installstate.requirementstxt = value
        return value

    return option(
        "--requirements",
        "-r",
        nargs=1,
        default="",
        expose_value=False,
        help="Import a requirements.txt file.",
        callback=callback,
        type=click_types.Path(dir_okay=False),
    )(f)


def dev_only_flag(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.lockoptions.dev_only = value
        return value

    return option(
        "--dev-only",
        default=False,
        is_flag=True,
        expose_value=False,
        help="Emit development dependencies *only* (overrides --dev)",
        callback=callback,
    )(f)


def deploy_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.deploy = value
        return value

    return option(
        "--deploy",
        is_flag=True,
        default=False,
        type=click_types.BOOL,
        help="Abort if the Pipfile.lock is out-of-date, or Python version is wrong.",
        callback=callback,
        expose_value=False,
    )(f)


def lock_only_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.lock_only = value
        return value

    return option(
        "--lock-only",
        is_flag=True,
        default=False,
        help="Only update lock file (specifiers not added to Pipfile).",
        callback=callback,
        type=click_types.BOOL,
        expose_value=False,
    )(f)


def setup_verbosity(ctx, param, value):
    if not value:
        return
    ctx.ensure_object(State).project.s.PIPENV_VERBOSITY = value


def validate_python_path(ctx, param, value):
    # Validating the Python path is complicated by accepting a number of
    # friendly options: the default will be boolean False to enable
    # autodetection but it may also be a value which will be searched in
    # the path or an absolute path. To report errors as early as possible
    # we'll report absolute paths which do not exist:
    if isinstance(value, (str, bytes)):
        if os.path.isabs(value) and not os.path.isfile(value):
            raise BadParameter("Expected Python at path %s does not exist" % value)
    return value


def validate_bool_or_none(ctx, param, value):
    if value is not None:
        return click_types.BOOL(value)
    return False


def validate_pypi_mirror(ctx, param, value):
    if value and not is_valid_url(value):
        raise BadParameter("Invalid PyPI mirror URL: %s" % value)
    return value


def common_options(f):
    f = pypi_mirror_option(f)
    f = verbose_option(f)
    f = quiet_option(f)
    f = clear_option(f)
    f = python_option(f)
    return f


def install_base_options(f):
    f = common_options(f)
    f = pre_option(f)
    f = keep_outdated_option(f)
    f = extra_pip_args(f)
    return f


def uninstall_options(f):
    f = install_base_options(f)
    f = categories_option(f)
    f = uninstall_dev_option(f)
    f = skip_lock_option(f)
    f = editable_option(f)
    f = package_arg(f)
    return f


def lock_options(f):
    f = install_base_options(f)
    f = lock_dev_option(f)
    f = dev_only_flag(f)
    f = categories_option(f)
    return f


def sync_options(f):
    f = install_base_options(f)
    f = install_dev_option(f)
    f = categories_option(f)
    return f


def install_options(f):
    f = sync_options(f)
    f = index_option(f)
    f = requirementstxt_option(f)
    f = selective_upgrade_option(f)
    f = ignore_pipfile_option(f)
    f = editable_option(f)
    f = package_arg(f)
    return f


def upgrade_options(f):
    f = lock_only_option(f)
    return f


def general_options(f):
    f = common_options(f)
    f = site_packages_option(f)
    return f
