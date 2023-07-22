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

    pip_installable_lines = requirements_from_lockfile(
        deps, include_hashes=include_hashes, include_markers=include_markers
    )

    for line in pip_installable_lines:
        click.echo(line)

    sys.exit(0)
