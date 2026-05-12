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

        # Empty-category fast path: when the Pipfile section is empty
        # (the common case for projects that don't use ``[dev-packages]``
        # or one of the optional groups) there is nothing to lock, so
        # we can skip the full resolver subprocess invocation entirely.
        # Profiling on a 30-package Pipfile (May 2026) showed the
        # second-category resolve cost ~6 s of wall time even with an
        # empty section: each call spawns the resolver subprocess,
        # re-imports pipenv + pip + the schema module, instantiates
        # ``Resolver`` + ``PackageFinder`` + ``Session``, and — when
        # ``use_default_constraints`` is on — walks the index for every
        # default-category transitive pin to confirm the empty
        # category doesn't conflict with anything.  All of that work
        # produces an empty section; popping ``old_lock_data`` above
        # already cleared any stale entries.  We just need to leave
        # an empty dict behind for the lockfile writer.
        if not packages:
            lockfile[category] = {}
            # ``resolved_default_deps`` stays ``None`` for ``default``
            # (correct: nothing to constrain non-default categories
            # with) and unchanged for non-default categories.
            continue

        from pipenv.utils.resolver import venv_resolve_deps

        # Build the resolver constraint set for this category.  Two sources:
        #
        # 1. Warm-relock prior locks (``old_lock_data``) — when a previous
        #    ``Pipfile.lock`` exists and the user did not pass ``--clear``,
        #    feed the previously-locked versions back as constraints so
        #    pip's ``PackageFinder`` short-circuits to the locked version
        #    instead of re-walking the index for the latest match.  This
        #    is the "pip install -c lockfile.txt" pattern applied to
        #    relocking.  We filter out entries whose locked version no
        #    longer satisfies the current Pipfile spec (the user may have
        #    tightened ``foo = ">=1.0"`` to ``foo = ">=2.0"``); those
        #    packages get a fresh resolve, the rest stay pinned.
        #    Transitive deps (not in the Pipfile) are kept as-is — they
        #    have no Pipfile spec to validate against and re-pinning them
        #    is exactly the win on large dependency graphs.
        #
        # 2. Cross-category default constraints — for non-default
        #    categories, the freshly-resolved default category is also
        #    fed as constraints so dev/test/etc. resolves don't pick
        #    versions that conflict with default (gh-4665, gh-4473).
        #    Gated by the ``use_default_constraints`` setting.
        #
        # Both sources are dicts keyed by package name, shaped like a
        # lockfile section.  When merged, cross-category wins for shared
        # keys (a freshly-resolved default pin should override an older
        # cached value with the same name).
        category_default_deps = {}
        if not clear and old_lock_data:
            category_default_deps.update(
                _filter_pinnable_lock_entries(old_lock_data, packages)
            )
        if category != "default" and use_default_constraints and resolved_default_deps:
            category_default_deps.update(resolved_default_deps)
        if not category_default_deps:
            category_default_deps = None

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


def _filter_pinnable_lock_entries(old_lock_data, pipfile_packages):
    """Return the subset of ``old_lock_data`` whose locked version is still
    valid as a constraint for the current Pipfile.

    Used by warm-relock to feed previously-locked versions back to pip's
    resolver as ``-c lockfile.txt``-style constraints.  This short-circuits
    ``find_all_candidates`` for packages whose Pipfile spec has not drifted,
    which is the bulk of the warm-path resolution cost.

    Filtering rules:

    - Drop non-dict entries (defensive; lockfile sections normally hold
      dicts but tolerant to legacy / hand-edited data).
    - Drop entries with no ``version`` (VCS / file / path entries — pip
      can't constrain on those, and ``get_constraints_from_resolved_deps``
      drops them anyway).
    - For packages declared in the Pipfile: only keep the pin if the
      locked version satisfies the Pipfile spec.  ``"*"`` and missing
      version specs are treated as "any" and always pass.  Pipfile
      entries with VCS / file / path / git keys are *dropped* (the
      Pipfile specifies a non-version source, so the locked version
      can't be used as a constraint).
    - For packages NOT in the Pipfile (transitive deps): always keep.
      We have no Pipfile spec to validate against, and transitives are
      where most of the warm-path speedup comes from.

    Parameters
    ----------
    old_lock_data : dict
        The popped previous lockfile section, keyed by package name as
        written in the lockfile (already canonicalized by pipenv when
        the lockfile was written).
    pipfile_packages : dict
        The Pipfile section for this category, keyed by package name
        as written in the Pipfile (may differ in casing from the
        lockfile canonical form).
    """
    from pipenv.patched.pip._vendor.packaging.specifiers import (
        InvalidSpecifier,
        SpecifierSet,
    )
    from pipenv.patched.pip._vendor.packaging.version import (
        InvalidVersion,
        Version,
    )
    from pipenv.utils.dependencies import pep423_name

    _VCS_OR_PATH_KEYS = ("git", "hg", "svn", "bzr", "file", "path")

    # Build a canonical-name lookup of the Pipfile section once so
    # the loop below is O(n) rather than O(n^2).
    pipfile_by_canon = {
        pep423_name(name): entry for name, entry in (pipfile_packages or {}).items()
    }

    valid = {}
    for name, entry in (old_lock_data or {}).items():
        if not isinstance(entry, dict):
            continue
        version = entry.get("version", "")
        # Strip a leading "==" since lockfile entries store
        # versions as ``"==X.Y.Z"`` while ``Version`` wants the bare
        # number.
        if isinstance(version, str) and version.startswith("=="):
            version = version[2:].strip()
        if not version:
            # No usable version pin (VCS / file / path lock entry).
            continue

        pipfile_entry = pipfile_by_canon.get(pep423_name(name))
        if pipfile_entry is None:
            # Transitive dep — keep the pin unconditionally.
            valid[name] = entry
            continue

        # Top-level entry: extract the version spec from the Pipfile.
        if isinstance(pipfile_entry, str):
            spec_str = pipfile_entry
        elif isinstance(pipfile_entry, dict):
            if any(k in pipfile_entry for k in _VCS_OR_PATH_KEYS):
                # Pipfile pins to a non-version source; lockfile version
                # is irrelevant here.
                continue
            spec_str = pipfile_entry.get("version", "")
        else:
            # Unknown shape — skip rather than guess.
            continue

        if not spec_str or spec_str == "*":
            # Open spec: any locked version is valid.
            valid[name] = entry
            continue

        try:
            if Version(version) in SpecifierSet(spec_str):
                valid[name] = entry
        except (InvalidSpecifier, InvalidVersion):
            # Malformed spec or non-PEP-440 version (e.g. local URL
            # pseudo-version); don't risk passing a bad constraint.
            continue

    return valid
