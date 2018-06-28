# -*- coding=utf-8 -*-
import os
import sys
import tempfile

from pipenv.patched import crayons
from pipenv.vendor import click, requirementslib

from pipenv._compat import TemporaryDirectory
from pipenv.core import project
from pipenv.environments import PIPENV_USE_SYSTEM
from pipenv.utils import (
    download_file,
    is_star,
    is_valid_url,
)

from ._install import (
    format_pip_error,
    format_pip_output,
    pip_install,
    split_argument,
)
from ._utils import convert_deps_to_pip, import_from_code, spinner
from .ensure import ensure_project, import_requirements
from .init import do_init


def do_install(
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
    from notpip._internal.exceptions import PipError

    requirements_directory = TemporaryDirectory(
        suffix='-requirements', prefix='pipenv-'
    )
    if selective_upgrade:
        keep_outdated = True
    more_packages = more_packages or []
    # Don't search for requirements.txt files if the user provides one
    if requirements or package_name or project.pipfile_exists:
        skip_requirements = True
    else:
        skip_requirements = False
    concurrent = (not sequential)
    # Ensure that virtualenv is available.
    ensure_project(
        three=three,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=skip_requirements,
    )
    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = project.settings.get('allow_prereleases')
    if not keep_outdated:
        keep_outdated = project.settings.get('keep_outdated')
    remote = requirements and is_valid_url(requirements)
    # Warn and exit if --system is used without a pipfile.
    global PIPENV_VIRTUALENV
    if system and package_name and not PIPENV_VIRTUALENV:
        click.echo(
            '{0}: --system is intended to be used for Pipfile installation, '
            'not installation of specific packages. Aborting.'.format(
                crayons.red('Warning', bold=True)
            ),
            err=True,
        )
        click.echo('See also: --deploy flag.', err=True)
        requirements_directory.cleanup()
        sys.exit(1)
    # Automatically use an activated virtualenv.
    if PIPENV_USE_SYSTEM:
        system = True
    # Check if the file is remote or not
    if remote:
        fd, temp_reqs = tempfile.mkstemp(
            prefix='pipenv-',
            suffix='-requirement.txt',
            dir=requirements_directory.name,
        )
        requirements_url = requirements
        # Download requirements file
        click.echo(
            crayons.normal(
                u'Remote requirements file provided! Downloading...', bold=True
            ),
            err=True,
        )
        try:
            download_file(requirements, temp_reqs)
        except IOError:
            click.echo(
                crayons.red(
                    u'Unable to find requirements file at {0}.'.format(
                        crayons.normal(requirements)
                    )
                ),
                err=True,
            )
            requirements_directory.cleanup()
            sys.exit(1)
        # Replace the url with the temporary requirements file
        requirements = temp_reqs
        remote = True
    if requirements:
        error, traceback = None, None
        click.echo(
            crayons.normal(
                u'Requirements file provided! Importing into Pipfile...',
                bold=True,
            ),
            err=True,
        )
        try:
            import_requirements(r=project.path_to(requirements), dev=dev)
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(
                requirements
            )
            error = (
                u'Unexpected syntax in {0}. Are you sure this is a '
                'requirements.txt style file?'.format(req_path)
            )
            traceback = e
        except AssertionError as e:
            error = (
                u'Requirements file doesn\'t appear to exist. Please ensure the file exists in your '
                'project directory or you provided the correct path.'
            )
            traceback = e
        finally:
            # If requirements file was provided by remote url delete the temporary file
            if remote:
                os.close(fd)  # Close for windows to allow file cleanup.
                os.remove(project.path_to(temp_reqs))
            if error and traceback:
                click.echo(crayons.red(error))
                click.echo(crayons.blue(str(traceback)), err=True)
                requirements_directory.cleanup()
                sys.exit(1)
    if code:
        click.echo(
            crayons.normal(
                u'Discovering imports from local codebase...', bold=True
            )
        )
        for req in import_from_code(code):
            click.echo('  Found {0}!'.format(crayons.green(req)))
            project.add_package_to_pipfile(req)
    # Capture -e argument and assign it to following package_name.
    more_packages = list(more_packages)
    if package_name == '-e':
        if not more_packages:
            raise click.BadArgumentUsage('Please provide path to editable package')
        package_name = ' '.join([package_name, more_packages.pop(0)])
    # capture indexes and extra indexes
    line = [package_name] + more_packages
    line = ' '.join(str(s) for s in line).strip()
    index_indicators = ['-i', '--index', '--extra-index-url']
    index, extra_indexes = None, None
    if any(line.endswith(s) for s in index_indicators):
        # check if cli option is not end of command
        raise click.BadArgumentUsage('Please provide index value')
    if any(s in line for s in index_indicators):
        line, index = split_argument(line, short='i', long_='index', num=1)
        line, extra_indexes = split_argument(line, long_='extra-index-url')
        package_names = line.split()
        package_name = package_names[0]
        if len(package_names) > 1:
            more_packages = package_names[1:]
        else:
            more_packages = []
    # Capture . argument and assign it to nothing
    if package_name == '.':
        package_name = False
    # Install editable local packages before locking - this gives us access to dist-info
    if project.pipfile_exists and (
        # double negatives are for english readability, leave them alone.
        (not project.lockfile_exists and not deploy) or (not project.virtualenv_exists and not system)
    ):
        section = project.editable_packages if not dev else project.editable_dev_packages
        for package in section.keys():
            converted = convert_deps_to_pip(
                {package: section[package]}, project=project, r=False
            )
            if not package_name:
                if converted:
                    package_name = converted.pop(0)
            if converted:
                more_packages.extend(converted)
    # Allow more than one package to be provided.
    package_names = [package_name] + more_packages
    # Support for --selective-upgrade.
    # We should do this part first to make sure that we actually do selectively upgrade
    # the items specified
    if selective_upgrade:
        for i, package_name in enumerate(package_names[:]):
            section = project.packages if not dev else project.dev_packages
            package = requirementslib.Requirement.from_line(package_name)
            package__name, package__val = package.pipfile_entry
            try:
                if not is_star(section[package__name]) and is_star(
                    package__val
                ):
                    # Support for VCS dependencies.
                    package_names[i] = convert_deps_to_pip(
                        {package_name: section[package__name]},
                        project=project,
                        r=False,
                    )[
                        0
                    ]
            except KeyError:
                pass
    # Install all dependencies, if none was provided.
    # This basically ensures that we have a pipfile and lockfile, then it locks and
    # installs from the lockfile
    if package_name is False:
        # Update project settings with pre preference.
        if pre:
            project.update_settings({'allow_prereleases': pre})
        do_init(
            dev=dev,
            allow_global=system,
            ignore_pipfile=ignore_pipfile,
            system=system,
            skip_lock=skip_lock,
            verbose=verbose,
            concurrent=concurrent,
            deploy=deploy,
            pre=pre,
            requirements_dir=requirements_directory,
            pypi_mirror=pypi_mirror,
        )

    # This is for if the user passed in dependencies, then we want to maek sure we
    else:
        for package_name in package_names:
            click.echo(
                crayons.normal(
                    u'Installing {0}...'.format(
                        crayons.green(package_name, bold=True)
                    ),
                    bold=True,
                )
            )
            # pip install:
            with spinner():
                c = pip_install(
                    package_name,
                    ignore_hashes=True,
                    allow_global=system,
                    selective_upgrade=selective_upgrade,
                    no_deps=False,
                    verbose=verbose,
                    pre=pre,
                    requirements_dir=requirements_directory.name,
                    index=index,
                    extra_indexes=extra_indexes,
                    pypi_mirror=pypi_mirror,
                )
                # Warn if --editable wasn't passed.
                try:
                    converted = requirementslib.Requirement.from_line(package_name)
                except ValueError as e:
                    click.echo('{0}: {1}'.format(crayons.red('WARNING'), e))
                    requirements_directory.cleanup()
                    sys.exit(1)
                if converted.is_vcs and not converted.editable:
                    click.echo(
                        '{0}: You installed a VCS dependency in non-editable mode. '
                        'This will work fine, but sub-dependencies will not be resolved by {1}.'
                        '\n  To enable this sub-dependency functionality, specify that this dependency is editable.'
                        ''.format(
                            crayons.red('Warning', bold=True),
                            crayons.red('$ pipenv lock'),
                        )
                    )
            click.echo(crayons.blue(format_pip_output(c.out)))
            # Ensure that package was successfully installed.
            try:
                assert c.return_code == 0
            except AssertionError:
                click.echo(
                    '{0} An error occurred while installing {1}!'.format(
                        crayons.red('Error: ', bold=True),
                        crayons.green(package_name),
                    ),
                    err=True,
                )
                click.echo(crayons.blue(format_pip_error(c.err)), err=True)
                if 'setup.py egg_info' in c.err:
                    click.echo(
                        "This is likely caused by a bug in {0}. "
                        "Report this to its maintainers.".format(
                            crayons.green(package_name),
                        ),
                        err=True,
                    )
                requirements_directory.cleanup()
                sys.exit(1)
            click.echo(
                '{0} {1} {2} {3}{4}'.format(
                    crayons.normal('Adding', bold=True),
                    crayons.green(package_name, bold=True),
                    crayons.normal("to Pipfile's", bold=True),
                    crayons.red(
                        '[dev-packages]' if dev else '[packages]', bold=True
                    ),
                    crayons.normal('...', bold=True),
                )
            )
            # Add the package to the Pipfile.
            try:
                project.add_package_to_pipfile(package_name, dev)
            except ValueError as e:
                click.echo(
                    '{0} {1}'.format(
                        crayons.red('ERROR (PACKAGE NOT INSTALLED):'), e
                    )
                )
            # Update project settings with pre preference.
            if pre:
                project.update_settings({'allow_prereleases': pre})
        do_init(
            dev=dev,
            system=system,
            allow_global=system,
            concurrent=concurrent,
            verbose=verbose,
            keep_outdated=keep_outdated,
            requirements_dir=requirements_directory,
            deploy=deploy,
            pypi_mirror=pypi_mirror,
            skip_lock=skip_lock
        )
    requirements_directory.cleanup()
    sys.exit(0)
