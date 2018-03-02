# -*- coding: utf-8 -*-

import logging
import os
import sys

import click
import click_completion
import crayons
import delegator
from click_didyoumean import DYMCommandCollection

from .__version__ import __version__

from . import environments
from .environments import *

# Enable shell completion.
click_completion.init()

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

def setup_verbose(ctx, param, value):
    if value:
        logging.getLogger('pip').setLevel(logging.INFO)
    return value


@click.group(invoke_without_command=True, context_settings=CONTEXT_SETTINGS)
@click.option('--update', is_flag=True, default=False, help="Update Pipenv & pip to latest.")
@click.option('--where', is_flag=True, default=False, help="Output project home information.")
@click.option('--venv', is_flag=True, default=False, help="Output virtualenv information.")
@click.option('--py', is_flag=True, default=False, help="Output Python interpreter information.")
@click.option('--envs', is_flag=True, default=False, help="Output Environment Variable options.")
@click.option('--rm', is_flag=True, default=False, help="Remove the virtualenv.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--completion', is_flag=True, default=False, help="Output completion (to be eval'd).")
@click.option('--man', is_flag=True, default=False, help="Display manpage.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--site-packages', is_flag=True, default=False, help="Enable site-packages for the virtualenv.")
@click.version_option(prog_name=crayons.normal('pipenv', bold=True), version=__version__)
@click.pass_context
def cli(
    ctx, where=False, venv=False, rm=False, bare=False, three=False,
    python=False, help=False, update=False, py=False,
    site_packages=False, envs=False, man=False, completion=False
):
    from . import core

    if not update:
        if core.need_update_check():
            # Spun off in background thread, not unlike magic.
            core.check_for_updates()
    else:
        # Update pip to latest version.
        core.ensure_latest_pip()

        # Upgrade self to latest version.
        core.ensure_latest_self()

        sys.exit()

    if completion:
        if PIPENV_SHELL:
            os.environ['_PIPENV_COMPLETE'] = 'source-{0}'.format(PIPENV_SHELL.split(os.sep)[-1])
        else:
            click.echo(
                'Please ensure that the {0} environment variable '
                'is set.'.format(crayons.normal('SHELL', bold=True)), err=True)
            sys.exit(1)

        c = delegator.run('pipenv')
        click.echo(c.out)
        sys.exit(0)

    if man:
        if core.system_which('man'):
            path = os.sep.join([os.path.dirname(__file__), 'pipenv.1'])
            os.execle(core.system_which('man'), 'man', path, os.environ)
        else:
            click.echo('man does not appear to be available on your system.', err=True)

    if envs:
        click.echo('The following environment variables can be set, to do various things:\n')
        for key in environments.__dict__:
            if key.startswith('PIPENV'):
                click.echo('  - {0}'.format(crayons.normal(key, bold=True)))

        click.echo('\nYou can learn more at:\n   {0}'.format(
            crayons.green('http://docs.pipenv.org/advanced/#configuration-with-environment-variables')
        ))
        sys.exit(0)

    core.warn_in_virtualenv()

    if ctx.invoked_subcommand is None:
        # --where was passed...
        if where:
            core.do_where(bare=True)
            sys.exit(0)

        elif py:
            core.do_py()
            sys.exit()

        # --venv was passed...
        elif venv:
            # There is no virtualenv yet.
            if not core.project.virtualenv_exists:
                click.echo(crayons.red('No virtualenv has been created for this project yet!'), err=True)
                sys.exit(1)
            else:
                click.echo(core.project.virtualenv_location)
                sys.exit(0)

        # --rm was passed...
        elif rm:
            # Abort if --system (or running in a virtualenv).
            if PIPENV_USE_SYSTEM:
                click.echo(
                    crayons.red(
                        'You are attempting to remove a virtualenv that '
                        'Pipenv did not create. Aborting.'
                    )
                )
                sys.exit(1)
            if core.project.virtualenv_exists:
                loc = core.project.virtualenv_location
                click.echo(
                    crayons.normal(
                        u'{0} ({1})…'.format(
                            crayons.normal('Removing virtualenv', bold=True),
                            crayons.green(loc)
                        )
                    )
                )

                with core.spinner():
                    # Remove the virtualenv.
                    core.cleanup_virtualenv(bare=True)
                sys.exit(0)
            else:
                click.echo(
                    crayons.red(
                        'No virtualenv has been created for this project yet!',
                        bold=True
                    ), err=True
                )
                sys.exit(1)

    # --two / --three was passed...
    if (python or three is not None) or site_packages:
        core.ensure_project(three=three, python=python, warn=True, site_packages=site_packages)

    # Check this again before exiting for empty ``pipenv`` command.
    elif ctx.invoked_subcommand is None:
        # Display help to user, if no commands were passed.
        click.echo(core.format_help(ctx.get_help()))



@click.command(short_help="Installs provided packages and adds them to Pipfile, or (if none is given), installs all packages.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--requirements', '-r', nargs=1, default=False, help="Import a requirements.txt file.")
@click.option('--code', '-c', nargs=1, default=False, help="Import from codebase.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--ignore-pipfile', is_flag=True, default=False, help="Ignore Pipfile when installing, using the Pipfile.lock.")
@click.option('--sequential', is_flag=True, default=False, help="Install dependencies one-at-a-time, instead of concurrently.")
@click.option('--skip-lock', is_flag=True, default=False, help=u"Ignore locking mechanisms when installing—use the Pipfile, instead.")
@click.option('--deploy', is_flag=True, default=False, help=u"Abort if the Pipfile.lock is out–of–date, or Python version is wrong.")
@click.option('--pre', is_flag=True, default=False, help=u"Allow pre–releases.")
@click.option('--keep-outdated', is_flag=True, default=False, help=u"Keep out–dated dependencies from being updated in Pipfile.lock.")
@click.option('--selective-upgrade', is_flag=True, default=False, help="Update specified packages.")
def install(
    package_name=False, more_packages=False, dev=False, three=False,
    python=False, system=False, lock=True, ignore_pipfile=False,
    skip_lock=False, verbose=False, requirements=False, sequential=False,
    pre=False, code=False, deploy=False, keep_outdated=False,
    selective_upgrade=False
):
    from . import core
    core.do_install(
        package_name=package_name, more_packages=more_packages, dev=dev,
        three=three, python=python, system=system, lock=lock,
        ignore_pipfile=ignore_pipfile, skip_lock=skip_lock, verbose=verbose,
        requirements=requirements, sequential=sequential, pre=pre, code=code,
        deploy=deploy, keep_outdated=keep_outdated,
        selective_upgrade=selective_upgrade
    )


@click.command(short_help="Un-installs a provided package and removes it from Pipfile.")
@click.argument('package_name', default=False)
@click.argument('more_packages', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="System pip management.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--lock', is_flag=True, default=True, help="Lock afterwards.")
@click.option('--all-dev', is_flag=True, default=False, help="Un-install all package from [dev-packages].")
@click.option('--all', is_flag=True, default=False, help="Purge all package(s) from virtualenv. Does not edit Pipfile.")
@click.option('--keep-outdated', is_flag=True, default=False, help=u"Keep out–dated dependencies from being updated in Pipfile.lock.")
def uninstall(
    package_name=False, more_packages=False, three=None, python=False,
    system=False, lock=False, all_dev=False, all=False, verbose=False,
    keep_outdated=False
):
    from . import core
    core.do_uninstall(
        package_name=package_name, more_packages=more_packages, three=three,
        python=python, system=system, lock=lock, all_dev=all_dev, all=all,
        verbose=verbose, keep_outdated=keep_outdated
    )



@click.command(short_help="Generates Pipfile.lock.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--requirements', '-r', is_flag=True, default=False, help="Generate output compatible with requirements.txt.")
@click.option('--dev', '-d', is_flag=True, default=False, help="Generate output compatible with requirements.txt for the development dependencies.")
@click.option('--clear', is_flag=True, default=False, help="Clear the dependency cache.")
@click.option('--pre', is_flag=True, default=False, help=u"Allow pre–releases.")
@click.option('--keep-outdated', is_flag=True, default=False, help=u"Keep out–dated dependencies from being updated in Pipfile.lock.")
def lock(three=None, python=False, verbose=False, requirements=False, dev=False, clear=False, pre=False, keep_outdated=False):
    from . import core
    # Ensure that virtualenv is available.
    core.ensure_project(three=three, python=python)

    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = core.project.settings.get('pre')

    if requirements:
        core.do_init(dev=dev, requirements=requirements)

    core.do_lock(verbose=verbose, clear=clear, pre=pre, keep_outdated=keep_outdated)



@click.command(short_help="Spawns a shell within the virtualenv.", context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--fancy', is_flag=True, default=False, help="Run in shell in fancy mode (for elegantly configured shells).")
@click.option('--anyway', is_flag=True, default=False, help="Always spawn a subshell, even if one is already spawned.")
@click.argument('shell_args', nargs=-1)
def shell(three=None, python=False, fancy=False, shell_args=None, anyway=False):
    from . import core
    # Prevent user from activating nested environments.
    if 'PIPENV_ACTIVE' in os.environ:
        # If PIPENV_ACTIVE is set, VIRTUAL_ENV should always be set too.
        venv_name = os.environ.get('VIRTUAL_ENV', 'UNKNOWN_VIRTUAL_ENVIRONMENT')

        if not anyway:
            click.echo('{0} {1} {2}\nNo action taken to avoid nested environments.'.format(
                crayons.normal('Shell for'),
                crayons.green(venv_name, bold=True),
                crayons.normal('already activated.', bold=True)
            ), err=True)

            sys.exit(1)

    # Load .env file.
    core.load_dot_env()

    # Use fancy mode for Windows.
    if os.name == 'nt':
        fancy = True

    core.do_shell(three=three, python=python, fancy=fancy, shell_args=shell_args)


@click.command(
    add_help_option=False,
    short_help="Spawns a command installed into the virtualenv.",
    context_settings=dict(
        ignore_unknown_options=True,
        allow_interspersed_args=False,
        allow_extra_args=True
    )
)
@click.argument('command')
@click.argument('args', nargs=-1)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
def run(command, args, three=None, python=False):
    from . import core
    core.do_run(command=command, args=args, three=three, python=python)


@click.command(short_help="Checks for security vulnerabilities and against PEP 508 markers provided in Pipfile.",  context_settings=dict(
    ignore_unknown_options=True,
    allow_extra_args=True
))
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--system', is_flag=True, default=False, help="Use system Python.")
@click.option('--unused', nargs=1, default=False, help="Given a code path, show potentially unused dependencies.")
@click.argument('args', nargs=-1)
def check(three=None, python=False, system=False, unused=False, style=False, args=None):
    from . import core
    core.do_check(three=three, python=python, system=system, unused=unused, args=args)


@click.command(short_help="Runs lock, then sync.")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--dev', '-d', is_flag=True, default=False, help="Install package(s) in [dev-packages].")
@click.option('--clear', is_flag=True, default=False, help="Clear the dependency cache.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--pre', is_flag=True, default=False, help=u"Allow pre–releases.")
@click.option('--keep-outdated', is_flag=True, default=False, help=u"Keep out–dated dependencies from being updated in Pipfile.lock.")
@click.option('--sequential', is_flag=True, default=False, help="Install dependencies one-at-a-time, instead of concurrently.")
@click.option('--outdated', is_flag=True, default=False, help=u"List out–of–date dependencies.")
@click.option('--dry-run', is_flag=True, default=None, help=u"List out–of–date dependencies.")
@click.argument('packages', nargs=-1)
@click.pass_context
def update(ctx, three=None, python=False, system=False, verbose=False, clear=False, keep_outdated=False, pre=False, dev=False, bare=False, sequential=False, packages=None, dry_run=None, outdated=False):
    from . import core

    core.ensure_project(three=three, python=python, warn=True)

    if not outdated:
        outdated = bool(dry_run)

    if outdated:
        core.do_outdated()

    if not packages:
        click.echo('{0} {1} {2} {3}{4}'.format(
            crayons.white('Running', bold=True),
            crayons.red('$ pipenv lock', bold=True),
            crayons.white('then', bold=True),
            crayons.red('$ pipenv sync', bold=True),
            crayons.white('.', bold=True),
        ))

        # Load the --pre settings from the Pipfile.
        if not pre:
            pre = core.project.settings.get('pre')

        core.do_lock(verbose=verbose, clear=clear, pre=pre, keep_outdated=keep_outdated)
        core.do_sync(
            ctx=ctx, install=install, dev=dev, three=three, python=python,
            bare=bare, dont_upgrade=False, user=False, verbose=verbose,
            clear=clear, unused=False, sequential=sequential
        )
    else:

        core.ensure_lockfile(keep_outdated=core.project.lockfile_exists)

        for package in packages:
            core.do_install(
                package_name=package, dev=dev,
                three=three, python=python, system=system, lock=True,
                ignore_pipfile=False, skip_lock=False, verbose=verbose,
                requirements=False, sequential=sequential, pre=pre, code=False,
                deploy=False, keep_outdated=True,
                selective_upgrade=True
            )




@click.command(short_help=u"Displays currently–installed dependency graph information.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--json', is_flag=True, default=False, help="Output JSON.")
@click.option('--reverse', is_flag=True, default=False, help="Reversed dependency graph.")
def graph(bare=False, json=False, reverse=False):
    from . import core
    core.do_graph(bare=bare, json=json, reverse=reverse)


@click.command(short_help="View a given module in your editor.", name="open")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.argument('module', nargs=1)
def run_open(module, three=None, python=None):
    from . import core
    # Ensure that virtualenv is available.
    core.ensure_project(three=three, python=python, validate=False)

    c = delegator.run('{0} -c "import {1}; print({1}.__file__);"'.format(core.which('python'), module))

    try:
        assert c.return_code == 0
    except AssertionError:
        click.echo(crayons.red('Module not found!'))
        sys.exit(1)

    if '__init__.py' in c.out:
        p = os.path.dirname(c.out.strip().rstrip('cdo'))
    else:
        p = c.out.strip().rstrip('cdo')

    click.echo(crayons.normal('Opening {0!r} in your EDITOR.'.format(p), bold=True))
    click.edit(filename=p)
    sys.exit(0)


@click.command(short_help="Installs all packages specified in Pipfile.lock.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--dev', '-d', is_flag=True, default=False, help="Additionally install package(s) in [dev-packages].")
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--bare', is_flag=True, default=False, help="Minimal output.")
@click.option('--clear', is_flag=True, default=False, help="Clear the dependency cache.")
@click.option('--sequential', is_flag=True, default=False, help="Install dependencies one-at-a-time, instead of concurrently.")
@click.pass_context
def sync(
    ctx, dev=False, three=None, python=None, bare=False,
    dont_upgrade=False, user=False, verbose=False, clear=False, unused=False,
    package_name=None, sequential=False
):
    from . import core
    core.do_sync(
        ctx=ctx, install=install, dev=dev, three=three, python=python,
        bare=bare, dont_upgrade=dont_upgrade, user=user, verbose=verbose,
        clear=clear, unused=unused, sequential=sequential
    )


@click.command(short_help="Uninstalls all packages not specified in Pipfile.lock.")
@click.option('--verbose', '-v', is_flag=True, default=False, help="Verbose mode.", callback=setup_verbose)
@click.option('--three/--two', is_flag=True, default=None, help="Use Python 3/2 when creating virtualenv.")
@click.option('--python', default=False, nargs=1, help="Specify which version of Python virtualenv should use.")
@click.option('--dry-run', is_flag=True, default=False, help="Just output unneeded packages.")
@click.pass_context
def clean(
    ctx, three=None, python=None, dry_run=False, bare=False,
    user=False, verbose=False
):
    from . import core
    core.do_clean(
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
