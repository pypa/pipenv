# -*- coding: utf-8 -*-
import os
import sys
from click import (
    argument,
    command,
    echo,
    edit,
    group,
    Group,
    option,
    pass_context,
    Option,
    version_option,
    BadParameter,
)
from click_didyoumean import DYMCommandCollection

import click_completion
import crayons
import delegator

from .__version__ import __version__

from . import environments
from .utils import is_valid_url

# Enable shell completion.
click_completion.init()
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


class PipenvGroup(Group):
    """Custom Group class provides formatted main help"""

    def get_help_option(self, ctx):
        from .core import format_help

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
            help='Show this message and exit.',
        )


def setup_verbose(ctx, param, value):
    if value:
        import logging
        logging.getLogger('pip').setLevel(logging.INFO)
    return value


def validate_python_path(ctx, param, value):
    # Validating the Python path is complicated by accepting a number of
    # friendly options: the default will be boolean False to enable
    # autodetection but it may also be a value which will be searched in
    # the path or an absolute path. To report errors as early as possible
    # we'll report absolute paths which do not exist:
    if isinstance(value, (str, bytes)):
        if os.path.isabs(value) and not os.path.isfile(value):
            raise BadParameter('Expected Python at path %s does not exist' % value)
    return value


def validate_pypi_mirror(ctx, param, value):
    if value and not is_valid_url(value):
        raise BadParameter('Invalid PyPI mirror URL: %s' % value)
    return value


@group(
    cls=PipenvGroup,
    invoke_without_command=True,
    context_settings=CONTEXT_SETTINGS,
)
@option(
    '--where',
    is_flag=True,
    default=False,
    help="Output project home information.",
)
@option(
    '--venv',
    is_flag=True,
    default=False,
    help="Output virtualenv information.",
)
@option(
    '--py',
    is_flag=True,
    default=False,
    help="Output Python interpreter information.",
)
@option(
    '--envs',
    is_flag=True,
    default=False,
    help="Output Environment Variable options.",
)
@option(
    '--rm', is_flag=True, default=False, help="Remove the virtualenv."
)
@option('--bare', is_flag=True, default=False, help="Minimal output.")
@option(
    '--completion',
    is_flag=True,
    default=False,
    help="Output completion (to be eval'd).",
)
@option('--man', is_flag=True, default=False, help="Display manpage.")
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--site-packages',
    is_flag=True,
    default=False,
    help="Enable site-packages for the virtualenv.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@option(
    '--support',
    is_flag=True,
    help="Output diagnostic information for use in Github issues."
)
@version_option(
    prog_name=crayons.normal('pipenv', bold=True), version=__version__
)
@pass_context
def cli(
    ctx,
    where=False,
    venv=False,
    rm=False,
    bare=False,
    three=False,
    python=False,
    help=False,
    py=False,
    site_packages=False,
    envs=False,
    man=False,
    completion=False,
    pypi_mirror=None,
    support=None
):
    if completion:  # Handle this ASAP to make shell startup fast.
        from . import shells
        try:
            shell = shells.detect_info()[0]
        except shells.ShellDetectionFailure:
            echo(
                'Fail to detect shell. Please provide the {0} environment '
                'variable.'.format(crayons.normal('PIPENV_SHELL', bold=True)),
                err=True,
            )
            sys.exit(1)
        print(click_completion.get_code(shell=shell, prog_name='pipenv'))
        sys.exit(0)

    from .core import (
        system_which,
        do_py,
        warn_in_virtualenv,
        do_where,
        project,
        spinner,
        cleanup_virtualenv,
        ensure_project,
        format_help
    )
    if man:
        if system_which('man'):
            path = os.sep.join([os.path.dirname(__file__), 'pipenv.1'])
            os.execle(system_which('man'), 'man', path, os.environ)
        else:
            echo(
                'man does not appear to be available on your system.', err=True
            )
    if envs:
        echo(
            'The following environment variables can be set, to do various things:\n'
        )
        for key in environments.__dict__:
            if key.startswith('PIPENV'):
                echo('  - {0}'.format(crayons.normal(key, bold=True)))
        echo(
            '\nYou can learn more at:\n   {0}'.format(
                crayons.green(
                    'http://docs.pipenv.org/advanced/#configuration-with-environment-variables'
                )
            )
        )
        sys.exit(0)
    warn_in_virtualenv()
    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            do_where(bare=True)
            sys.exit(0)
        elif py:
            do_py()
            sys.exit()
        # --support was passed...
        elif support:
            from .help import get_pipenv_diagnostics
            get_pipenv_diagnostics()
            sys.exit(0)
        # --venv was passed...
        elif venv:
            # There is no virtualenv yet.
            if not project.virtualenv_exists:
                echo(
                    crayons.red(
                        'No virtualenv has been created for this project yet!'
                    ),
                    err=True,
                )
                sys.exit(1)
            else:
                echo(project.virtualenv_location)
                sys.exit(0)
        # --rm was passed...
        elif rm:
            # Abort if --system (or running in a virtualenv).
            if environments.PIPENV_USE_SYSTEM:
                echo(
                    crayons.red(
                        'You are attempting to remove a virtualenv that '
                        'Pipenv did not create. Aborting.'
                    )
                )
                sys.exit(1)
            if project.virtualenv_exists:
                loc = project.virtualenv_location
                echo(
                    crayons.normal(
                        u'{0} ({1})...'.format(
                            crayons.normal('Removing virtualenv', bold=True),
                            crayons.green(loc),
                        )
                    )
                )
                with spinner():
                    # Remove the virtualenv.
                    cleanup_virtualenv(bare=True)
                sys.exit(0)
            else:
                echo(
                    crayons.red(
                        'No virtualenv has been created for this project yet!',
                        bold=True,
                    ),
                    err=True,
                )
                sys.exit(1)
    # --two / --three was passed...
    if (python or three is not None) or site_packages:
        ensure_project(
            three=three, python=python, warn=True, site_packages=site_packages, pypi_mirror=pypi_mirror
        )
    # Check this again before exiting for empty ``pipenv`` command.
    elif ctx.invoked_subcommand is None:
        # Display help to user, if no commands were passed.
        echo(format_help(ctx.get_help()))


