import re
import sys

from pipenv.utils.dependencies import get_lockfile_section_using_pipfile_category
from pipenv.utils.requirements import (
    requirements_from_lockfile,
    requirements_from_pipfile,
)


def generate_requirements(
    project,
    dev=False,
    dev_only=False,
    include_hashes=False,
    include_markers=True,
    categories="",
    from_pipfile=False,
    no_lock=False,
):
    # If --no-lock, generate from Pipfile directly without using lockfile versions
    if no_lock:
        _generate_requirements_from_pipfile(
            project=project,
            dev=dev,
            dev_only=dev_only,
            include_markers=include_markers,
            categories=categories,
        )
        return

    lockfile = project.load_lockfile(expand_env_vars=False)
    pipfile_package_names = project.pipfile_package_names

    # Print index URLs first
    for i, package_index in enumerate(lockfile["_meta"]["sources"]):
        prefix = "-i" if i == 0 else "--extra-index-url"
        print(
            " ".join([prefix, package_index["url"]])
        )  # Use print instead of console.print

    deps = {}
    categories_list = re.split(r", *| ", categories) if categories else []

    if categories_list:
        for category in categories_list:
            lockfile_category = get_lockfile_section_using_pipfile_category(
                category.strip()
            )
            category_deps = lockfile.get(lockfile_category, {})
            if from_pipfile:
                # Use the specific category's package names, not combined
                category_package_names = pipfile_package_names.get(
                    category.strip(), set()
                )
                category_deps = {
                    k: v for k, v in category_deps.items() if k in category_package_names
                }
            deps.update(category_deps)
    else:
        if dev or dev_only:
            dev_deps = lockfile["develop"]
            if from_pipfile:
                # Only use dev-packages names when filtering dev dependencies
                dev_package_names = pipfile_package_names.get("dev-packages", set())
                dev_deps = {k: v for k, v in dev_deps.items() if k in dev_package_names}
            deps.update(dev_deps)
        if not dev_only:
            default_deps = lockfile["default"]
            if from_pipfile:
                # Only use packages names when filtering default dependencies
                default_package_names = pipfile_package_names.get("packages", set())
                default_deps = {
                    k: v for k, v in default_deps.items() if k in default_package_names
                }
            deps.update(default_deps)

    pip_installable_lines = requirements_from_lockfile(
        deps, include_hashes=include_hashes, include_markers=include_markers
    )

    # Print each requirement on its own line
    for line in pip_installable_lines:
        print(line)  # Use print instead of console.print

    sys.exit(0)


def _generate_requirements_from_pipfile(
    project,
    dev=False,
    dev_only=False,
    include_markers=True,
    categories="",
):
    """Generate requirements directly from Pipfile using flexible version specifiers.

    This is useful for libraries that need looser version constraints than
    the strictly pinned versions in Pipfile.lock.
    """
    parsed_pipfile = project.parsed_pipfile

    # Print index URLs from Pipfile sources
    sources = parsed_pipfile.get("source", [])
    for i, source in enumerate(sources):
        url = source.get("url", "")
        if url:
            prefix = "-i" if i == 0 else "--extra-index-url"
            print(f"{prefix} {url}")

    deps = {}
    categories_list = re.split(r", *| ", categories) if categories else []

    if categories_list:
        for category in categories_list:
            category_deps = project.get_pipfile_section(category.strip())
            deps.update(category_deps)
    else:
        if dev or dev_only:
            dev_deps = project.get_pipfile_section("dev-packages")
            deps.update(dev_deps)
        if not dev_only:
            default_deps = project.get_pipfile_section("packages")
            deps.update(default_deps)

    pip_installable_lines = requirements_from_pipfile(
        deps, include_markers=include_markers
    )

    # Print each requirement on its own line
    for line in pip_installable_lines:
        print(line)

    sys.exit(0)
