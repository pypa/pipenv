import os
from urllib.parse import unquote

from pipenv.patched.pip._internal.network.session import PipSession
from pipenv.patched.pip._internal.req import parse_requirements
from pipenv.patched.pip._internal.req.constructors import (
    install_req_from_parsed_requirement,
)
from pipenv.utils.constants import VCS_LIST
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
    for f in parse_requirements(r, session=PipSession()):
        package = install_req_from_parsed_requirement(f)
        if package.name not in BAD_PACKAGES:
            if package.link is not None:
                if package.editable:
                    package_string = f"-e {package.link}"
                else:
                    package_string = unquote(str(package.original_link))

                project.add_package_to_pipfile(package, package_string, dev=dev)
            else:
                project.add_package_to_pipfile(package, str(package.req), dev=dev)
    indexes = sorted(set(indexes))
    trusted_hosts = sorted(set(trusted_hosts))
    for index in indexes:
        add_index_to_pipfile(project, index, trusted_hosts)
    project.recase_pipfile()


def add_index_to_pipfile(project, index, trusted_hosts=None):
    # don't require HTTPS for trusted hosts (see: https://pip.pypa.io/en/stable/cli/pip/#cmdoption-trusted-host)
    if trusted_hosts is None:
        trusted_hosts = get_trusted_hosts()

    host_and_port = get_host_and_port(index)
    require_valid_https = not any(
        v in trusted_hosts
        for v in (
            host_and_port,
            host_and_port.partition(":")[
                0
            ],  # also check if hostname without port is in trusted_hosts
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


def requirement_from_lockfile(
    package_name, package_info, include_hashes=True, include_markers=True
):
    from pipenv.utils.dependencies import is_editable_path, is_star

    # Handle string requirements
    if isinstance(package_info, str):
        if package_info and not is_star(package_info):
            return f"{package_name}=={package_info}"
        else:
            return package_name
    # Handling vcs repositories
    for vcs in VCS_LIST:
        if vcs in package_info:
            url = package_info[vcs]
            ref = package_info.get("ref", "")
            extras = (
                "[{}]".format(",".join(package_info.get("extras", [])))
                if "extras" in package_info
                else ""
            )
            include_vcs = "" if f"{vcs}+" in url else f"{vcs}+"
            egg_fragment = "" if "#egg=" in url else f"#egg={package_name}"
            pip_line = f"{include_vcs}{url}@{ref}{egg_fragment}{extras}"
            return pip_line
    # Handling file-sourced packages
    for k in ["file", "path"]:
        line = []
        if k in package_info:
            path = package_info[k]
            if is_editable_path(path):
                line.append("-e")
            extras = ""
            if "extras" in package_info:
                extras = f"[{','.join(package_info['extras'])}]"
            line.append(f"{package_info[k]}{extras}")
            pip_line = " ".join(line)
            return pip_line

    # Handling packages from standard pypi like indexes
    version = package_info.get("version", "").replace("==", "")
    hashes = (
        f" --hash={' --hash='.join(package_info['hashes'])}"
        if include_hashes and "hashes" in package_info
        else ""
    )
    markers = (
        "; {}".format(package_info["markers"])
        if include_markers and "markers" in package_info and package_info["markers"]
        else ""
    )
    os_markers = (
        "; {}".format(package_info["os_markers"])
        if include_markers and "os_markers" in package_info and package_info["os_markers"]
        else ""
    )
    extras = (
        "[{}]".format(",".join(package_info.get("extras", [])))
        if "extras" in package_info
        else ""
    )
    pip_line = f"{package_name}{extras}=={version}{os_markers}{markers}{hashes}"
    return pip_line


def requirements_from_lockfile(deps, include_hashes=True, include_markers=True):
    pip_packages = []

    for package_name, package_info in deps.items():
        pip_package = requirement_from_lockfile(
            package_name, package_info, include_hashes, include_markers
        )

        # Append to the list
        pip_packages.append(pip_package)

    # pip_packages contains the pip-installable lines
    return pip_packages