@command(
    short_help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.",
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True),
)
@argument('package_name', default=False)
@argument('more_packages', nargs=-1)
@option(
    '--dev',
    '-d',
    is_flag=True,
    default=False,
    help="Install package(s) in [dev-packages].",
)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@option(
    '--system', is_flag=True, default=False, help="System pip management."
)
@option(
    '--requirements',
    '-r',
    nargs=1,
    default=False,
    help="Import a requirements.txt file.",
)
@option(
    '--code', '-c', nargs=1, default=False, help="Import from codebase."
)
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option(
    '--ignore-pipfile',
    is_flag=True,
    default=False,
    help="Ignore Pipfile when installing, using the Pipfile.lock.",
)
@option(
    '--sequential',
    is_flag=True,
    default=False,
    help="Install dependencies one-at-a-time, instead of concurrently.",
)
@option(
    '--skip-lock',
    is_flag=True,
    default=False,
    help=u"Ignore locking mechanisms when installing—use the Pipfile, instead.",
)
@option(
    '--deploy',
    is_flag=True,
    default=False,
    help=u"Abort if the Pipfile.lock is out-of-date, or Python version is wrong.",
)
@option(
    '--pre', is_flag=True, default=False, help=u"Allow pre-releases."
)
@option(
    '--keep-outdated',
    is_flag=True,
    default=False,
    help=u"Keep out-dated dependencies from being updated in Pipfile.lock.",
)
@option(
    '--selective-upgrade',
    is_flag=True,
    default=False,
    help="Update specified packages.",
)
def install(
    package_name=False,
    more_packages=False,
    dev=False,
    three=False,
    python=False,
    pypi_mirror=None,
    system=False,
    lock=True,
    ignore_pipfile=False,
    skip_lock=False,
    verbose=False,
    requirements=False,
    sequential=False,
    pre=False,
    code=False,
    deploy=False,
    keep_outdated=False,
    selective_upgrade=False,
):
    from .core import do_install

    do_install(
        package_name=package_name,
        more_packages=more_packages,
        dev=dev,
        three=three,
        python=python,
        pypi_mirror=pypi_mirror,
        system=system,
        lock=lock,
        ignore_pipfile=ignore_pipfile,
        skip_lock=skip_lock,
        verbose=verbose,
        requirements=requirements,
        sequential=sequential,
        pre=pre,
        code=code,
        deploy=deploy,
        keep_outdated=keep_outdated,
        selective_upgrade=selective_upgrade,
    )


