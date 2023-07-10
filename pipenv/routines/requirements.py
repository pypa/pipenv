import re
import sys

from pipenv.utils.dependencies import get_lockfile_section_using_pipfile_category
from pipenv.vendor import click


def requirements_from_deps(deps, include_hashes=True, include_markers=True):
    pip_packages = []

    for package_name, package_info in deps.items():
        # Handling git repositories
        if "git" in package_info:
            git = package_info["git"]
            ref = package_info.get("ref", "")
            extras = (
                "[{}]".format(",".join(package_info.get("extras", [])))
                if "extras" in package_info
                else ""
            )
            pip_package = f"{package_name}{extras} @ git+{git}@{ref}"
        # Handling file-sourced packages
        elif "file" in package_info or "path" in package_info:
            file = package_info.get("file") or package_info.get("path")
            extras = (
                "[{}]".format(",".join(package_info.get("extras", [])))
                if "extras" in package_info
                else ""
            )
            pip_package = f"{file}{extras}"
        else:
            # Handling packages from standard pypi like indexes
            version = package_info.get("version", "").replace("==", "")
            hashes = (
                " --hash={}".format(" --hash=".join(package_info["hashes"]))
                if include_hashes and "hashes" in package_info
                else ""
            )
            markers = (
                "; {}".format(package_info["markers"])
                if include_markers
                and "markers" in package_info
                and package_info["markers"]
                else ""
            )
            extras = (
                "[{}]".format(",".join(package_info.get("extras", [])))
                if "extras" in package_info
                else ""
            )
            pip_package = f"{package_name}{extras}=={version}{markers}{hashes}"

        # Append to the list
        pip_packages.append(pip_package)

    # pip_packages contains the pip-installable lines
    return pip_packages


def generate_requirements(
    project,
    dev=False,
    dev_only=False,
    include_hashes=False,
    include_markers=True,
    categories="",
):
    lockfile = project.load_lockfile(expand_env_vars=False)

    for i, package_index in enumerate(lockfile["_meta"]["sources"]):
        prefix = "-i" if i == 0 else "--extra-index-url"
        click.echo(" ".join([prefix, package_index["url"]]))

    deps = {}
    categories_list = re.split(r", *| ", categories) if categories else []

    if categories_list:
        for category in categories_list:
            category = get_lockfile_section_using_pipfile_category(category.strip())
            deps.update(lockfile.get(category, {}))
    else:
        if dev or dev_only:
            deps.update(lockfile["develop"])
        if not dev_only:
            deps.update(lockfile["default"])

    pip_installable_lines = requirements_from_deps(
        deps, include_hashes=include_hashes, include_markers=include_markers
    )

    for line in pip_installable_lines:
        click.echo(line)

    sys.exit(0)
