import os
import sys

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from pipenv.patched import crayons
from pipenv.vendor import click, delegator, six

from pipenv.core import project, which, which_pip
from pipenv.utils import (
    escape_grouped_arguments,
    pep423_name,
    temp_environ,
)

from ._utils import convert_deps_to_pip


def _is_pinned(val):
    if isinstance(val, Mapping):
        val = val.get('version')
    return isinstance(val, six.string_types) and val.startswith('==')


def _venv_resolve_deps(
    deps, which, project, pre=False, verbose=False, clear=False,
    allow_global=False, pypi_mirror=None,
):
    from .vendor import delegator
    from . import resolver
    import json
    if not deps:
        return []
    resolver = escape_grouped_arguments(resolver.__file__.rstrip('co'))
    cmd = '{0} {1} {2} {3} {4} {5}'.format(
        escape_grouped_arguments(which('python', allow_global=allow_global)),
        resolver,
        '--pre' if pre else '',
        '--verbose' if verbose else '',
        '--clear' if clear else '',
        '--system' if allow_global else '',
    )
    with temp_environ():
        os.environ['PIPENV_PACKAGES'] = '\n'.join(deps)
        if pypi_mirror:
            os.environ['PIPENV_PYPI_MIRROR'] = str(pypi_mirror)
        c = delegator.run(cmd, block=True)
    try:
        assert c.return_code == 0
    except AssertionError:
        if verbose:
            click.echo(c.out, err=True)
            click.echo(c.err, err=True)
        else:
            click.echo(c.err[int(len(c.err) / 2) - 1:], err=True)
        sys.exit(c.return_code)
    if verbose:
        click.echo(c.out.split('RESULTS:')[0], err=True)
    try:
        return json.loads(c.out.split('RESULTS:')[1].strip())

    except IndexError:
        raise RuntimeError('There was a problem with locking.')


def _translate_markers(pipfile_entry):
    """Take a pipfile entry and normalize its markers

    Provide a pipfile entry which may have 'markers' as a key or it may have
    any valid key from `packaging.markers.marker_context.keys()` and standardize
    the format into {'markers': 'key == "some_value"'}.

    :param pipfile_entry: A dictionariy of keys and values representing a pipfile entry
    :type pipfile_entry: dict
    :returns: A normalized dictionary with cleaned marker entries
    """
    if not isinstance(pipfile_entry, Mapping):
        raise TypeError('Entry is not a pipfile formatted mapping.')
    from notpip._vendor.distlib.markers import DEFAULT_CONTEXT as marker_context
    allowed_marker_keys = ['markers'] + [k for k in marker_context.keys()]
    provided_keys = list(pipfile_entry.keys()) if hasattr(pipfile_entry, 'keys') else []
    pipfile_marker = next((k for k in provided_keys if k in allowed_marker_keys), None)
    new_pipfile = dict(pipfile_entry).copy()
    if pipfile_marker:
        entry = "{0}".format(pipfile_entry[pipfile_marker])
        if pipfile_marker != 'markers':
            entry = "{0} {1}".format(pipfile_marker, entry)
            new_pipfile.pop(pipfile_marker)
        new_pipfile['markers'] = entry
    return new_pipfile


def _clean_resolved_dep(dep, is_top_level=False, pipfile_entry=None):
    name = pep423_name(dep['name'])
    # We use this to determine if there are any markers on top level packages
    # So we can make sure those win out during resolution if the packages reoccur
    lockfile = {
        'version': '=={0}'.format(dep['version']),
    }
    for key in ['hashes', 'index', 'extras']:
        if key in dep:
            lockfile[key] = dep[key]
    # In case we lock a uri or a file when the user supplied a path
    # remove the uri or file keys from the entry and keep the path
    if pipfile_entry and any(k in pipfile_entry for k in ['file', 'path']):
        fs_key = next((k for k in ['path', 'file'] if k in pipfile_entry), None)
        lockfile_key = next((k for k in ['uri', 'file', 'path'] if k in lockfile), None)
        if fs_key != lockfile_key:
            try:
                del lockfile[lockfile_key]
            except KeyError:
                # pass when there is no lock file, usually because it's the first time
                pass
            lockfile[fs_key] = pipfile_entry[fs_key]

    # If a package is **PRESENT** in the pipfile but has no markers, make sure we
    # **NEVER** include markers in the lockfile
    if 'markers' in dep:
        # First, handle the case where there is no top level dependency in the pipfile
        if not is_top_level:
            try:
                lockfile['markers'] = _translate_markers(dep)['markers']
            except TypeError:
                pass
        # otherwise make sure we are prioritizing whatever the pipfile says about the markers
        # If the pipfile says nothing, then we should put nothing in the lockfile
        else:
            try:
                pipfile_entry = _translate_markers(pipfile_entry)
                lockfile['markers'] = pipfile_entry.get('markers')
            except TypeError:
                pass
    return {name: lockfile}


