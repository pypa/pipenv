# coding: utf-8
from __future__ import absolute_import, division, print_function, unicode_literals

import itertools
import os
import shlex
import sys

from ._compat import get_installed_distributions, InstallCommand

from .. import click, sync
from .._compat import parse_requirements
from ..exceptions import PipToolsError
from ..logging import log
from ..repositories import PyPIRepository
from ..utils import flat_map

DEFAULT_REQUIREMENTS_FILE = "requirements.txt"


@click.command()
@click.version_option()
@click.option(
    "-a",
    "--ask",
    is_flag=True,
    help="Show what would happen, then ask whether to continue",
)
@click.option(
    "-n",
    "--dry-run",
    is_flag=True,
    help="Only show what would happen, don't change anything",
)
@click.option("--force", is_flag=True, help="Proceed even if conflicts are found")
@click.option(
    "-f",
    "--find-links",
    multiple=True,
    help="Look for archives in this directory or on this HTML page",
    envvar="PIP_FIND_LINKS",
)
@click.option(
    "-i",
    "--index-url",
    help="Change index URL (defaults to PyPI)",
    envvar="PIP_INDEX_URL",
)
@click.option(
    "--extra-index-url",
    multiple=True,
    help="Add additional index URL to search",
    envvar="PIP_EXTRA_INDEX_URL",
)
@click.option(
    "--trusted-host",
    multiple=True,
    help="Mark this host as trusted, even though it does not have valid or any HTTPS.",
)
@click.option(
    "--no-index",
    is_flag=True,
    help="Ignore package index (only looking at --find-links URLs instead)",
)
@click.option("-q", "--quiet", default=False, is_flag=True, help="Give less output")
@click.option(
    "--user", "user_only", is_flag=True, help="Restrict attention to user directory"
)
@click.option("--cert", help="Path to alternate CA bundle.")
@click.option(
    "--client-cert",
    help="Path to SSL client certificate, a single file containing "
    "the private key and the certificate in PEM format.",
)
@click.argument("src_files", required=False, type=click.Path(exists=True), nargs=-1)
@click.option("--pip-args", help="Arguments to pass directly to pip install.")
def cli(
    ask,
    dry_run,
    force,
    find_links,
    index_url,
    extra_index_url,
    trusted_host,
    no_index,
    quiet,
    user_only,
    cert,
    client_cert,
    src_files,
    pip_args,
):
    """Synchronize virtual environment with requirements.txt."""
    if not src_files:
        if os.path.exists(DEFAULT_REQUIREMENTS_FILE):
            src_files = (DEFAULT_REQUIREMENTS_FILE,)
        else:
            msg = "No requirement files given and no {} found in the current directory"
            log.error(msg.format(DEFAULT_REQUIREMENTS_FILE))
            sys.exit(2)

    if any(src_file.endswith(".in") for src_file in src_files):
        msg = (
            "Some input files have the .in extension, which is most likely an error "
            "and can cause weird behaviour. You probably meant to use "
            "the corresponding *.txt file?"
        )
        if force:
            log.warning("WARNING: " + msg)
        else:
            log.error("ERROR: " + msg)
            sys.exit(2)

    install_command = InstallCommand()
    options, _ = install_command.parse_args([])
    session = install_command._build_session(options)
    finder = install_command._build_package_finder(options=options, session=session)

    # Parse requirements file. Note, all options inside requirements file
    # will be collected by the finder.
    requirements = flat_map(
        lambda src: parse_requirements(src, finder=finder, session=session), src_files
    )

    try:
        requirements = sync.merge(requirements, ignore_conflicts=force)
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    installed_dists = get_installed_distributions(skip=[], user_only=user_only)
    to_install, to_uninstall = sync.diff(requirements, installed_dists)

    install_flags = _compose_install_flags(
        finder,
        no_index=no_index,
        index_url=index_url,
        extra_index_url=extra_index_url,
        trusted_host=trusted_host,
        find_links=find_links,
        user_only=user_only,
        cert=cert,
        client_cert=client_cert,
    ) + shlex.split(pip_args or "")
    sys.exit(
        sync.sync(
            to_install,
            to_uninstall,
            verbose=(not quiet),
            dry_run=dry_run,
            install_flags=install_flags,
            ask=ask,
        )
    )


def _compose_install_flags(
    finder,
    no_index=False,
    index_url=None,
    extra_index_url=None,
    trusted_host=None,
    find_links=None,
    user_only=False,
    cert=None,
    client_cert=None,
):
    """
    Compose install flags with the given finder and CLI options.
    """
    result = []

    # Build --index-url/--extra-index-url/--no-index
    if no_index:
        result.append("--no-index")
    elif index_url:
        result.extend(["--index-url", index_url])
    elif finder.index_urls:
        finder_index_url = finder.index_urls[0]
        if finder_index_url != PyPIRepository.DEFAULT_INDEX_URL:
            result.extend(["--index-url", finder_index_url])
        for extra_index in finder.index_urls[1:]:
            result.extend(["--extra-index-url", extra_index])
    else:
        result.append("--no-index")

    for extra_index in extra_index_url or []:
        result.extend(["--extra-index-url", extra_index])

    # Build --trusted-hosts
    for host in itertools.chain(trusted_host or [], finder.trusted_hosts):
        result.extend(["--trusted-host", host])

    # Build --find-links
    for link in itertools.chain(find_links or [], finder.find_links):
        result.extend(["--find-links", link])

    # Build format controls --no-binary/--only-binary
    for format_control in ("no_binary", "only_binary"):
        formats = getattr(finder.format_control, format_control)
        if not formats:
            continue
        result.extend(
            ["--" + format_control.replace("_", "-"), ",".join(sorted(formats))]
        )

    if user_only:
        result.append("--user")

    if cert:
        result.extend(["--cert", cert])

    if client_cert:
        result.extend(["--client-cert", client_cert])

    return result
