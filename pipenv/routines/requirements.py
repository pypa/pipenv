import re
import sys

from pipenv.utils.dependencies import get_lockfile_section_using_pipfile_category
from pipenv.utils.requirements import requirements_from_lockfile
from pipenv.vendor import click


def generate_requirements(
    project,
    dev=False,
    dev_only=False,
    include_hashes=False,
    include_markers=True,
    categories="",
    from_pipfile=False,
):
    lockfile = project.load_lockfile(expand_env_vars=False)
    pipfile_root_package_names = project.pipfile_package_names["combined"]

    for i, package_index in enumerate(lockfile["_meta"]["sources"]):
        prefix = "-i" if i == 0 else "--extra-index-url"
        click.echo(" ".join([prefix, package_index["url"]]))

    deps = {}
    categories_list = re.split(r", *| ", categories) if categories else []

    if categories_list:
        for category in categories_list:
            category = get_lockfile_section_using_pipfile_category(category.strip())
            category_deps = lockfile.get(category, {})
            if from_pipfile:
                category_deps = {
                    k: v
                    for k, v in category_deps.items()
                    if k in pipfile_root_package_names
                }
            deps.update(category_deps)
    else:
        if dev or dev_only:
            dev_deps = lockfile["develop"]
            if from_pipfile:
                dev_deps = {
                    k: v for k, v in dev_deps.items() if k in pipfile_root_package_names
                }
            deps.update(dev_deps)
        if not dev_only:
            default_deps = lockfile["default"]
            if from_pipfile:
                default_deps = {
                    k: v
                    for k, v in default_deps.items()
                    if k in pipfile_root_package_names
                }
            deps.update(default_deps)

    pip_installable_lines = requirements_from_lockfile(
        deps, include_hashes=include_hashes, include_markers=include_markers
    )

    for line in pip_installable_lines:
        click.echo(line)

    sys.exit(0)
