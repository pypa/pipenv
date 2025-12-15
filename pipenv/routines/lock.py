import contextlib
import sys
import traceback

from pipenv.utils import err
from pipenv.utils.dependencies import (
    get_pipfile_category_using_lockfile_section,
)


def do_lock(
    project,
    system=False,
    clear=False,
    pre=False,
    write=True,
    quiet=False,
    pypi_mirror=None,
    categories=None,
    extra_pip_args=None,
    use_uv=None,
):
    """Executes the freeze functionality.

    Args:
        use_uv: If True, use UV resolver. If None, check PIPENV_USE_UV env var.
    """
    if not pre:
        pre = project.settings.get("allow_prereleases")

    # Determine whether to use UV resolver
    if use_uv is None:
        use_uv = project.s.PIPENV_USE_UV

    # Check if UV is available when requested
    if use_uv:
        from pipenv.utils.uv import is_uv_available

        if not is_uv_available():
            err.print(
                "[yellow]Warning: PIPENV_USE_UV is set but UV is not available. "
                "Falling back to pip resolver.[/yellow]"
            )
            use_uv = False

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

    if use_uv:
        # UV backend: resolve with UV and write pylock.toml only (no Pipfile.lock)
        _do_lock_uv(
            project=project,
            lockfile_categories=lockfile_categories,
            pre=pre,
            quiet=quiet,
        )
        # UV backend does not generate Pipfile.lock - only pylock.toml
        return None
    else:
        # Use default pip resolver
        _do_lock_pip(
            project=project,
            lockfile=lockfile,
            lockfile_categories=lockfile_categories,
            system=system,
            clear=clear,
            pre=pre,
            quiet=quiet,
            write=write,
            pypi_mirror=pypi_mirror,
            extra_pip_args=extra_pip_args,
        )

        # Overwrite any category packages with default packages.
        for category in lockfile_categories:
            if category == "default":
                pass
            if lockfile.get(category):
                lockfile[category].update(
                    overwrite_with_default(
                        lockfile.get("default", {}), lockfile[category]
                    )
                )
        if write:
            lockfile.update({"_meta": project.get_lockfile_meta()})
            project.write_lockfile(lockfile)
            if not quiet:
                err.print(
                    f"Updated Pipfile.lock ({project.get_lockfile_hash()})!",
                    style="bold",
                )
        else:
            return lockfile


def _do_lock_pip(
    project,
    lockfile,
    lockfile_categories,
    system,
    clear,
    pre,
    quiet,
    write,
    pypi_mirror,
    extra_pip_args,
):
    """Resolve dependencies using pip's resolver."""
    from pipenv.utils.resolver import venv_resolve_deps

    for category in lockfile_categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        if project.pipfile_exists:
            packages = project.parsed_pipfile.get(pipfile_category, {})
        else:
            packages = project.get_pipfile_section(pipfile_category)

        if write:
            if not quiet:
                err.print(
                    f"Locking [yellow][{pipfile_category}][/yellow] dependencies..."
                )

        # Prune old lockfile category as new one will be created.
        with contextlib.suppress(KeyError):
            old_lock_data = lockfile.pop(category)

        try:
            # Mutates the lockfile
            venv_resolve_deps(
                packages,
                which=project._which,
                project=project,
                pipfile_category=pipfile_category,
                clear=clear,
                pre=pre,
                allow_global=system,
                pypi_mirror=pypi_mirror,
                pipfile=packages,
                lockfile=lockfile,
                old_lock_data=old_lock_data,
                extra_pip_args=extra_pip_args,
            )
        except RuntimeError:
            sys.exit(1)
        except Exception:
            err.print(traceback.format_exc())
            sys.exit(1)


def _do_lock_uv(
    project,
    lockfile_categories,
    pre,
    quiet,
):
    """Resolve dependencies using UV's resolver with index restriction enforcement.

    UV backend outputs to pylock.toml format only. No Pipfile.lock is generated.
    """
    from pipenv.utils.uv import uv_lock_to_pylock

    if not quiet:
        err.print("Using [bold cyan]UV[/bold cyan] resolver → pylock.toml...")

    try:
        # Gather all deps and sources from Pipfile
        sources = project.pipfile_sources(expand_vars=True)

        # Build index_lookup from Pipfile package specs
        # Track which packages belong to which category for proper grouping
        index_lookup = {}
        all_deps = {}
        category_packages = {}  # Track packages by category

        for category in lockfile_categories:
            pipfile_category = get_pipfile_category_using_lockfile_section(category)
            if project.pipfile_exists:
                packages = project.parsed_pipfile.get(pipfile_category, {})
            else:
                packages = project.get_pipfile_section(pipfile_category)

            category_packages[category] = set()
            for pkg_name, pkg_spec in packages.items():
                all_deps[pkg_name] = pkg_spec
                category_packages[category].add(pkg_name.lower().replace("_", "-"))
                # Track index assignments
                if isinstance(pkg_spec, dict) and "index" in pkg_spec:
                    index_lookup[pkg_name.lower()] = pkg_spec["index"]

        # Resolve with UV and get pylock.toml data
        pylock_data = uv_lock_to_pylock(
            project=project,
            deps=all_deps,
            sources=sources,
            index_lookup=index_lookup,
            lockfile_categories=lockfile_categories,
            category_packages=category_packages,
            pre=pre,
        )

        # Write pylock.toml
        from pathlib import Path

        from pipenv.utils.pylock import PylockFile

        pylock_path = Path(project.pylock_output_path)
        pylock_file = PylockFile(path=pylock_path, data=pylock_data)
        pylock_file.write()

        if not quiet:
            err.print(f"Wrote [bold green]{pylock_path}[/bold green]")

    except RuntimeError as e:
        err.print(f"[red]UV resolution failed: {e}[/red]")
        sys.exit(1)
    except Exception:
        err.print(traceback.format_exc())
        sys.exit(1)


def overwrite_with_default(default, dev):
    for pkg in set(dev) & set(default):
        dev[pkg] = default[pkg]
    return dev
