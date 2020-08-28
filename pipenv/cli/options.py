# -*- coding=utf-8 -*-
from __future__ import absolute_import

import os

import click.types

from click import (
    BadParameter, BadArgumentUsage, Group, Option, argument, echo, make_pass_decorator, option
)
from click_didyoumean import DYMMixin

from .. import environments
from ..utils import is_valid_url


CONTEXT_SETTINGS = {
    "help_option_names": ["-h", "--help"],
    "auto_envvar_prefix": "PIPENV"
}


class PipenvGroup(DYMMixin, Group):
    """Custom Group class provides formatted main help"""

    def get_help_option(self, ctx):
        from ..core import format_help

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


class State(object):
    def __init__(self):
        self.index = None
        self.extra_index_urls = []
        self.verbose = False
        self.quiet = False
        self.pypi_mirror = None
        self.python = None
        self.two = None
        self.three = None
        self.site_packages = None
        self.clear = False
        self.system = False
        self.installstate = InstallState()
        self.lockoptions = LockOptions()


class InstallState(object):
    def __init__(self):
        self.dev = False
        self.pre = False
        self.selective_upgrade = False
        self.keep_outdated = False
        self.skip_lock = False
        self.ignore_pipfile = False
        self.sequential = False
        self.code = False
        self.requirementstxt = None
        self.deploy = False
        self.packages = []
        self.editables = []


class LockOptions(object):
    def __init__(self):
        self.dev_only = False
        self.emit_requirements = False
        self.emit_requirements_header = False


pass_state = make_pass_decorator(State, ensure=True)


def index_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.index = value
        return value
    return option('-i', '--index', expose_value=False, envvar="PIP_INDEX_URL",
                  help='Target PyPI-compatible package index url.', nargs=1,
                  callback=callback)(f)


def extra_index_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.extra_index_urls.extend(list(value))
        return value
    return option("--extra-index-url", multiple=True, expose_value=False,
                  help=u"URLs to the extra PyPI compatible indexes to query for package look-ups.",
                  callback=callback, envvar="PIP_EXTRA_INDEX_URL")(f)


def editable_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.editables.extend(value)
        return value
    return option('-e', '--editable', expose_value=False, multiple=True,
                  callback=callback, type=click.types.STRING, help=(
                      "An editable Python package URL or path, often to a VCS "
                      "repository."
                  ))(f)


def sequential_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.sequential = value
        return value
    return option("--sequential", is_flag=True, default=False, expose_value=False,
                  help="Install dependencies one-at-a-time, instead of concurrently.",
                  callback=callback, type=click.types.BOOL, show_envvar=True)(f)


def skip_lock_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.skip_lock = value
        return value
    return option("--skip-lock", is_flag=True, default=False, expose_value=False,
                  help=u"Skip locking mechanisms and use the Pipfile instead during operation.",
                  envvar="PIPENV_SKIP_LOCK", callback=callback, type=click.types.BOOL,
                  show_envvar=True)(f)


def keep_outdated_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.keep_outdated = value
        return value
    return option("--keep-outdated", is_flag=True, default=False, expose_value=False,
                  help=u"Keep out-dated dependencies from being updated in Pipfile.lock.",
                  callback=callback, type=click.types.BOOL, show_envvar=True)(f)


def selective_upgrade_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.selective_upgrade = value
        return value
    return option("--selective-upgrade", is_flag=True, default=False, type=click.types.BOOL,
                  help="Update specified packages.", callback=callback,
                  expose_value=False)(f)


def ignore_pipfile_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.ignore_pipfile = value
        return value
    return option("--ignore-pipfile", is_flag=True, default=False, expose_value=False,
                  help="Ignore Pipfile when installing, using the Pipfile.lock.",
                  callback=callback, type=click.types.BOOL, show_envvar=True)(f)


def _dev_option(f, help_text):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.dev = value
        return value
    return option("--dev", "-d", is_flag=True, default=False, type=click.types.BOOL,
                  help=help_text, callback=callback,
                  expose_value=False, show_envvar=True)(f)


def install_dev_option(f):
    return _dev_option(f, "Install both develop and default packages")


def lock_dev_option(f):
    return _dev_option(f, "Generate both develop and default requirements")


def uninstall_dev_option(f):
    return _dev_option(f, "Deprecated (as it has no effect). May be removed in a future release.")


def pre_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.pre = value
        return value
    return option("--pre", is_flag=True, default=False, help=u"Allow pre-releases.",
                  callback=callback, type=click.types.BOOL, expose_value=False)(f)