@command(
    short_help="Un-installs a provided package and removes it from Pipfile."
)
@argument('package_name', default=False)
@argument('more_packages', nargs=-1)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--system', is_flag=True, default=False, help="System pip management."
)
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option('--lock', is_flag=True, default=True, help="Lock afterwards.")
@option(
    '--all-dev',
    is_flag=True,
    default=False,
    help="Un-install all package from [dev-packages].",
)
@option(
    '--all',
    is_flag=True,
    default=False,
    help="Purge all package(s) from virtualenv. Does not edit Pipfile.",
)
@option(
    '--keep-outdated',
    is_flag=True,
    default=False,
    help=u"Keep out-dated dependencies from being updated in Pipfile.lock.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
def uninstall(
    package_name=False,
    more_packages=False,
    three=None,
    python=False,
    system=False,
    lock=False,
    all_dev=False,
    all=False,
    verbose=False,
    keep_outdated=False,
    pypi_mirror=None,
):
    from .core import do_uninstall

    do_uninstall(
        package_name=package_name,
        more_packages=more_packages,
        three=three,
        python=python,
        system=system,
        lock=lock,
        all_dev=all_dev,
        all=all,
        verbose=verbose,
        keep_outdated=keep_outdated,
        pypi_mirror=pypi_mirror,
    )


@command(short_help="Generates Pipfile.lock.")
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option(
    '--requirements',
    '-r',
    is_flag=True,
    default=False,
    help="Generate output compatible with requirements.txt.",
)
@option(
    '--dev',
    '-d',
    is_flag=True,
    default=False,
    help="Generate output compatible with requirements.txt for the development dependencies.",
)
@option(
    '--clear', is_flag=True, default=False, help="Clear the dependency cache."
)
@option(
    '--pre', is_flag=True, default=False, help=u"Allow pre-releases."
)
@option(
    '--keep-outdated',
    is_flag=True,
    default=False,
    help=u"Keep out-dated dependencies from being updated in Pipfile.lock.",
)
def lock(
    three=None,
    python=False,
    pypi_mirror=None,
    verbose=False,
    requirements=False,
    dev=False,
    clear=False,
    pre=False,
    keep_outdated=False,
):
    from .core import ensure_project, do_init, do_lock

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, pypi_mirror=pypi_mirror)
    if requirements:
        do_init(dev=dev, requirements=requirements, pypi_mirror=pypi_mirror)
    do_lock(
        verbose=verbose, clear=clear, pre=pre, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror
    )


@command(
    short_help="Spawns a shell within the virtualenv.",
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True),
)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--fancy',
    is_flag=True,
    default=False,
    help="Run in shell in fancy mode (for elegantly configured shells).",
)
@option(
    '--anyway',
    is_flag=True,
    default=False,
    help="Always spawn a subshell, even if one is already spawned.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@argument('shell_args', nargs=-1)
def shell(
    three=None, python=False, fancy=False, shell_args=None, anyway=False, pypi_mirror=None
):
    from .core import load_dot_env, do_shell
    # Prevent user from activating nested environments.
    if 'PIPENV_ACTIVE' in os.environ:
        # If PIPENV_ACTIVE is set, VIRTUAL_ENV should always be set too.
        venv_name = os.environ.get(
            'VIRTUAL_ENV', 'UNKNOWN_VIRTUAL_ENVIRONMENT'
        )
        if not anyway:
            echo(
                '{0} {1} {2}\nNo action taken to avoid nested environments.'.format(
                    crayons.normal('Shell for'),
                    crayons.green(venv_name, bold=True),
                    crayons.normal('already activated.', bold=True),
                ),
                err=True,
            )
            sys.exit(1)
    # Load .env file.
    load_dot_env()
    # Use fancy mode for Windows.
    if os.name == 'nt':
        fancy = True
    do_shell(
        three=three, python=python, fancy=fancy, shell_args=shell_args, pypi_mirror=pypi_mirror
    )


@command(
    add_help_option=False,
    short_help="Spawns a command installed into the virtualenv.",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
        allow_extra_args=True,
    ),
)
@argument('command')
@argument('args', nargs=-1)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
def run(command, args, three=None, python=False, pypi_mirror=None):
    from .core import do_run
    do_run(command=command, args=args, three=three, python=python, pypi_mirror=pypi_mirror)


