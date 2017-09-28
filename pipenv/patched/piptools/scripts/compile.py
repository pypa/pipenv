# coding: utf-8
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import optparse
import os
import sys
import tempfile

import pip
from pip.req import InstallRequirement, parse_requirements

from .. import click
from ..exceptions import PipToolsError
from ..logging import log
from ..repositories import LocalRequirementsRepository, PyPIRepository
from ..resolver import Resolver
from ..utils import (assert_compatible_pip_version, dedup, is_pinned_requirement,
                     key_from_req, UNSAFE_PACKAGES)
from ..writer import OutputWriter

# Make sure we're using a compatible version of pip
assert_compatible_pip_version()

DEFAULT_REQUIREMENTS_FILE = 'requirements.in'


class PipCommand(pip.basecommand.Command):
    name = 'PipCommand'


@click.command()
@click.version_option()
@click.option('-v', '--verbose', is_flag=True, help="Show more output")
@click.option('-n', '--dry-run', is_flag=True, help="Only show what would happen, don't change anything")
@click.option('-p', '--pre', is_flag=True, default=None, help="Allow resolving to prereleases (default is not)")
@click.option('-r', '--rebuild', is_flag=True, help="Clear any caches upfront, rebuild from scratch")
@click.option('-f', '--find-links', multiple=True, help="Look for archives in this directory or on this HTML page", envvar='PIP_FIND_LINKS')  # noqa
@click.option('-i', '--index-url', help="Change index URL (defaults to PyPI)", envvar='PIP_INDEX_URL')
@click.option('--extra-index-url', multiple=True, help="Add additional index URL to search", envvar='PIP_EXTRA_INDEX_URL')  # noqa
@click.option('--client-cert', help="Path to SSL client certificate, a single file containing the private key and the certificate in PEM format.")  # noqa
@click.option('--trusted-host', multiple=True, envvar='PIP_TRUSTED_HOST',
              help="Mark this host as trusted, even though it does not have "
                   "valid or any HTTPS.")
@click.option('--header/--no-header', is_flag=True, default=True,
              help="Add header to generated file")
@click.option('--index/--no-index', is_flag=True, default=True,
              help="Add index URL to generated file")
@click.option('--emit-trusted-host/--no-emit-trusted-host', is_flag=True,
              default=True, help="Add trusted host option to generated file")
@click.option('--annotate/--no-annotate', is_flag=True, default=True,
              help="Annotate results, indicating where dependencies come from")
@click.option('-U', '--upgrade', is_flag=True, default=False,
              help='Try to upgrade all dependencies to their latest versions')
@click.option('-P', '--upgrade-package', 'upgrade_packages', nargs=1, multiple=True,
              help="Specify particular packages to upgrade.")
@click.option('-o', '--output-file', nargs=1, type=str, default=None,
              help=('Output file name. Required if more than one input file is given. '
                    'Will be derived from input file otherwise.'))
@click.option('--allow-unsafe', is_flag=True, default=False,
              help="Pin packages considered unsafe: {}".format(', '.join(sorted(UNSAFE_PACKAGES))))
@click.option('--generate-hashes', is_flag=True, default=False,
              help="Generate pip 8 style hashes in the resulting requirements file.")
@click.option('--max-rounds', default=10,
              help="Maximum number of rounds before resolving the requirements aborts.")
