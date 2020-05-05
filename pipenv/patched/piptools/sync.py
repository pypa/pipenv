import collections
import os
import sys
import tempfile
from subprocess import check_call  # nosec

from ._compat import DEV_PKGS
from ._compat import stdlib_pkgs

from . import click
from .exceptions import IncompatibleRequirements
from .utils import (
    flat_map,
    format_requirement,
    get_hashes_from_ireq,
    is_url_requirement,
    key_from_ireq,
    key_from_req,
)

PACKAGES_TO_IGNORE = (
    ["-markerlib", "pip", "pip-tools", "pip-review", "pkg-resources"]
    + list(stdlib_pkgs)
    + list(DEV_PKGS)
)


def dependency_tree(installed_keys, root_key):
    """
    Calculate the dependency tree for the package `root_key` and return
    a collection of all its dependencies.  Uses a DFS traversal algorithm.

    `installed_keys` should be a {key: requirement} mapping, e.g.
        {'django': from_line('django==1.8')}
    `root_key` should be the key to return the dependency tree for.
    """
    dependencies = set()
    queue = collections.deque()

    if root_key in installed_keys:
        dep = installed_keys[root_key]
        queue.append(dep)

    while queue:
        v = queue.popleft()
        key = key_from_req(v)
        if key in dependencies:
            continue

        dependencies.add(key)

        for dep_specifier in v.requires():
            dep_name = key_from_req(dep_specifier)
            if dep_name in installed_keys:
                dep = installed_keys[dep_name]

                if dep_specifier.specifier.contains(dep.version):
                    queue.append(dep)

    return dependencies


def get_dists_to_ignore(installed):
    """
    Returns a collection of package names to ignore when performing pip-sync,
    based on the currently installed environment.  For example, when pip-tools
    is installed in the local environment, it should be ignored, including all
    of its dependencies (e.g. click).  When pip-tools is not installed
    locally, click should also be installed/uninstalled depending on the given
    requirements.
    """
    installed_keys = {key_from_req(r): r for r in installed}
    return list(
        flat_map(lambda req: dependency_tree(installed_keys, req), PACKAGES_TO_IGNORE)
    )


def merge(requirements, ignore_conflicts):
    by_key = {}

    for ireq in requirements:
        # Limitation: URL requirements are merged by precise string match, so
        # "file:///example.zip#egg=example", "file:///example.zip", and
        # "example==1.0" will not merge with each other
        if ireq.match_markers():
            key = key_from_ireq(ireq)

            if not ignore_conflicts:
                existing_ireq = by_key.get(key)
                if existing_ireq:
                    # NOTE: We check equality here since we can assume that the
                    # requirements are all pinned
                    if ireq.specifier != existing_ireq.specifier:
                        raise IncompatibleRequirements(ireq, existing_ireq)

            # TODO: Always pick the largest specifier in case of a conflict
            by_key[key] = ireq
    return by_key.values()


def diff_key_from_ireq(ireq):
    """
    Calculate a key for comparing a compiled requirement with installed modules.
    For URL requirements, only provide a useful key if the url includes
    #egg=name==version, which will set ireq.req.name and ireq.specifier.
    Otherwise return ireq.link so the key will not match and the package will
    reinstall. Reinstall is necessary to ensure that packages will reinstall
    if the URL is changed but the version is not.
    """
    if is_url_requirement(ireq):
        if (
            ireq.req
            and (getattr(ireq.req, "key", None) or getattr(ireq.req, "name", None))
            and ireq.specifier
        ):
            return key_from_ireq(ireq)
        return str(ireq.link)
    return key_from_ireq(ireq)


def diff(compiled_requirements, installed_dists):
    """
    Calculate which packages should be installed or uninstalled, given a set
    of compiled requirements and a list of currently installed modules.
    """
    requirements_lut = {diff_key_from_ireq(r): r for r in compiled_requirements}

    satisfied = set()  # holds keys
    to_install = set()  # holds InstallRequirement objects
    to_uninstall = set()  # holds keys

    pkgs_to_ignore = get_dists_to_ignore(installed_dists)
    for dist in installed_dists:
        key = key_from_req(dist)
        if key not in requirements_lut or not requirements_lut[key].match_markers():
            to_uninstall.add(key)
        elif requirements_lut[key].specifier.contains(dist.version):
            satisfied.add(key)

    for key, requirement in requirements_lut.items():
        if key not in satisfied and requirement.match_markers():
            to_install.add(requirement)

    # Make sure to not uninstall any packages that should be ignored
    to_uninstall -= set(pkgs_to_ignore)

    return (to_install, to_uninstall)


def sync(
    to_install,
    to_uninstall,
    verbose=False,
    dry_run=False,
    install_flags=None,
    ask=False,
):
    """
    Install and uninstalls the given sets of modules.
    """
    if not to_uninstall and not to_install:
        if verbose:
            click.echo("Everything up-to-date")
        return 0

    pip_flags = []
    if not verbose:
        pip_flags += ["-q"]

    if ask:
        dry_run = True

    if dry_run:
        if to_uninstall:
            click.echo("Would uninstall:")
            for pkg in to_uninstall:
                click.echo("  {}".format(pkg))

        if to_install:
            click.echo("Would install:")
            for ireq in to_install:
                click.echo("  {}".format(format_requirement(ireq)))

    if ask and click.confirm("Would you like to proceed with these changes?"):
        dry_run = False

    if not dry_run:
        if to_uninstall:
            check_call(  # nosec
                [sys.executable, "-m", "pip", "uninstall", "-y"]
                + pip_flags
                + sorted(to_uninstall)
            )

        if to_install:
            if install_flags is None:
                install_flags = []
            # prepare requirement lines
            req_lines = []
            for ireq in sorted(to_install, key=key_from_ireq):
                ireq_hashes = get_hashes_from_ireq(ireq)
                req_lines.append(format_requirement(ireq, hashes=ireq_hashes))

            # save requirement lines to a temporary file
            tmp_req_file = tempfile.NamedTemporaryFile(mode="wt", delete=False)
            tmp_req_file.write("\n".join(req_lines))
            tmp_req_file.close()

            try:
                check_call(  # nosec
                    [sys.executable, "-m", "pip", "install", "-r", tmp_req_file.name]
                    + pip_flags
                    + install_flags
                )
            finally:
                os.unlink(tmp_req_file.name)

    return 0
