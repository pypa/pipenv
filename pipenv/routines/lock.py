from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from pipenv.utils.dependencies import (
    get_pipfile_category_using_lockfile_section,
)
from pipenv.vendor import click

if TYPE_CHECKING:
    from pipenv._types.pipfile2 import LockfileSchema, MutableMappingT
    from pipenv.project import Project


def do_lock(
    project: Project,
    system: bool = False,
    clear: bool = False,
    pre: bool = False,
    write: bool = True,
    quiet: bool = False,
    pypi_mirror: str | None = None,
    categories: list[str] | None = None,
    extra_pip_args: list[str] | None = None,
) -> LockfileSchema:
    """Executes the freeze functionality."""
    if not pre:
        pre = project.settings.get("allow_prereleases")
    # Cleanup lockfile.
    if not categories:
        lockfile_categories = project.get_package_categories(for_lockfile=True)
    else:
        lockfile_categories = categories.copy()
        if "dev-packages" in categories:
            lockfile_categories.remove("dev-packages")
            lockfile_categories.insert(0, "develop")
        if "packages" in categories:
            lockfile_categories.remove("packages")
            lockfile_categories.insert(0, "default")
    # Create the lockfile.
    lockfile = project.lockfile(categories=lockfile_categories)
    for category in lockfile_categories:
        for k, v in lockfile.get(category, {}).copy().items():
            if not hasattr(v, "keys"):
                del lockfile[category][k]

    # Resolve package to generate constraints before resolving other categories
    for category in lockfile_categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_category, {})
        else:
            packages = project.get_pipfile_section(pipfile_category)

        if write:
            if not quiet:  # Alert the user of progress.
                click.echo(
                    "{} {} {}".format(
                        click.style("Locking"),
                        click.style(f"[{pipfile_category}]", fg="yellow"),
                        click.style("dependencies..."),
                    ),
                    err=True,
                )

        # Prune old lockfile category as new one will be created.
        with contextlib.suppress(KeyError):
            old_lock_data = lockfile.pop(category)

        from pipenv.utils.resolver import venv_resolve_deps

        # Mutates the lockfile
        venv_resolve_deps(
            packages,
            which=project._which,
            project=project,
            category=pipfile_category,
            clear=clear,
            pre=pre,
            allow_global=system,
            pypi_mirror=pypi_mirror,
            pipfile=packages,
            lockfile=lockfile,
            old_lock_data=old_lock_data,
            extra_pip_args=extra_pip_args,
        )

    # Overwrite any category packages with default packages.
    for category in lockfile_categories:
        if category == "default":
            pass
        if lockfile.get(category):
            lockfile[category].update(
                overwrite_with_default(lockfile.get("default", {}), lockfile[category])
            )
    if write:
        lockfile.update({"_meta": project.get_lockfile_meta()})
        project.write_lockfile(lockfile)
        if not quiet:
            click.echo(
                "{}".format(
                    click.style(
                        f"Updated Pipfile.lock ({project.get_lockfile_hash()})!",
                        bold=True,
                    )
                ),
                err=True,
            )
    else:
        return lockfile


def overwrite_with_default(
    default: MutableMappingT, dev: MutableMappingT
) -> MutableMappingT:
    for pkg in set(dev) & set(default):
        dev[pkg] = default[pkg]
    return dev