@command(
    short_help="Checks for security vulnerabilities and against PEP 508 markers provided in Pipfile.",
    context_settings=dict(ignore_unknown_options=True, allow_extra_args=True),
)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--system', is_flag=True, default=False, help="Use system Python."
)
@option(
    '--unused',
    nargs=1,
    default=False,
    help="Given a code path, show potentially unused dependencies.",
)
@option(
    '--ignore',
    '-i',
    multiple=True,
    help="Ignore specified vulnerability during safety checks."
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@argument('args', nargs=-1)
def check(
    three=None,
    python=False,
    system=False,
    unused=False,
    style=False,
    ignore=None,
    args=None,
    pypi_mirror=None,
):
    from .core import do_check
    do_check(
        three=three,
        python=python,
        system=system,
        unused=unused,
        ignore=ignore,
        args=args,
        pypi_mirror=pypi_mirror
    )


@command(short_help="Runs lock, then sync.")
@argument('more_packages', nargs=-1)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option(
    '--dev',
    '-d',
    is_flag=True,
    default=False,
    help="Install package(s) in [dev-packages].",
)
@option(
    '--clear', is_flag=True, default=False, help="Clear the dependency cache."
)
@option('--bare', is_flag=True, default=False, help="Minimal output.")
@option(
    '--pre', is_flag=True, default=False, help=u"Allow pre-releases."
)
@option(
    '--keep-outdated',
    is_flag=True,
    default=False,
    help=u"Keep out-dated dependencies from being updated in Pipfile.lock.",
)
@option(
    '--sequential',
    is_flag=True,
    default=False,
    help="Install dependencies one-at-a-time, instead of concurrently.",
)
@option(
    '--outdated',
    is_flag=True,
    default=False,
    help=u"List out-of-date dependencies.",
)
@option(
    '--dry-run',
    is_flag=True,
    default=None,
    help=u"List out-of-date dependencies.",
)
@argument('package', default=False)
@pass_context
def update(
    ctx,
    three=None,
    python=False,
    pypi_mirror=None,
    system=False,
    verbose=False,
    clear=False,
    keep_outdated=False,
    pre=False,
    dev=False,
    bare=False,
    sequential=False,
    package=None,
    dry_run=None,
    outdated=False,
    more_packages=None,
):
    from .core import (
        ensure_project,
        do_outdated,
        do_lock,
        do_sync,
        ensure_lockfile,
        do_install,
        project,
    )

    ensure_project(three=three, python=python, warn=True, pypi_mirror=pypi_mirror)
    if not outdated:
        outdated = bool(dry_run)
    if outdated:
        do_outdated(pypi_mirror=pypi_mirror)
    if not package:
        echo(
            '{0} {1} {2} {3}{4}'.format(
                crayons.white('Running', bold=True),
                crayons.red('$ pipenv lock', bold=True),
                crayons.white('then', bold=True),
                crayons.red('$ pipenv sync', bold=True),
                crayons.white('.', bold=True),
            )
        )
    else:
        for package in ([package] + list(more_packages) or []):
            if package not in project.all_packages:
                echo(
                    '{0}: {1} was not found in your Pipfile! Aborting.'
                    ''.format(
                        crayons.red('Warning', bold=True),
                        crayons.green(package, bold=True),
                    ),
                    err=True,
                )
                sys.exit(1)
    do_lock(
        verbose=verbose, clear=clear, pre=pre, keep_outdated=keep_outdated, pypi_mirror=pypi_mirror
    )
    do_sync(
        ctx=ctx,
        dev=dev,
        three=three,
        python=python,
        bare=bare,
        dont_upgrade=False,
        user=False,
        verbose=verbose,
        clear=clear,
        unused=False,
        sequential=sequential,
        pypi_mirror=pypi_mirror,
    )


@command(
    short_help=u"Displays currently-installed dependency graph information."
)
@option('--bare', is_flag=True, default=False, help="Minimal output.")
@option('--json', is_flag=True, default=False, help="Output JSON.")
@option('--json-tree', is_flag=True, default=False, help="Output JSON in nested tree.")
@option(
    '--reverse', is_flag=True, default=False, help="Reversed dependency graph."
)
def graph(bare=False, json=False, json_tree=False, reverse=False):
    from .core import do_graph

    do_graph(bare=bare, json=json, json_tree=json_tree, reverse=reverse)


@command(short_help="View a given module in your editor.", name="open")
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@argument('module', nargs=1)
def run_open(module, three=None, python=None, pypi_mirror=None):
    from .core import which, ensure_project

    # Ensure that virtualenv is available.
    ensure_project(three=three, python=python, validate=False, pypi_mirror=pypi_mirror)
    c = delegator.run(
        '{0} -c "import {1}; print({1}.__file__);"'.format(
            which('python'), module
        )
    )
    try:
        assert c.return_code == 0
    except AssertionError:
        echo(crayons.red('Module not found!'))
        sys.exit(1)
    if '__init__.py' in c.out:
        p = os.path.dirname(c.out.strip().rstrip('cdo'))
    else:
        p = c.out.strip().rstrip('cdo')
    echo(
        crayons.normal('Opening {0!r} in your EDITOR.'.format(p), bold=True)
    )
    edit(filename=p)
    sys.exit(0)


@command(short_help="Installs all packages specified in Pipfile.lock.")
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option(
    '--dev',
    '-d',
    is_flag=True,
    default=False,
    help="Additionally install package(s) in [dev-packages].",
)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--pypi-mirror',
    default=environments.PIPENV_PYPI_MIRROR,
    nargs=1,
    callback=validate_pypi_mirror,
    help="Specify a PyPI mirror.",
)
@option('--bare', is_flag=True, default=False, help="Minimal output.")
@option(
    '--clear', is_flag=True, default=False, help="Clear the dependency cache."
)
@option(
    '--sequential',
    is_flag=True,
    default=False,
    help="Install dependencies one-at-a-time, instead of concurrently.",
)
@pass_context
def sync(
    ctx,
    dev=False,
    three=None,
    python=None,
    bare=False,
    dont_upgrade=False,
    user=False,
    verbose=False,
    clear=False,
    unused=False,
    package_name=None,
    sequential=False,
    pypi_mirror=None,
):
    from .core import do_sync

    do_sync(
        ctx=ctx,
        dev=dev,
        three=three,
        python=python,
        bare=bare,
        dont_upgrade=dont_upgrade,
        user=user,
        verbose=verbose,
        clear=clear,
        unused=unused,
        sequential=sequential,
        pypi_mirror=pypi_mirror,
    )


