import json
import logging
import os
import re
import sys
import tempfile
import time

from pipenv.patched import crayons
from pipenv.vendor import click, delegator, requirementslib, six

from pipenv import progress
from pipenv._compat import Path
from pipenv.core import project, which_pip
from pipenv.environments import (
    PIPENV_CACHE_DIR,
    PIPENV_HIDE_EMOJIS,
    PIPENV_MAX_SUBPROCESS,
)
from pipenv.project import SourceNotFound
from pipenv.utils import (
    create_mirror_source,
    escape_grouped_arguments,
    fs_str,
    is_pypi_url,
    is_valid_url,
    prepare_pip_source_args,
    split_file,
)

from ._utils import convert_deps_to_pip


if not PIPENV_HIDE_EMOJIS:
    now = time.localtime()
    # Halloween easter-egg.
    if ((now.tm_mon == 10) and (now.tm_mday == 30)) or (
        (now.tm_mon == 10) and (now.tm_mday == 31)
    ):
        INSTALL_LABEL = '🎃   '
    # Christmas easter-egg.
    elif ((now.tm_mon == 12) and (now.tm_mday == 24)) or (
        (now.tm_mon == 12) and (now.tm_mday == 25)
    ):
        INSTALL_LABEL = '🎅   '
    else:
        INSTALL_LABEL = '🐍   '
    INSTALL_LABEL2 = crayons.normal('☤  ', bold=True)
    STARTING_LABEL = '    '
else:
    INSTALL_LABEL = '   '
    INSTALL_LABEL2 = '   '
    STARTING_LABEL = '   '


def _merge_deps(
    file_dict,
    project,
    dev=False,
    requirements=False,
    ignore_hashes=False,
    blocking=False,
    only=False,
):
    """
    Given a file_dict, merges dependencies and converts them to pip dependency lists.
        :param dict file_dict: The result of calling :func:`pipenv.utils.split_file`
        :param :class:`pipenv.project.Project` project: Pipenv project
        :param bool dev=False: Flag indicating whether dev dependencies are to be installed
        :param bool requirements=False: Flag indicating whether to use a requirements file
        :param bool ignore_hashes=False:
        :param bool blocking=False:
        :param bool only=False:
        :return: Pip-converted 3-tuples of [deps, requirements_deps]
    """
    deps = []
    requirements_deps = []
    for section in list(file_dict.keys()):
        # Turn develop-vcs into ['develop', 'vcs']
        section_name, suffix = section.rsplit(
            '-', 1
        ) if '-' in section and not section == 'dev-packages' else (
            section, None
        )
        if not file_dict[section] or section_name not in (
            'dev-packages', 'packages', 'default', 'develop'
        ):
            continue

        is_dev = section_name in ('dev-packages', 'develop')
        if is_dev and not dev:
            continue

        if ignore_hashes:
            for k, v in file_dict[section]:
                if 'hash' in v:
                    del v['hash']
        # Block and ignore hashes for all suffixed sections (vcs/editable)
        no_hashes = True if suffix else ignore_hashes
        block = True if suffix else blocking
        include_index = True if not suffix else False
        converted = convert_deps_to_pip(
            file_dict[section], project, r=False, include_index=include_index
        )
        deps.extend((d, no_hashes, block) for d in converted)
        if dev and is_dev and requirements:
            requirements_deps.extend((d, no_hashes, block) for d in converted)
    return deps, requirements_deps


def split_argument(req, short=None, long_=None, num=-1):
    """Split an argument from a string (finds None if not present).

    Uses -short <arg>, --long <arg>, and --long=arg as permutations.

    returns string, index
    """
    index_entries = []
    if long_:
        index_entries.append('--{0}'.format(long_))
    if short:
        index_entries.append('-{0}'.format(short))
    match_string = '|'.join(index_entries)
    matches = re.findall('(?<=\s)({0})([\s=])(\S+)'.format(match_string), req)
    remove_strings = []
    match_values = []
    for match in matches:
        match_values.append(match[-1])
        remove_strings.append(''.join(match))
    for string_to_remove in remove_strings:
        req = req.replace(' {0}'.format(string_to_remove), '')
    if not match_values:
        return req, None
    if num == 1:
        return req, match_values[0]
    if num == -1:
        return req, match_values
    return req, match_values[:num]