def package_arg(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.packages.extend(value)
        return value
    return argument('packages', nargs=-1, callback=callback, expose_value=False,
                    type=click.types.STRING)(f)


def three_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.three = value
            state.two = not value
        return value
    return option("--three/--two", is_flag=True, default=None,
                  help="Use Python 3/2 when creating virtualenv.", callback=callback,
                  expose_value=False)(f)


def python_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.python = validate_python_path(ctx, param, value)
        return value
    return option("--python", default=False, nargs=1, callback=callback,
                  help="Specify which version of Python virtualenv should use.",
                  expose_value=False, allow_from_autoenv=False)(f)


def pypi_mirror_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.pypi_mirror = validate_pypi_mirror(ctx, param, value)
        return value
    return option("--pypi-mirror", default=environments.PIPENV_PYPI_MIRROR, nargs=1,
                  callback=callback, help="Specify a PyPI mirror.", expose_value=False)(f)


def verbose_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            if state.quiet:
                raise BadArgumentUsage(
                    "--verbose and --quiet are mutually exclusive! Please choose one!",
                    ctx=ctx
                )
            state.verbose = True
            setup_verbosity(ctx, param, 1)
    return option("--verbose", "-v", is_flag=True, expose_value=False,
                  callback=callback, help="Verbose mode.", type=click.types.BOOL)(f)


def quiet_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            if state.verbose:
                raise BadArgumentUsage(
                    "--verbose and --quiet are mutually exclusive! Please choose one!",
                    ctx=ctx
                )
            state.quiet = True
            setup_verbosity(ctx, param, -1)
    return option("--quiet", "-q", is_flag=True, expose_value=False,
                  callback=callback, help="Quiet mode.", type=click.types.BOOL)(f)


def site_packages_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        validate_bool_or_none(ctx, param, value)
        state.site_packages = value
        return value
    return option("--site-packages/--no-site-packages", is_flag=True, default=None,
                  help="Enable site-packages for the virtualenv.", callback=callback,
                  expose_value=False, show_envvar=True)(f)


def clear_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.clear = value
        return value
    return option("--clear", is_flag=True, callback=callback, type=click.types.BOOL,
                  help="Clears caches (pipenv, pip, and pip-tools).",
                  expose_value=False, show_envvar=True)(f)


def system_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value is not None:
            state.system = value
        return value
    return option("--system", is_flag=True, default=False, help="System pip management.",
                  callback=callback, type=click.types.BOOL, expose_value=False,
                  show_envvar=True)(f)


def requirementstxt_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.installstate.requirementstxt = value
        return value
    return option("--requirements", "-r", nargs=1, default=False, expose_value=False,
                  help="Import a requirements.txt file.", callback=callback)(f)


def emit_requirements_flag(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.lockoptions.emit_requirements = value
        return value
    return option("--requirements", "-r", default=False, is_flag=True, expose_value=False,
                  help="Generate output in requirements.txt format.", callback=callback)(f)


def emit_requirements_header_flag(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.lockoptions.emit_requirements_header = value
        return value
    return option("--header/--no-header", default=True, is_flag=True, expose_value=False,
                  help="Add header to generated requirements", callback=callback)(f)


def dev_only_flag(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.lockoptions.dev_only = value
        return value
    return option("--dev-only", default=False, is_flag=True, expose_value=False,
                  help="Emit development dependencies *only* (overrides --dev)", callback=callback)(f)


def code_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        if value:
            state.installstate.code = value
        return value
    return option("--code", "-c", nargs=1, default=False, help="Install packages "
                  "automatically discovered from import statements.", callback=callback,
                  expose_value=False)(f)


def deploy_option(f):
    def callback(ctx, param, value):
        state = ctx.ensure_object(State)
        state.installstate.deploy = value
        return value
    return option("--deploy", is_flag=True, default=False, type=click.types.BOOL,
                  help=u"Abort if the Pipfile.lock is out-of-date, or Python version is"
                  " wrong.", callback=callback, expose_value=False)(f)


def setup_verbosity(ctx, param, value):
    if not value:
        return
    import logging
    loggers = ("pip", "piptools")
    if value == 1:
        for logger in loggers:
            logging.getLogger(logger).setLevel(logging.INFO)
    elif value == -1:
        for logger in loggers:
            logging.getLogger(logger).setLevel(logging.CRITICAL)
    environments.PIPENV_VERBOSITY = value


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
        return click.types.BOOL(value)
    return False


def validate_pypi_mirror(ctx, param, value):
    if value and not is_valid_url(value):
        raise BadParameter("Invalid PyPI mirror URL: %s" % value)
    return value


def common_options(f):
    f = pypi_mirror_option(f)
    f = verbose_option(f)
    f = clear_option(f)
    f = three_option(f)
    f = python_option(f)
    return f


def install_base_options(f):
    f = common_options(f)
    f = pre_option(f)
    f = keep_outdated_option(f)
    return f


def uninstall_options(f):
    f = install_base_options(f)
    f = uninstall_dev_option(f)
    f = skip_lock_option(f)
    f = editable_option(f)
    f = package_arg(f)
    return f


def lock_options(f):
    f = install_base_options(f)
    f = lock_dev_option(f)
    f = emit_requirements_flag(f)
    f = emit_requirements_header_flag(f)
    f = dev_only_flag(f)
    return f


def sync_options(f):
    f = install_base_options(f)
    f = install_dev_option(f)
    f = sequential_option(f)
    return f


def install_options(f):
    f = sync_options(f)
    f = index_option(f)
    f = extra_index_option(f)
    f = requirementstxt_option(f)
    f = selective_upgrade_option(f)
    f = ignore_pipfile_option(f)
    f = editable_option(f)
    f = package_arg(f)
    return f


def general_options(f):
    f = common_options(f)
    f = site_packages_option(f)
    return f
