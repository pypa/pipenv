import contextlib
import sys
import traceback

from pipenv.routines.context import RoutineContext
from pipenv.utils import err
from pipenv.utils.dependencies import (
    get_pipfile_category_using_lockfile_section,
)


def do_lock(project, ctx: RoutineContext):
    """Executes the freeze functionality.

    Per T_C.9: consumes :class:`~pipenv.routines.context.RoutineContext`
    for every user-facing input (``system`` / ``clear`` / ``pre`` /
    ``write`` / ``quiet`` / ``pypi_mirror`` / ``categories`` /
    ``extra_pip_args``).
    """
    target = ctx.target_env
    policy = ctx.install_policy
    sel = ctx.package_selection
    exec_opts = ctx.execution_options

    system = target.system
    pypi_mirror = target.pypi_mirror
    clear = policy.clear
    pre = policy.pre
    quiet = exec_opts.quiet
    write = exec_opts.write
    extra_pip_args = (
        list(exec_opts.extra_pip_args) if exec_opts.extra_pip_args else None
    )
    categories = list(sel.categories) if sel.categories else None

    if not pre:
        pre = project.settings.get("allow_prereleases")

    # Install any [build-system].requires packages first so they are available
    # when the resolver runs setup.py egg_info on local packages (issue #3651).
    from pipenv.routines.install import install_build_system_packages

    install_build_system_packages(
        project,
        allow_global=system,
        pypi_mirror=pypi_mirror,
    )

    # Cleanup lockfile.
    if not categories:
        lockfile_categories = project.pipfile.get_package_categories(for_lockfile=True)
    else:
        lockfile_categories = categories.copy()
        if "dev-packages" in categories:
            lockfile_categories.remove("dev-packages")
            lockfile_categories.insert(0, "develop")
        if "packages" in categories:
            lockfile_categories.remove("packages")
            lockfile_categories.insert(0, "default")
    # Create the lockfile.
    lockfile = project.lockfile.as_dict(categories=lockfile_categories)
    for category in lockfile_categories:
        for k, v in lockfile.get(category, {}).copy().items():
            if not hasattr(v, "keys"):
                del lockfile[category][k]

    # Determine whether to enforce default constraints on non-default categories.
    # When enabled (the default), resolved pins from the default category
    # (including transitive deps) are passed as constraints when resolving
    # non-default categories.  This prevents conflicting version pins across
    # categories (gh-4665, gh-4473).
    # Users can opt out via [pipenv] use_default_constraints = false in Pipfile.
    use_default_constraints = project.settings.get("use_default_constraints", True)

    # After resolving "default", we collect the resolved pins (including
    # transitive deps) to pass as constraints to subsequent categories.
    resolved_default_deps = None

    # Resolve package to generate constraints before resolving other categories
    for category in lockfile_categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        if project.pipfile.exists:
            packages = project.pipfile.parsed.get(pipfile_category, {})
        else:
            packages = project.pipfile.get_section(pipfile_category)

        if write:
            if not quiet:  # Alert the user of progress.
                err.print(
                    f"Locking [yellow][{pipfile_category}][/yellow] dependencies..."
                )

        # Prune old lockfile category as new one will be created.
        # Initialize to None so that downstream venv_resolve_deps gets a
        # well-defined sentinel when the category isn't in the lockfile
        # yet (first lock, or a newly-added category) — without this,
        # the unconditional reference at the venv_resolve_deps call
        # site below raises UnboundLocalError when the pop hits KeyError.
        old_lock_data = None
        with contextlib.suppress(KeyError):
            old_lock_data = lockfile.pop(category)

        from pipenv.utils.resolver import venv_resolve_deps

        # For non-default categories, pass resolved default deps as constraints
        # so the resolver produces compatible version pins.
        category_default_deps = None
        if category != "default" and use_default_constraints:
            category_default_deps = resolved_default_deps

        try:
            # Mutates the lockfile
            venv_resolve_deps(
                packages,
                which=project.venv_locator._which,
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
                resolved_default_deps=category_default_deps,
            )
        except RuntimeError:
            sys.exit(1)
        except Exception:
            err.print(traceback.format_exc())
            sys.exit(1)

        # After resolving default, capture the resolved pins for constraining
        # subsequent categories.
        if category == "default":
            resolved_default_deps = lockfile.get("default", {})

    # Overwrite any non-default category packages with default packages,
    # but only when use_default_constraints is enabled.
    if use_default_constraints:
        for category in lockfile_categories:
            if category == "default":
                continue
            if lockfile.get(category):
                lockfile[category].update(
                    overwrite_with_default(
                        lockfile.get("default", {}), lockfile[category]
                    )
                )
    if write:
        lockfile.update({"_meta": project.lockfile.meta()})
        project.lockfile.write(lockfile)
        if not quiet:
            err.print(
                f"Updated Pipfile.lock ({project.lockfile.hash()})!",
                style="bold",
            )
    else:
        return lockfile


def overwrite_with_default(default, dev):
    for pkg in set(dev) & set(default):
        dev[pkg] = default[pkg]
    return dev
