import os
import re

from pipenv.patched.pip._internal.network.session import PipSession
from pipenv.patched.pip._internal.req import parse_requirements
from pipenv.patched.pip._internal.req.constructors import (
    install_req_from_parsed_requirement,
)
from pipenv.patched.pip._internal.utils.misc import split_auth_from_netloc
from pipenv.utils.indexes import parse_indexes
from pipenv.utils.internet import get_host_and_port
from pipenv.utils.pip import get_trusted_hosts


def import_requirements(project, r=None, dev=False):
    # Parse requirements.txt file with Pip's parser.
    # Pip requires a `PipSession` which is a subclass of requests.Session.
    # Since we're not making any network calls, it's initialized to nothing.
    if r:
        assert os.path.isfile(r)
    # Default path, if none is provided.
    if r is None:
        r = project.requirements_location
    with open(r) as f:
        contents = f.read()
    indexes = []
    trusted_hosts = []
    # Find and add extra indexes.
    for line in contents.split("\n"):
        index, extra_index, trusted_host, _ = parse_indexes(line.strip(), strict=True)
        if index:
            indexes = [index]
        if extra_index:
            indexes.append(extra_index)
        if trusted_host:
            trusted_hosts.append(get_host_and_port(trusted_host))
    indexes = sorted(set(indexes))
    trusted_hosts = sorted(set(trusted_hosts))
    reqs = [
        install_req_from_parsed_requirement(f)
        for f in parse_requirements(r, session=PipSession())
    ]
    for package in reqs:
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                if package.editable:
                    package_string = f"-e {package.link}"
                else:
                    netloc, (user, pw) = split_auth_from_netloc(package.link.netloc)
                    safe = True
                    if user and not re.match(r"\${[\W\w]+}", user):
                        safe = False
                    if pw and not re.match(r"\${[\W\w]+}", pw):
                        safe = False
                    if safe:
                        package_string = str(package.link._url)
                    else:
                        package_string = str(package.link)
                project.add_package_to_pipfile(package_string, dev=dev)
            else:
                project.add_package_to_pipfile(str(package.req), dev=dev)
    for index in indexes:
        add_index_to_pipfile(project, index, trusted_hosts)
    project.recase_pipfile()


def add_index_to_pipfile(project, index, trusted_hosts=None):
    # don't require HTTPS for trusted hosts (see: https://pip.pypa.io/en/stable/cli/pip/#cmdoption-trusted-host)
    if trusted_hosts is None:
        trusted_hosts = get_trusted_hosts()

    host_and_port = get_host_and_port(index)
    require_valid_https = not any(
        (
            v in trusted_hosts
            for v in (
                host_and_port,
                host_and_port.partition(":")[
                    0
                ],  # also check if hostname without port is in trusted_hosts
            )
        )
    )
    index_name = project.add_index_to_pipfile(index, verify_ssl=require_valid_https)
    return index_name


BAD_PACKAGES = (
    "distribute",
    "pip",
    "pkg-resources",
    "setuptools",
    "wheel",
)
