import itertools
import os
import shlex
import shutil
import sys
from typing import List, Optional, Tuple, cast

import click
from pip._internal.commands import create_command
from pip._internal.commands.install import InstallCommand
from pip._internal.index.package_finder import PackageFinder
from pip._internal.utils.misc import get_installed_distributions

from .. import sync
from .._compat import IS_CLICK_VER_8_PLUS, parse_requirements
from ..exceptions import PipToolsError
from ..logging import log
from ..repositories import PyPIRepository
from ..utils import (
    flat_map,
    get_pip_version_for_python_executable,
    get_required_pip_specification,
    get_sys_path_for_python_executable,
)

DEFAULT_REQUIREMENTS_FILE = "requirements.txt"

# TODO: drop click 7 and remove this block, pass directly to version_option
version_option_kwargs = {"package_name": "pip-tools"} if IS_CLICK_VER_8_PLUS else {}


@click.command(context_settings={"help_option_names": ("-h", "--help")})
@click.version_option(**version_option_kwargs)
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
)
@click.option("-i", "--index-url", help="Change index URL (defaults to PyPI)")
@click.option(
    "--extra-index-url", multiple=True, help="Add additional index URL to search"
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
@click.option(
    "--python-executable",
    help="Custom python executable path if targeting an environment other than current.",
)
@click.option("-v", "--verbose", count=True, help="Show more output")
@click.option("-q", "--quiet", count=True, help="Give less output")
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
    ask: bool,
    dry_run: bool,
    force: bool,
    find_links: Tuple[str, ...],
    index_url: Optional[str],
    extra_index_url: Tuple[str, ...],
    trusted_host: Tuple[str, ...],
    no_index: bool,
    python_executable: Optional[str],
    verbose: int,
    quiet: int,
    user_only: bool,
    cert: Optional[str],
    client_cert: Optional[str],
    src_files: Tuple[str, ...],
    pip_args: Optional[str],
) -> None:
    """Synchronize virtual environment with requirements.txt."""
    log.verbosity = verbose - quiet

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

    if python_executable:
        _validate_python_executable(python_executable)

    install_command = cast(InstallCommand, create_command("install"))
    options, _ = install_command.parse_args([])
    session = install_command._build_session(options)
    finder = install_command._build_package_finder(options=options, session=session)

    # Parse requirements file. Note, all options inside requirements file
    # will be collected by the finder.
    requirements = flat_map(
        lambda src: parse_requirements(src, finder=finder, session=session), src_files
    )

    try:
        merged_requirements = sync.merge(requirements, ignore_conflicts=force)
    except PipToolsError as e:
        log.error(str(e))
        sys.exit(2)

    paths = (
        None
        if python_executable is None
        else get_sys_path_for_python_executable(python_executable)
    )

    installed_dists = get_installed_distributions(
        skip=[], user_only=user_only, paths=paths, local_only=python_executable is None
    )
    to_install, to_uninstall = sync.diff(merged_requirements, installed_dists)

    install_flags = (
        _compose_install_flags(
            finder,
            no_index=no_index,
            index_url=index_url,
            extra_index_url=extra_index_url,
            trusted_host=trusted_host,
            find_links=find_links,
            user_only=user_only,
            cert=cert,
            client_cert=client_cert,
        )
        + shlex.split(pip_args or "")
    )
    sys.exit(
        sync.sync(
            to_install,
            to_uninstall,
            dry_run=dry_run,
            install_flags=install_flags,
            ask=ask,
            python_executable=python_executable,
        )
    )


def _validate_python_executable(python_executable: str) -> None:
    """
    Validates incoming python_executable argument passed to CLI.
    """
    resolved_python_executable = shutil.which(python_executable)
    if resolved_python_executable is None:
        msg = "Could not resolve '{}' as valid executable path or alias."
        log.error(msg.format(python_executable))
        sys.exit(2)

    # Ensure that target python executable has the right version of pip installed
    pip_version = get_pip_version_for_python_executable(python_executable)
    required_pip_specification = get_required_pip_specification()
    if not required_pip_specification.contains(pip_version, prereleases=True):
        msg = (
            "Target python executable '{}' has pip version {} installed. "
            "Version {} is expected."
        )
        log.error(
            msg.format(python_executable, pip_version, required_pip_specification)
        )
        sys.exit(2)


def _compose_install_flags(
    finder: PackageFinder,
    no_index: bool,
    index_url: Optional[str],
    extra_index_url: Tuple[str, ...],
    trusted_host: Tuple[str, ...],
    find_links: Tuple[str, ...],
    user_only: bool,
    cert: Optional[str],
    client_cert: Optional[str],
) -> List[str]:
    """
    Compose install flags with the given finder and CLI options.
    """
    result = []

    # Build --index-url/--extra-index-url/--no-index
    if no_index:
        result.append("--no-index")
    elif index_url is not None:
        result.extend(["--index-url", index_url])
    elif finder.index_urls:
        finder_index_url = finder.index_urls[0]
        if finder_index_url != PyPIRepository.DEFAULT_INDEX_URL:
            result.extend(["--index-url", finder_index_url])
        for extra_index in finder.index_urls[1:]:
            result.extend(["--extra-index-url", extra_index])
    else:
        result.append("--no-index")

    for extra_index in extra_index_url:
        result.extend(["--extra-index-url", extra_index])

    # Build --trusted-hosts
    for host in itertools.chain(trusted_host, finder.trusted_hosts):
        result.extend(["--trusted-host", host])

    # Build --find-links
    for link in itertools.chain(find_links, finder.find_links):
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

    if cert is not None:
        result.extend(["--cert", cert])

    if client_cert is not None:
        result.extend(["--client-cert", client_cert])

    return result