@command(
    short_help="Uninstalls all packages not specified in Pipfile.lock."
)
@option(
    '--verbose',
    '-v',
    is_flag=True,
    default=False,
    help="Verbose mode.",
    callback=setup_verbose,
)
@option(
    '--three/--two',
    is_flag=True,
    default=None,
    help="Use Python 3/2 when creating virtualenv.",
)
@option(
    '--python',
    default=False,
    nargs=1,
    callback=validate_python_path,
    help="Specify which version of Python virtualenv should use.",
)
@option(
    '--dry-run',
    is_flag=True,
    default=False,
    help="Just output unneeded packages.",
)
@pass_context
def clean(
    ctx,
    three=None,
    python=None,
    dry_run=False,
    bare=False,
    user=False,
    verbose=False,
):
    from .core import do_clean

    do_clean(
        ctx=ctx, three=three, python=python, dry_run=dry_run, verbose=verbose
    )


# Install click commands.
cli.add_command(graph)
cli.add_command(install)
cli.add_command(uninstall)
cli.add_command(sync)
cli.add_command(lock)
cli.add_command(check)
cli.add_command(clean)
cli.add_command(shell)
cli.add_command(run)
cli.add_command(update)
cli.add_command(run_open)
# Only invoke the "did you mean" when an argument wasn't passed (it breaks those).
if '-' not in ''.join(sys.argv) and len(sys.argv) > 1:
    cli = DYMCommandCollection(sources=[cli])
if __name__ == '__main__':
    cli()