def pip_install(
    package_name=None,
    r=None,
    allow_global=False,
    ignore_hashes=False,
    no_deps=True,
    verbose=False,
    block=True,
    index=None,
    pre=False,
    selective_upgrade=False,
    requirements_dir=None,
    extra_indexes=None,
    pypi_mirror=None,
):
    from notpip._internal import logger as piplogger
    from notpip._vendor.pyparsing import ParseException

    if verbose:
        click.echo(
            crayons.normal('Installing {0!r}'.format(package_name), bold=True),
            err=True,
        )
        piplogger.setLevel(logging.INFO)
    # Create files for hash mode.
    if not package_name.startswith('-e ') and (not ignore_hashes) and (
        r is None
    ):
        fd, r = tempfile.mkstemp(
            prefix='pipenv-', suffix='-requirement.txt', dir=requirements_dir
        )
        with os.fdopen(fd, 'w') as f:
            f.write(package_name)
    # Install dependencies when a package is a VCS dependency.
    try:
        req = requirementslib.Requirement.from_line(
            package_name.split('--hash')[0].split('--trusted-host')[0]
        ).vcs
    except (ParseException, ValueError) as e:
        click.echo('{0}: {1}'.format(crayons.red('WARNING'), e), err=True)
        click.echo(
            '{0}... You will have to reinstall any packages that failed to install.'.format(
                crayons.red('ABORTING INSTALL')
            ),
            err=True,
        )
        click.echo(
            'You may have to manually run {0} when you are finished.'.format(
                crayons.normal('pipenv lock', bold=True)
            )
        )
        sys.exit(1)
    if req:
        no_deps = False
        # Don't specify a source directory when using --system.
        if not allow_global and ('PIP_SRC' not in os.environ):
            src = '--src {0}'.format(
                escape_grouped_arguments(project.virtualenv_src_location)
            )
        else:
            src = ''
    else:
        src = ''

    # Try installing for each source in project.sources.
    if index:
        if not is_valid_url(index):
            index = project.find_source(index).get('url')
        sources = [{'url': index}]
        if extra_indexes:
            if isinstance(extra_indexes, six.string_types):
                extra_indexes = [extra_indexes]
            for idx in extra_indexes:
                try:
                    extra_src = project.find_source(idx).get('url')
                except SourceNotFound:
                    extra_src = idx
                if extra_src != index:
                    sources.append({'url': extra_src})
        else:
            for idx in project.pipfile_sources:
                if idx['url'] != sources[0]['url']:
                    sources.append({'url': idx['url']})
    else:
        sources = project.pipfile_sources
    if pypi_mirror:
        sources = [create_mirror_source(pypi_mirror) if is_pypi_url(source['url']) else source for source in sources]
    if package_name.startswith('-e '):
        install_reqs = ' -e "{0}"'.format(package_name.split('-e ')[1])
    elif r:
        install_reqs = ' -r {0}'.format(escape_grouped_arguments(r))
    else:
        install_reqs = ' "{0}"'.format(package_name)
    # Skip hash-checking mode, when appropriate.
    if r:
        with open(r) as f:
            if '--hash' not in f.read():
                ignore_hashes = True
    else:
        if '--hash' not in install_reqs:
            ignore_hashes = True
    verbose_flag = '--verbose' if verbose else ''
    if not ignore_hashes:
        install_reqs += ' --require-hashes'
    no_deps = '--no-deps' if no_deps else ''
    pre = '--pre' if pre else ''
    quoted_pip = which_pip(allow_global=allow_global)
    quoted_pip = escape_grouped_arguments(quoted_pip)
    upgrade_strategy = '--upgrade --upgrade-strategy=only-if-needed' if selective_upgrade else ''
    pip_command = '{0} install {4} {5} {6} {7} {3} {1} {2} --exists-action w'.format(
        quoted_pip,
        install_reqs,
        ' '.join(prepare_pip_source_args(sources)),
        no_deps,
        pre,
        src,
        verbose_flag,
        upgrade_strategy,
    )
    if verbose:
        click.echo('$ {0}'.format(pip_command), err=True)
    cache_dir = Path(PIPENV_CACHE_DIR)
    pip_config = {
        'PIP_CACHE_DIR': fs_str(cache_dir.as_posix()),
        'PIP_WHEEL_DIR': fs_str(cache_dir.joinpath('wheels').as_posix()),
        'PIP_DESTINATION_DIR': fs_str(cache_dir.joinpath('pkgs').as_posix()),
    }
    c = delegator.run(pip_command, block=block, env=pip_config)
    return c


def format_pip_output(out, r=None):
    def gen(out):
        for line in out.split('\n'):
            # Remove requirements file information from pip9 output.
            if '(from -r' in line:
                yield line[: line.index('(from -r')]

            else:
                yield line

    out = '\n'.join([l for l in gen(out)])
    return out


def format_pip_error(error):
    error = error.replace(
        'Expected', str(crayons.green('Expected', bold=True))
    )
    error = error.replace('Got', str(crayons.red('Got', bold=True)))
    error = error.replace(
        'THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE',
        str(
            crayons.red(
                'THESE PACKAGES DO NOT MATCH THE HASHES FROM Pipfile.lock!',
                bold=True,
            )
        ),
    )
    error = error.replace(
        'someone may have tampered with them',
        str(crayons.red('someone may have tampered with them')),
    )
    error = error.replace(
        'option to pip install', 'option to \'pipenv install\''
    )
    return error