@click.argument('src_files', nargs=-1, type=click.Path(exists=True, allow_dash=True))
def cli(verbose, dry_run, pre, rebuild, find_links, index_url, extra_index_url,
        client_cert, trusted_host, header, index, emit_trusted_host, annotate,
        upgrade, upgrade_packages, output_file, allow_unsafe, generate_hashes,
        src_files, max_rounds):
    """Compiles requirements.txt from requirements.in specs."""
    log.verbose = verbose

    if len(src_files) == 0:
        if os.path.exists(DEFAULT_REQUIREMENTS_FILE):
            src_files = (DEFAULT_REQUIREMENTS_FILE,)
        elif os.path.exists('setup.py'):
            src_files = ('setup.py',)
            if not output_file:
                output_file = 'requirements.txt'
        else:
            raise click.BadParameter(("If you do not specify an input file, "
                                      "the default is {} or setup.py").format(DEFAULT_REQUIREMENTS_FILE))

    if len(src_files) == 1 and src_files[0] == '-':
        if not output_file:
            raise click.BadParameter('--output-file is required if input is from stdin')

    if len(src_files) > 1 and not output_file:
        raise click.BadParameter('--output-file is required if two or more input files are given.')

    if output_file:
        dst_file = output_file
    else:
        base_name = src_files[0].rsplit('.', 1)[0]
        dst_file = base_name + '.txt'

    if upgrade and upgrade_packages:
        raise click.BadParameter('Only one of --upgrade or --upgrade-package can be provided as an argument.')

    ###
    # Setup
    ###

    pip_command = get_pip_command()

    pip_args = []
    if find_links:
        for link in find_links:
            pip_args.extend(['-f', link])
    if index_url:
        pip_args.extend(['-i', index_url])
    if extra_index_url:
        for extra_index in extra_index_url:
            pip_args.extend(['--extra-index-url', extra_index])
    if client_cert:
        pip_args.extend(['--client-cert', client_cert])
    if pre:
        pip_args.extend(['--pre'])
    if trusted_host:
        for host in trusted_host:
            pip_args.extend(['--trusted-host', host])

    pip_options, _ = pip_command.parse_args(pip_args)

    session = pip_command._build_session(pip_options)
    repository = PyPIRepository(pip_options, session)

    # Proxy with a LocalRequirementsRepository if --upgrade is not specified
    # (= default invocation)
    if not upgrade and os.path.exists(dst_file):
        ireqs = parse_requirements(dst_file, finder=repository.finder, session=repository.session, options=pip_options)
        # Exclude packages from --upgrade-package/-P from the existing pins: We want to upgrade.
        upgrade_pkgs_key = {key_from_req(InstallRequirement.from_line(pkg).req) for pkg in upgrade_packages}
        existing_pins = {key_from_req(ireq.req): ireq
                         for ireq in ireqs
                         if is_pinned_requirement(ireq) and key_from_req(ireq.req) not in upgrade_pkgs_key}
        repository = LocalRequirementsRepository(existing_pins, repository)

    log.debug('Using indexes:')
    # remove duplicate index urls before processing
    repository.finder.index_urls = list(dedup(repository.finder.index_urls))
    for index_url in repository.finder.index_urls:
        log.debug('  {}'.format(index_url))

    if repository.finder.find_links:
        log.debug('')
        log.debug('Configuration:')
        for find_link in repository.finder.find_links:
            log.debug('  -f {}'.format(find_link))

    ###
    # Parsing/collecting initial requirements
    ###

    constraints = []
    for src_file in src_files:
        is_setup_file = os.path.basename(src_file) == 'setup.py'
        if is_setup_file or src_file == '-':
            # pip requires filenames and not files. Since we want to support
            # piping from stdin, we need to briefly save the input from stdin
            # to a temporary file and have pip read that.  also used for
            # reading requirements from install_requires in setup.py.
            tmpfile = tempfile.NamedTemporaryFile(mode='wt', delete=False)
            if is_setup_file:
                from distutils.core import run_setup
                dist = run_setup(src_file)
                tmpfile.write('\n'.join(dist.install_requires))
            else:
                tmpfile.write(sys.stdin.read())
            tmpfile.flush()
            constraints.extend(parse_requirements(
                tmpfile.name, finder=repository.finder, session=repository.session, options=pip_options))
        else:
            constraints.extend(parse_requirements(
                src_file, finder=repository.finder, session=repository.session, options=pip_options))

    # Check the given base set of constraints first
    Resolver.check_constraints(constraints)

    try:
        resolver = Resolver(constraints, repository, prereleases=pre,
                            clear_caches=rebuild, allow_unsafe=allow_unsafe)
        results = resolver.resolve(max_rounds=max_rounds)
        if generate_hashes:
            hashes = resolver.resolve_hashes(results)
        else:
            hashes = None
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    log.debug('')

    ##
    # Output
    ##

    # Compute reverse dependency annotations statically, from the
    # dependency cache that the resolver has populated by now.
    #
    # TODO (1a): reverse deps for any editable package are lost
    #            what SHOULD happen is that they are cached in memory, just
    #            not persisted to disk!
    #
    # TODO (1b): perhaps it's easiest if the dependency cache has an API
    #            that could take InstallRequirements directly, like:
    #
    #                cache.set(ireq, ...)
    #
    #            then, when ireq is editable, it would store in
    #
    #              editables[egg_name][link_without_fragment] = deps
    #              editables['pip-tools']['git+...ols.git@future'] = {'click>=3.0', 'six'}
    #
    #            otherwise:
    #
    #              self[as_name_version_tuple(ireq)] = {'click>=3.0', 'six'}
    #
    reverse_dependencies = None
    if annotate:
        reverse_dependencies = resolver.reverse_dependencies(results)

    writer = OutputWriter(src_files, dst_file, dry_run=dry_run,
                          emit_header=header, emit_index=index,
                          emit_trusted_host=emit_trusted_host,
                          annotate=annotate,
                          generate_hashes=generate_hashes,
                          default_index_url=repository.DEFAULT_INDEX_URL,
                          index_urls=repository.finder.index_urls,
                          trusted_hosts=pip_options.trusted_hosts,
                          format_control=repository.finder.format_control)
    writer.write(results=results,
                 unsafe_requirements=resolver.unsafe_constraints,
                 reverse_dependencies=reverse_dependencies,
                 primary_packages={key_from_req(ireq.req) for ireq in constraints if not ireq.constraint},
                 markers={key_from_req(ireq.req): ireq.markers
                          for ireq in constraints if ireq.markers},
                 hashes=hashes,
                 allow_unsafe=allow_unsafe)

    if dry_run:
        log.warning('Dry-run, so nothing updated.')


def get_pip_command():
    # Use pip's parser for pip.conf management and defaults.
    # General options (find_links, index_url, extra_index_url, trusted_host,
    # and pre) are defered to pip.
    pip_command = PipCommand()
    index_opts = pip.cmdoptions.make_option_group(
        pip.cmdoptions.index_group,
        pip_command.parser,
    )
    pip_command.parser.insert_option_group(0, index_opts)
    pip_command.parser.add_option(optparse.Option('--pre', action='store_true', default=False))

    return pip_command
