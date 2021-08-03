import optparse
from typing import Iterator, Optional

import pipenv.patched.notpip
from pipenv.patched.notpip._internal.index.package_finder import PackageFinder
from pipenv.patched.notpip._internal.network.session import PipSession
from pipenv.patched.notpip._internal.req import InstallRequirement
from pipenv.patched.notpip._internal.req import parse_requirements as _parse_requirements
from pipenv.patched.notpip._internal.req.constructors import install_req_from_parsed_requirement
from pipenv.patched.notpip._vendor.packaging.version import parse as parse_version

PIP_VERSION = tuple(map(int, parse_version(pip.__version__).base_version.split(".")))


def parse_requirements(
    filename: str,
    session: PipSession,
    finder: Optional[PackageFinder] = None,
    options: Optional[optparse.Values] = None,
    constraint: bool = False,
    isolated: bool = False,
) -> Iterator[InstallRequirement]:
    for parsed_req in _parse_requirements(
        filename, session, finder=finder, options=options, constraint=constraint
    ):
        yield install_req_from_parsed_requirement(parsed_req, isolated=isolated)