def do_install_dependencies(
    dev=False,
    only=False,
    bare=False,
    requirements=False,
    allow_global=False,
    ignore_hashes=False,
    skip_lock=False,
    verbose=False,
    concurrent=True,
    requirements_dir=None,
    pypi_mirror=False,
):
    """"Executes the install functionality.

    If requirements is True, simply spits out a requirements format to stdout.
    """

    def cleanup_procs(procs, concurrent):
        for c in procs:
            if concurrent:
                c.block()
            if 'Ignoring' in c.out:
                click.echo(crayons.yellow(c.out.strip()))
            if verbose:
                click.echo(crayons.blue(c.out or c.err))
            # The Installation failed...
            if c.return_code != 0:
                # Save the Failed Dependency for later.
                failed_deps_list.append((c.dep, c.ignore_hash))
                # Alert the user.
                click.echo(
                    '{0} {1}! Will try again.'.format(
                        crayons.red('An error occurred while installing'),
                        crayons.green(c.dep.split('--hash')[0].strip()),
                    )
                )

    if requirements:
        bare = True
    blocking = (not concurrent)
    # Load the lockfile if it exists, or if only is being used (e.g. lock is being used).
    if skip_lock or only or not project.lockfile_exists:
        if not bare:
            click.echo(
                crayons.normal(
                    u'Installing dependencies from Pipfile...', bold=True
                )
            )
            lockfile = split_file(project._lockfile)
    else:
        with open(project.lockfile_location) as f:
            lockfile = split_file(json.load(f))
        if not bare:
            click.echo(
                crayons.normal(
                    u'Installing dependencies from Pipfile.lock ({0})...'.format(
                        lockfile['_meta'].get('hash', {}).get('sha256')[-6:]
                    ),
                    bold=True,
                )
            )
    # Allow pip to resolve dependencies when in skip-lock mode.
    no_deps = (not skip_lock)
    deps_list, dev_deps_list = _merge_deps(
        lockfile,
        project,
        dev=dev,
        requirements=requirements,
        ignore_hashes=ignore_hashes,
        blocking=blocking,
        only=only,
    )
    failed_deps_list = []
    if requirements:
        # Comment out packages that shouldn't be included in
        # requirements.txt, for pip9.
        # Additional package selectors, specific to pip's --hash checking mode.
        for l in (deps_list, dev_deps_list):
            for i, dep in enumerate(l):
                l[i] = list(l[i])
                if '--hash' in l[i][0]:
                    l[i][0] = (l[i][0].split('--hash')[0].strip())
        index_args = prepare_pip_source_args(project.sources)
        index_args = ' '.join(index_args).replace(' -', '\n-')
        # Output only default dependencies
        click.echo(index_args)
        if not dev:
            click.echo('\n'.join(d[0] for d in sorted(deps_list)))
            sys.exit(0)
        # Output only dev dependencies
        if dev:
            click.echo('\n'.join(d[0] for d in sorted(dev_deps_list)))
            sys.exit(0)
    procs = []
    deps_list_bar = progress.bar(
        deps_list, label=INSTALL_LABEL if os.name != 'nt' else ''
    )
    for dep, ignore_hash, block in deps_list_bar:
        if len(procs) < PIPENV_MAX_SUBPROCESS:
            # Use a specific index, if specified.
            dep, index = split_argument(dep, short='i', long_='index', num=1)
            dep, extra_indexes = split_argument(dep, long_='extra-index-url')
            # Install the module.
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                verbose=verbose,
                block=block,
                index=index,
                requirements_dir=requirements_dir,
                extra_indexes=extra_indexes,
                pypi_mirror=pypi_mirror,
            )
            c.dep = dep
            c.ignore_hash = ignore_hash
            procs.append(c)
        if len(procs) >= PIPENV_MAX_SUBPROCESS or len(procs) == len(deps_list):
            cleanup_procs(procs, concurrent)
            procs = []
    cleanup_procs(procs, concurrent)
    # Iterate over the hopefully-poorly-packaged dependencies...
    if failed_deps_list:
        click.echo(
            crayons.normal(
                u'Installing initially failed dependencies...', bold=True
            )
        )
        for dep, ignore_hash in progress.bar(
            failed_deps_list, label=INSTALL_LABEL2
        ):
            # Use a specific index, if specified.
            dep, index = split_argument(dep, short='i', long_='index', num=1)
            dep, extra_indexes = split_argument(dep, long_='extra-index-url')
            # Install the module.
            c = pip_install(
                dep,
                ignore_hashes=ignore_hash,
                allow_global=allow_global,
                no_deps=no_deps,
                verbose=verbose,
                index=index,
                requirements_dir=requirements_dir,
                extra_indexes=extra_indexes,
            )
            # The Installation failed...
            if c.return_code != 0:
                # We echo both c.out and c.err because pip returns error details on out.
                click.echo(crayons.blue(format_pip_output(c.out)))
                click.echo(crayons.blue(format_pip_error(c.err)), err=True)
                # Return the subprocess' return code.
                sys.exit(c.return_code)
            else:
                click.echo(
                    '{0} {1}{2}'.format(
                        crayons.green('Success installing'),
                        crayons.green(dep.split('--hash')[0].strip()),
                        crayons.green('!'),
                    )
                )
