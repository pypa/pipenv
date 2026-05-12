import contextlib
import sys
import traceback
from pathlib import Path

from pipenv.routines.context import RoutineContext
from pipenv.utils import err
from pipenv.utils.dependencies import (
    get_pipfile_category_using_lockfile_section,
)


def _clear_parsed_manifest_cache(project) -> None:
    """Invalidate the Initiative G phase-1 parsed-manifest cache.

    Wired in T17: ``pipenv lock --clear`` (and ``pipenv install
    --clear`` via the same lock path) must wipe our pipenv-owned
    parsed-manifest cache in addition to pip's HTTP cache.  Without
    this, our cache becomes a poisoning surface the user can't easily
    nuke.

    Best-effort: failures here must never block the lock/install
    operation (the cache is opportunistic, not load-bearing in phase
    1).  ``ParsedManifestCache.clear_all`` already swallows ``rmtree``
    errors via ``ignore_errors=True``; this wrapper adds an outer
    guard against import-time / construction-time failures.
    """
    try:
        from pipenv.resolver.manifest_cache import ParsedManifestCache

        cache_root = Path(project.s.PIPENV_CACHE_DIR)
        ParsedManifestCache(cache_root).clear_all()
    except Exception:  # noqa: BLE001 — defensive; never block the resolve.
        pass


def _prefetch_index_manifests_if_enabled(
    project, lockfile_categories, *, clear: bool
) -> None:
    """Best-effort: pre-fetch top-level package indexes in parallel.

    Activated only when the user opted in via
    ``[pipenv] prefetch_index_manifests = true`` (or the
    ``PIPENV_PREFETCH_INDEX_MANIFESTS`` env-var override added in T18).
    All exceptions are swallowed so the lock continues with cold-cache
    behaviour on any failure mode.

    The underlying transport is pip's own ``PipSession`` (obtained via
    :func:`pipenv.utils.internet.get_requests_session`).  That guarantees
    pip's on-disk ``SafeFileCache`` is warmed as a side-effect of our
    fetches — the resolver subprocess invoked later will hit a warm
    cache without us having to reverse-engineer pip's CacheControl
    on-disk format.  Our own parsed-manifest cache (T7) is also
    populated for Phase 3 reuse.

    ``--clear`` short-circuits the prefetch: the user explicitly asked
    for a fresh resolution, so we honour that.

    No URL is logged at any verbosity level (URLs may carry credentials
    before stripping).  When verbose, a single summary line is emitted:
    ``Prefetched N package indexes in M.MMs.``

    Initiative G phase 2 — T19.  See ``initiative-g-phase1-2-plan.md``
    §T19 for the design rationale.
    """
    if clear:
        return
    try:
        if not project.settings.get("prefetch_index_manifests", False):
            return
    except Exception:
        return

    # Lazy imports — when the setting is disabled (the common case) the
    # cost of importing T7/T8/T9 modules is zero.  Same goes for the
    # ``time`` module and ``get_requests_session``.
    import time

    try:
        from pathlib import Path

        from pipenv.resolver.fetcher import ParallelFetcher
        from pipenv.resolver.manifest_cache import ParsedManifestCache
        from pipenv.resolver.pep691 import PEP691Client
        from pipenv.utils.internet import get_requests_session
    except Exception:
        # Phase-1 modules not present in this build, or something else
        # unexpected at import time.  Opt-out cleanly.
        return

    # ------------------------------------------------------------------
    # Collect (index_url, package_name) targets across categories x sources.
    # ------------------------------------------------------------------
    try:
        sources = project.sources.pipfile_sources()
    except Exception:
        return
    if not sources:
        return

    targets: list[tuple[str, str]] = []
    for category in lockfile_categories:
        pipfile_category = get_pipfile_category_using_lockfile_section(category)
        try:
            if project.pipfile.exists:
                packages = project.pipfile.parsed.get(pipfile_category, {})
            else:
                packages = project.pipfile.get_section(pipfile_category)
        except Exception:
            packages = {}
        if not packages:
            continue
        for package_name in packages.keys():
            for source in sources:
                index_url = source.get("url", "")
                if index_url:
                    targets.append((index_url, package_name))

    if not targets:
        return

    # ------------------------------------------------------------------
    # Resolve cache root and build a PipSession per verify-policy.
    # Sharing one session per (verify_ssl) value keeps the connection
    # pool warm while honouring per-source TLS-validation toggles.
    # ------------------------------------------------------------------
    try:
        cache_root = Path(project.s.PIPENV_CACHE_DIR) / "pipenv-manifests"
    except Exception:
        return

    sessions_by_verify: dict[bool, object] = {}
    for source in sources:
        verify = bool(source.get("verify_ssl", True))
        if verify in sessions_by_verify:
            continue
        try:
            sessions_by_verify[verify] = get_requests_session(verify_ssl=verify)
        except Exception:
            continue

    if not sessions_by_verify:
        return

    # For now, dispatch via whichever verify policy is most common
    # (defaulting to ``True`` when both exist).  Mixed-verify projects
    # are rare; the minority sources simply miss the prefetch and fall
    # back to pip's normal cold fetch — best-effort is the contract.
    # Per-source per-session fan-out is deferred to Phase 3.
    primary_verify = True if True in sessions_by_verify else False
    session = sessions_by_verify[primary_verify]

    try:
        cache = ParsedManifestCache(cache_root)
        client = PEP691Client(session, verify=primary_verify)
        fetcher = ParallelFetcher(client, cache)
    except Exception:
        return

    try:
        quiet = bool(project.s.is_quiet())
    except Exception:
        quiet = False
    try:
        verbose = bool(project.s.is_verbose())
    except Exception:
        verbose = False

    start = time.perf_counter()
    try:
        fetcher.populate(targets)
    except Exception:
        return
    elapsed = time.perf_counter() - start

    if verbose and not quiet:
        # Count unique package names — ``targets`` carries one
        # (source, name) tuple per source-fan-out, so the raw length
        # would overstate the work.
        unique_names = len({name for (_, name) in targets})
        try:
            err.print(
                f"[dim]Prefetched {unique_names} package indexes "
                f"in {elapsed:.2f}s.[/dim]"
            )
        except Exception:
            # Even logging failures must not break the lock.
            pass


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

    # T17: ``--clear`` must invalidate our parsed-manifest cache in
    # addition to pip's HTTP/resolution caches.  Runs at the top of
    # the lock so a cache wipe is visible to every resolve in this
    # invocation (and to the prefetch helper below, which is a no-op
    # under ``clear=True`` regardless — see T19).
    if clear:
        _clear_parsed_manifest_cache(project)

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

    # T19 (Initiative G phase 2): opt-in parallel manifest prefetch.
    # No-op unless ``[pipenv] prefetch_index_manifests`` is truthy (or
    # ``PIPENV_PREFETCH_INDEX_MANIFESTS`` is set).  Best-effort: any
    # failure is swallowed and the resolve loop below proceeds with
    # cold-cache behaviour.  Skipped entirely when ``--clear`` was
    # requested (the user wanted a fresh resolution).
    _prefetch_index_manifests_if_enabled(
        project, lockfile_categories, clear=clear
    )

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