def do_lock(
    verbose=False,
    system=False,
    clear=False,
    pre=False,
    keep_outdated=False,
    write=True,
    pypi_mirror=None,
):
    """Executes the freeze functionality."""
    from .utils import get_vcs_deps
    cached_lockfile = {}
    if not pre:
        pre = project.settings.get('allow_prereleases')
    if keep_outdated:
        if not project.lockfile_exists:
            click.echo(
                '{0}: Pipfile.lock must exist to use --keep-outdated!'.format(
                    crayons.red('Warning', bold=True)
                )
            )
            sys.exit(1)
        cached_lockfile = project.lockfile_content
    # Create the lockfile.
    lockfile = project._lockfile
    # Cleanup lockfile.
    for section in ('default', 'develop'):
        for k, v in lockfile[section].copy().items():
            if not hasattr(v, 'keys'):
                del lockfile[section][k]
    # Ensure that develop inherits from default.
    dev_packages = project.dev_packages.copy()
    for dev_package in project.dev_packages:
        if dev_package in project.packages:
            dev_packages[dev_package] = project.packages[dev_package]
    # Resolve dev-package dependencies, with pip-tools.
    pip_freeze = delegator.run(
        '{0} freeze'.format(escape_grouped_arguments(which_pip(allow_global=system)))
    ).out
    sections = {
        'dev': {
            'packages': project.dev_packages,
            'vcs': project.vcs_dev_packages,
            'pipfile_key': 'dev_packages',
            'lockfile_key': 'develop',
            'log_string': 'dev-packages',
            'dev': True
        },
        'default': {
            'packages': project.packages,
            'vcs': project.vcs_packages,
            'pipfile_key': 'packages',
            'lockfile_key': 'default',
            'log_string': 'packages',
            'dev': False
        }
    }
    for section_name in ['dev', 'default']:
        settings = sections[section_name]
        if write:
            # Alert the user of progress.
            click.echo(
                u'{0} {1} {2}'.format(
                    crayons.normal('Locking'),
                    crayons.red('[{0}]'.format(settings['log_string'])),
                    crayons.normal('dependencies...'),
                ),
                err=True,
            )

        deps = convert_deps_to_pip(
            settings['packages'], project, r=False, include_index=True
        )
        results = _venv_resolve_deps(
            deps,
            which=which,
            verbose=verbose,
            project=project,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
        )
        # Add dependencies to lockfile.
        for dep in results:
            is_top_level = dep['name'] in settings['packages']
            pipfile_entry = settings['packages'][dep['name']] if is_top_level else None
            dep_lockfile = _clean_resolved_dep(dep, is_top_level=is_top_level, pipfile_entry=pipfile_entry)
            lockfile[settings['lockfile_key']].update(dep_lockfile)
        # Add refs for VCS installs.
        # TODO: be smarter about this.
        vcs_reqs, vcs_lockfile = get_vcs_deps(
            project,
            pip_freeze,
            which=which,
            verbose=verbose,
            clear=clear,
            pre=pre,
            allow_global=system,
            dev=settings['dev']
        )
        vcs_lines = [req.as_line() for req in vcs_reqs if req.editable]
        vcs_results = _venv_resolve_deps(
            vcs_lines,
            which=which,
            verbose=verbose,
            project=project,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
        )
        for dep in vcs_results:
            normalized = pep423_name(dep['name'])
            if not hasattr(dep, 'keys') or not hasattr(dep['name'], 'keys'):
                continue
            is_top_level = (
                dep['name'] in vcs_lockfile or
                normalized in vcs_lockfile
            )
            if is_top_level:
                try:
                    pipfile_entry = vcs_lockfile[dep['name']]
                except KeyError:
                    pipfile_entry = vcs_lockfile[normalized]
            else:
                pipfile_entry = None
            dep_lockfile = _clean_resolved_dep(
                dep, is_top_level=is_top_level, pipfile_entry=pipfile_entry,
            )
            vcs_lockfile.update(dep_lockfile)
        lockfile[settings['lockfile_key']].update(vcs_lockfile)

    # Support for --keep-outdated...
    if keep_outdated:
        for section_name, section in (
            ('default', project.packages), ('develop', project.dev_packages)
        ):
            for package_specified in section:
                norm_name = pep423_name(package_specified)
                if not _is_pinned(section[package_specified]):
                    if norm_name in cached_lockfile[section_name]:
                        lockfile[section_name][norm_name] = cached_lockfile[
                            section_name
                        ][
                            norm_name
                        ]
    # Overwrite any develop packages with default packages.
    for default_package in lockfile['default']:
        if default_package in lockfile['develop']:
            lockfile['develop'][default_package] = lockfile['default'][
                default_package
            ]
    if write:
        project.write_lockfile(lockfile)
        click.echo(
            '{0}'.format(
                crayons.normal(
                    'Updated Pipfile.lock ({0})!'.format(
                        lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
                    ),
                    bold=True,
                )
            ),
            err=True,
        )
    else:
        return lockfile
