"""Validation of dependencies of packages
"""

from collections import namedtuple

from pipenv.patched.notpip._vendor.packaging.utils import canonicalize_name

from pipenv.patched.notpip._internal.operations.prepare import make_abstract_dist

from pipenv.patched.notpip._internal.utils.misc import get_installed_distributions
from pipenv.patched.notpip._internal.utils.typing import MYPY_CHECK_RUNNING

if MYPY_CHECK_RUNNING:
    from pipenv.patched.notpip._internal.req.req_install import InstallRequirement
    from typing import Any, Dict, Iterator, Set, Tuple, List

    # Shorthands
    PackageSet = Dict[str, 'PackageDetails']
    Missing = Tuple[str, Any]
    Conflicting = Tuple[str, str, Any]

    MissingDict = Dict[str, List[Missing]]
    ConflictingDict = Dict[str, List[Conflicting]]
    CheckResult = Tuple[MissingDict, ConflictingDict]

PackageDetails = namedtuple('PackageDetails', ['version', 'requires'])


def create_package_set_from_installed(**kwargs):
    # type: (**Any) -> PackageSet
    """Converts a list of distributions into a PackageSet.
    """
    # Default to using all packages installed on the system
    if kwargs == {}:
        kwargs = {"local_only": False, "skip": ()}
    retval = {}
    for dist in get_installed_distributions(**kwargs):
        name = canonicalize_name(dist.project_name)
        retval[name] = PackageDetails(dist.version, dist.requires())
    return retval


def check_package_set(package_set):
    # type: (PackageSet) -> CheckResult
    """Check if a package set is consistent
    """
    missing = dict()
    conflicting = dict()

    for package_name in package_set:
        # Info about dependencies of package_name
        missing_deps = set()  # type: Set[Missing]
        conflicting_deps = set()  # type: Set[Conflicting]

        for req in package_set[package_name].requires:
            name = canonicalize_name(req.project_name)  # type: str

            # Check if it's missing
            if name not in package_set:
                missed = True
                if req.marker is not None:
                    missed = req.marker.evaluate()
                if missed:
                    missing_deps.add((name, req))
                continue

            # Check if there's a conflict
            version = package_set[name].version  # type: str
            if not req.specifier.contains(version, prereleases=True):
                conflicting_deps.add((name, version, req))

        def str_key(x):
            return str(x)

        if missing_deps:
            missing[package_name] = sorted(missing_deps, key=str_key)
        if conflicting_deps:
            conflicting[package_name] = sorted(conflicting_deps, key=str_key)

    return missing, conflicting


def check_install_conflicts(to_install):
    # type: (List[InstallRequirement]) -> Tuple[PackageSet, CheckResult]
    """For checking if the dependency graph would be consistent after \
    installing given requirements
    """
    # Start from the current state
    state = create_package_set_from_installed()
    _simulate_installation_of(to_install, state)
    return state, check_package_set(state)


# NOTE from @pradyunsg
# This required a minor update in dependency link handling logic over at
# operations.prepare.IsSDist.dist() to get it working
def _simulate_installation_of(to_install, state):
    # type: (List[InstallRequirement], PackageSet) -> None
    """Computes the version of packages after installing to_install.
    """

    # Modify it as installing requirement_set would (assuming no errors)
    for inst_req in to_install:
        dist = make_abstract_dist(inst_req).dist(finder=None)
        name = canonicalize_name(dist.key)
        state[name] = PackageDetails(dist.version, dist.requires())
