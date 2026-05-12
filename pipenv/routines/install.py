import os
import queue
import sys
import warnings
from collections import defaultdict
from dataclasses import replace
from tempfile import NamedTemporaryFile

from pipenv import environments, exceptions
from pipenv.patched.pip._internal.exceptions import PipError
from pipenv.routines.context import RoutineContext
from pipenv.routines.lock import do_lock
from pipenv.utils import console, err, fileutils
from pipenv.utils.dependencies import (
    add_index_to_pipfile_with_trust_check,
    expansive_install_req_from_line,
    get_lockfile_section_using_pipfile_category,
    import_requirements,
    install_req_from_pipfile,
    normalize_editable_path_for_pip,
)
from pipenv.utils.dependencies import (
    python_version as _python_version_for_path,
)
from pipenv.utils.indexes import get_source_list
from pipenv.utils.internet import download_file, is_valid_url
from pipenv.utils.pip import (
    get_trusted_hosts,
    pip_install_deps,
)
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.project import ensure_project
from pipenv.utils.shell import temp_environ


def _target_marker_environment(project, allow_global=False):
    """Build a marker environment dict reflecting the venv's Python version.

    ``dep.markers.evaluate()`` defaults to marker variables from the *currently
    running* interpreter.  When pipenv runs under a different Python than the
    virtualenv it manages (e.g. ``pipenv sync --python 3.12`` invoked by a
    system Python 3.10), evaluating markers in the host environment incorrectly
    filters out packages that actually apply to the target venv.  See #6647.

    When ``allow_global=True`` the installation target is the system interpreter
    (the same one running pipenv), so no override is needed.

    Returns a dict suitable for passing as ``environment=`` to ``Marker.evaluate``
    that overrides ``python_version`` and ``python_full_version``, or *None*
    if no override is needed (global install, venv matches host, or the venv's
    version can't be determined).
    """
    if allow_global:
        return None
    try:
        if not project.venv_locator.exists:
            return None
        venv_python = project.venv_locator._which("python")
    except Exception:
        return None
    if not venv_python:
        return None
    try:
        venv_full_version = _python_version_for_path(str(venv_python))
    except Exception:
        venv_full_version = None
    if not venv_full_version:
        return None
    running_full = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if venv_full_version == running_full:
        return None
    parts = venv_full_version.split(".")
    if len(parts) < 2:
        return None
    return {
        "python_version": ".".join(parts[:2]),
        "python_full_version": venv_full_version,
    }


def _should_use_no_binary(pkg_name, extra_pip_args):
    """Return True if --no-binary should be recorded in the Pipfile for pkg_name.

    Checks both ``extra_pip_args`` (e.g. ``["--no-binary", "cartopy"]``) and the
    ``PIP_NO_BINARY`` environment variable (e.g. ``PIP_NO_BINARY=cartopy``).
    """
    if not pkg_name:
        return False

    # Normalise the name the same way pip does internally so that
    # "Cartopy", "cartopy", and "cartopy" all match.
    def _normalise(name):
        return name.lower().replace("-", "_").replace(".", "_")

    pkg_norm = _normalise(pkg_name)

    def _name_matches(value):
        """Return True if value is ':all:' or contains pkg_name."""
        if value.strip() == ":all:":
            return True
        return any(
            _normalise(part.strip()) == pkg_norm
            for part in value.split(",")
            if part.strip()
        )

    # Check extra_pip_args
    if extra_pip_args:
        i = 0
        while i < len(extra_pip_args):
            arg = extra_pip_args[i]
            if arg == "--no-binary" and i + 1 < len(extra_pip_args):
                if _name_matches(extra_pip_args[i + 1]):
                    return True
                i += 2
            elif arg.startswith("--no-binary="):
                val = arg.split("=", 1)[1]
                if _name_matches(val):
                    return True
                i += 1
            else:
                i += 1

    # Check PIP_NO_BINARY environment variable
    pip_no_binary = os.environ.get("PIP_NO_BINARY", "")
    if pip_no_binary and _name_matches(pip_no_binary):
        return True

    return False


def handle_new_packages(
    project,
    ctx: RoutineContext,
    *,
    perform_upgrades: bool = True,
):
    """Add user-requested packages to the Pipfile and optionally upgrade.

    Per T_C.6: consumes :class:`RoutineContext` for the bundled inputs
    (packages, editables, dev/pre/system/index/extra_pip_args/etc.).
    ``perform_upgrades`` stays as a per-call kwarg because it is a
    call-site intent flag (``do_install`` flips it off when
    ``skip_lock`` is set), not a property of the user's CLI invocation.
    """
    from pipenv.routines.update import do_update

    sel = ctx.package_selection
    target = ctx.target_env
    policy = ctx.install_policy
    exec_opts = ctx.execution_options

    packages = list(sel.packages) if sel.packages else []
    editable_packages = list(sel.editable_packages) if sel.editable_packages else []
    pipfile_categories = list(sel.categories) if sel.categories else []
    extra_pip_args = list(exec_opts.extra_pip_args) if exec_opts.extra_pip_args else []
    index = sel.index

    new_packages = []
    if packages or editable_packages:

        pkg_list = packages + [
            f"-e {normalize_editable_path_for_pip(pkg)}" for pkg in editable_packages
        ]

        for pkg_line in pkg_list:
            console.print(f"Installing {pkg_line}...", style="bold green")
            with temp_environ():
                if not target.system:
                    os.environ["PIP_USER"] = "0"
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]

                try:
                    pkg_requirement, _ = expansive_install_req_from_line(
                        pkg_line, expand_env=True
                    )
                    if index:
                        source = project.sources.get_index_by_name(index)
                        default_index = project.sources.get_default_index()["name"]
                        if not source:
                            index_name = add_index_to_pipfile_with_trust_check(project, index)
                            if index_name != default_index:
                                pkg_requirement.index = index_name
                        elif source["name"] != default_index:
                            pkg_requirement.index = source["name"]
                except ValueError as e:
                    err.print(f"[red]WARNING[/red]: {e}")
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Installation Failed"
                        )
                    )
                    sys.exit(1)

                try:
                    no_binary = _should_use_no_binary(
                        pkg_requirement.name if pkg_requirement else None,
                        extra_pip_args,
                    )
                    if pipfile_categories:
                        for category in pipfile_categories:
                            added, cat, normalized_name = project.add_package_to_pipfile(
                                pkg_requirement,
                                pkg_line,
                                sel.dev,
                                category,
                                no_binary=no_binary,
                            )
                            if added:
                                new_packages.append((normalized_name, cat))
                    else:
                        added, cat, normalized_name = project.add_package_to_pipfile(
                            pkg_requirement, pkg_line, sel.dev, no_binary=no_binary
                        )
                        if added:
                            new_packages.append((normalized_name, cat))
                except ValueError:
                    import traceback

                    err.print(f"[bold][red]Error:[/red][/bold] {traceback.format_exc()}")
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Failed adding package to Pipfile"
                        )
                    )

                console.print(
                    environments.PIPENV_SPINNER_OK_TEXT.format("Installation Succeeded")
                )

        # Update project settings with pre-release preference.
        if policy.pre:
            project.settings.update({"allow_prereleases": policy.pre})

    # Use the update routine for new packages
    if perform_upgrades and (packages or editable_packages):
        try:
            # Post T_C.8 ``do_update`` consumes ``RoutineContext``. Build
            # a context that mirrors the pre-migration kwargs verbatim
            # (dev / pre / packages / editables / pypi_mirror / index /
            # extra_pip_args / categories) so the post-install upgrade
            # pass behaves identically.
            update_ctx = RoutineContext.from_cli(
                pypi_mirror=target.pypi_mirror,
                pre=policy.pre,
                packages=tuple(packages),
                editable_packages=tuple(editable_packages),
                categories=tuple(pipfile_categories),
                dev=sel.dev,
                index=index,
                extra_pip_args=tuple(extra_pip_args),
            )
            do_update(project, update_ctx)
            return new_packages, True
        except Exception:
            for pkg_name, category in new_packages:
                project.remove_package_from_pipfile(pkg_name, category)
            raise

    return new_packages, False


def handle_lockfile(project, ctx: RoutineContext):
    """Handle the lockfile, updating if necessary.

    Per T_C.6: consumes :class:`RoutineContext` for the bundled inputs
    (packages, install-policy flags, target-env flags). Per T_C.7,
    ``handle_outdated_lockfile`` and ``handle_missing_lockfile`` are
    now on ``RoutineContext`` too; only the call-state strings
    (``old_hash`` / ``new_hash``) remain as direct args.
    """
    sel = ctx.package_selection
    target = ctx.target_env
    policy = ctx.install_policy

    packages = list(sel.packages) if sel.packages else []

    if (
        (project.lockfile.exists and not policy.ignore_pipfile)
        and not policy.skip_lock
        and not packages
    ):
        old_hash = project.lockfile.hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if policy.deploy:
                console.print(
                    f"Your Pipfile.lock ({old_hash}) is out of date. Expected: ({new_hash}).",
                    style="red",
                )
                raise exceptions.DeployException
            elif not target.system:
                handle_outdated_lockfile(
                    project,
                    ctx,
                    old_hash=old_hash,
                    new_hash=new_hash,
                )
    elif not project.lockfile.exists and not policy.skip_lock:
        handle_missing_lockfile(project, ctx)


def handle_outdated_lockfile(
    project,
    ctx: RoutineContext,
    *,
    old_hash,
    new_hash,
):
    """Handle an outdated lockfile.

    Per T_C.7: consumes :class:`RoutineContext` for target-env / policy
    flags. ``old_hash`` and ``new_hash`` stay as call-state strings
    (see design doc section 3, "other" group).
    """
    target = ctx.target_env
    policy = ctx.install_policy

    if (target.system or target.allow_global) and not (project.s.PIPENV_VIRTUALENV):
        err.print(
            f"Pipfile.lock ({old_hash}) out of date, but installation uses --system so"
            f" re-building lockfile must happen in isolation."
            f" Please rebuild lockfile in a virtualenv. Continuing anyway...",
            style="yellow",
        )
    else:
        if old_hash:
            msg = (
                "Pipfile.lock ({0}) out of date: run `pipenv lock` to update to ({1})..."
            )
        else:
            msg = "Pipfile.lock is corrupt, replaced with ({1})..."
        err.print(
            msg.format(old_hash, new_hash),
            style="bold yellow",
        )
        if not policy.skip_lock:
            # do_lock honours ctx.execution_options.write (defaults True).
            # Drop the categories selection so the lock spans every
            # configured Pipfile section, matching the pre-T_C.9 call
            # that passed ``categories=None`` explicitly.
            lock_ctx = replace(
                ctx,
                package_selection=replace(
                    ctx.package_selection, categories=()
                ),
            )
            do_lock(project, lock_ctx)


def handle_missing_lockfile(project, ctx: RoutineContext):
    """Handle a missing lockfile by creating one.

    Per T_C.7: consumes :class:`RoutineContext` for the bundled
    target-env / install-policy flags.
    """
    target = ctx.target_env

    if (target.system or target.allow_global) and not project.s.PIPENV_VIRTUALENV:
        raise exceptions.PipenvOptionsError(
            "--system",
            "--system is intended to be used for Pipfile installation, "
            "not installation of specific packages. Aborting.\n"
            "See also: --deploy flag.",
        )
    else:
        if not project.s.is_quiet():
            err.print(
                "Pipfile.lock not found, creating...",
                style="bold",
            )
        # do_lock honours ctx.execution_options.write (defaults True).
        # The pre-T_C.9 call here omitted ``categories`` so the lock
        # spans every configured Pipfile section; ensure ctx mirrors
        # that by clearing any category selection from the parent ctx.
        lock_ctx = replace(
            ctx,
            package_selection=replace(
                ctx.package_selection, categories=()
            ),
        )
        do_lock(project, lock_ctx)


def do_install(project, ctx: RoutineContext) -> None:
    """Install user-requested packages and/or apply the Pipfile.

    Consumes a :class:`~pipenv.routines.context.RoutineContext` per the
    design doc (``docs/dev/initiative-c-design.md`` sections 2 and 6).
    Post T_C.7, every helper in this module is also on ``RoutineContext``.
    """
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("ignore", category=ResourceWarning)

    # Normalize editable paths up front and fold them back into the
    # context so downstream readers see the canonicalised values.
    pkg_sel = ctx.package_selection
    editable_normalized = tuple(
        normalize_editable_path_for_pip(p) for p in pkg_sel.editable_packages if p
    )
    ctx = replace(
        ctx,
        package_selection=replace(pkg_sel, editable_packages=editable_normalized),
    )

    # Pin default categories if the user didn't pass any. Matches the
    # pre-migration ``do_install`` behaviour exactly.
    if not ctx.package_selection.categories:
        default_cats = (
            ("dev-packages",) if ctx.package_selection.dev else ("packages",)
        )
        ctx = replace(
            ctx,
            package_selection=replace(
                ctx.package_selection, categories=default_cats
            ),
        )

    # Local working copies of the flags / selections used below.
    target = ctx.target_env
    policy = ctx.install_policy
    sel = ctx.package_selection

    pipfile_categories = list(sel.categories)
    new_packages: list[tuple[str, str]] = []

    ensure_project(
        project,
        python=target.python,
        system=target.system,
        warn=True,
        deploy=policy.deploy,
        skip_requirements=False,
        pypi_mirror=target.pypi_mirror,
        site_packages=target.site_packages,
        pipfile_categories=pipfile_categories,
        lockfile_only=policy.ignore_pipfile,
    )

    do_install_validations(project, ctx, requirements_directory)

    do_init(project, ctx)

    if not policy.deploy:
        new_packages, _ = handle_new_packages(
            project,
            ctx,
            perform_upgrades=not policy.skip_lock,
        )

    try:
        # When --dev was requested, install both default and dev categories
        # from the Pipfile (the historical do_install behaviour).
        install_categories = (
            ("packages", "dev-packages") if sel.dev else tuple(pipfile_categories)
        )
        deps_ctx = replace(
            ctx,
            package_selection=replace(
                ctx.package_selection, categories=install_categories
            ),
        )
        do_install_dependencies(project, deps_ctx, requirements_directory)
    except Exception as e:
        # If we fail to install, remove the package from the Pipfile.
        for pkg_name, category in new_packages:
            project.remove_package_from_pipfile(pkg_name, category)
        raise e

    sys.exit(0)


def do_install_validations(
    project,
    ctx: RoutineContext,
    requirements_directory,
):
    """Validate Pipfile / lockfile presence and process a requirements file.

    Per T_C.7: consumes :class:`RoutineContext` for the bundled user-facing
    inputs (packages, dev/pre/deploy/skip_lock/system flags, categories,
    requirementstxt). ``requirements_directory`` stays as a per-call arg
    because it is a runtime-created temp dir, not a user input.
    """
    sel = ctx.package_selection
    target = ctx.target_env
    policy = ctx.install_policy

    package_args = list(sel.package_args)
    categories = list(sel.categories) if sel.categories else []
    requirementstxt = sel.requirementstxt

    # Don't attempt to install develop and default packages if Pipfile is missing
    if not project.pipfile_exists and not (package_args or sel.dev):
        if not (policy.ignore_pipfile or policy.deploy):
            raise exceptions.PipfileNotFound(project.path_to("Pipfile"))
        elif (
            (policy.skip_lock and policy.deploy) or policy.ignore_pipfile
        ) and not project.lockfile.any_exists:
            raise exceptions.LockfileNotFound(project.path_to("Pipfile.lock"))
    # NOTE: The pre-context implementation loaded ``allow_prereleases``
    # from ``project.settings`` into a local ``pre`` variable here, but the
    # value was never consumed further inside this validator. Downstream
    # helpers re-read ``project.settings`` themselves, so the dead read is
    # omitted in the context-based signature.
    remote = requirementstxt and is_valid_url(requirementstxt)
    if "default" in categories:
        raise exceptions.PipenvUsageError(
            message="Cannot install to category `default`-- did you mean `packages`?"
        )
    if "develop" in categories:
        raise exceptions.PipenvUsageError(
            message="Cannot install to category `develop`-- did you mean `dev-packages`?"
        )
    # Automatically use an activated virtualenv.
    system = target.system
    if project.s.PIPENV_USE_SYSTEM:
        system = True
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"
    # Check if the file is remote or not
    if remote:
        err.print(
            "Remote requirements file provided! Downloading...",
            style="bold",
        )
        fd = NamedTemporaryFile(
            prefix="pipenv-", suffix="-requirement.txt", dir=requirements_directory
        )
        temp_reqs = fd.name
        requirements_url = requirementstxt
        # Download requirements file
        try:
            download_file(requirements_url, temp_reqs, project.s.PIPENV_MAX_RETRIES)
        except OSError:
            fd.close()
            os.unlink(temp_reqs)
            err.print(
                f"Unable to find requirements file at {requirements_url}.",
                style="red",
            )
            sys.exit(1)
        finally:
            fd.close()
        # Replace the url with the temporary requirements file
        requirementstxt = temp_reqs
    if requirementstxt:
        error, traceback = None, None
        err.print(
            "Requirements file provided! Importing into Pipfile...",
            style="bold",
        )
        try:
            import_requirements(
                project,
                r=project.path_to(requirementstxt),
                dev=sel.dev,
                categories=categories,
            )
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = project.path_to(requirementstxt)
            error = f"Unexpected syntax in {req_path}. Are you sure this is a requirements.txt style file?"
            traceback = e
        except AssertionError as e:
            error = (
                "Requirements file doesn't appear to exist. Please ensure the file exists in your "
                "project directory or you provided the correct path."
            )
            traceback = e
        finally:
            if error and traceback:
                console.print(error, style="red")
                err.print(str(traceback), style="yellow")
                sys.exit(1)


def install_build_system_packages(
    project,
    allow_global=False,
    pypi_mirror=None,
    requirements_dir=None,
):
    """Install packages specified in [build-system].requires from the Pipfile.

    These packages are installed before any other packages are resolved or installed,
    so they are available when building packages that import non-standard tools in
    their setup.py (e.g. custom setuptools wrappers).

    Example Pipfile::

        [build-system]
        requires = ["stwrapper", "setuptools>=40.8.0", "wheel"]

    :param project: The pipenv project instance.
    :param allow_global: Whether to use the global Python environment.
    :param pypi_mirror: Optional PyPI mirror URL.
    :param requirements_dir: Optional temporary directory for requirements files.
    """
    build_requires = project.pipfile_build_requires
    if not build_requires:
        return

    if not requirements_dir:
        requirements_dir = fileutils.create_tracked_tempdir(
            suffix="-requirements", prefix="pipenv-"
        )

    if not project.s.is_quiet():
        err.print(
            "Installing [build-system] dependencies...",
            style="bold",
        )

    sources = get_source_list(
        project,
        index=None,
        extra_indexes=None,
        trusted_hosts=get_trusted_hosts(),
        pypi_mirror=pypi_mirror,
    )

    procs = queue.Queue(maxsize=1)
    cmds = pip_install_deps(
        project,
        deps=build_requires,
        sources=sources,
        allow_global=allow_global,
        ignore_hashes=True,  # Build deps are not hashed
        no_deps=False,
        requirements_dir=requirements_dir,
        use_pep517=True,
        extra_pip_args=None,
    )

    for c in cmds:
        procs.put(c)
        _cleanup_procs(project, procs)


def do_install_dependencies(
    project,
    ctx: RoutineContext,
    requirements_dir,
):
    """
    Executes the installation functionality.

    Per T_C.7: consumes :class:`RoutineContext` for the bundled user-facing
    inputs (dev / categories / bare / allow_global / pypi_mirror /
    extra_pip_args / skip_lock / ignore_hashes). ``requirements_dir`` is
    a runtime-created temp dir, so it stays as a per-call arg.
    """
    sel = ctx.package_selection
    target = ctx.target_env
    policy = ctx.install_policy
    exec_opts = ctx.execution_options

    # Install any build-system packages first so they are available when
    # building packages that use non-standard setup.py tooling.
    install_build_system_packages(
        project,
        allow_global=target.allow_global,
        pypi_mirror=target.pypi_mirror,
        requirements_dir=requirements_dir,
    )
    procs = queue.Queue(maxsize=1)
    categories = list(sel.categories) if sel.categories else []
    if not categories:
        if sel.dev:
            categories = ["packages", "dev-packages"]
        else:
            categories = ["packages"]

    # ``skip_lock`` implicitly forces ``ignore_hashes`` ON (you cannot hash
    # packages you never resolved). Compute the effective flag locally so
    # the frozen ``ctx`` is not mutated mid-loop.
    effective_ignore_hashes = exec_opts.ignore_hashes or policy.skip_lock

    for pipfile_category in categories:
        lockfile = None
        pipfile = None
        if policy.skip_lock:
            if not exec_opts.bare and not project.s.is_quiet():
                console.print("Installing dependencies from Pipfile...", style="bold")
            pipfile = project.get_pipfile_section(pipfile_category)
        else:
            lockfile = project.get_or_create_lockfile(categories=categories)
            if not exec_opts.bare and not project.s.is_quiet():
                lockfile_category = get_lockfile_section_using_pipfile_category(
                    pipfile_category
                )
                lockfile_type = (
                    "pylock.toml"
                    if project.lockfile.pylock_exists
                    and (project.settings.use_pylock or not project.lockfile.exists)
                    else "Pipfile.lock"
                )
                lockfile_hash = lockfile["_meta"].get("hash", {}).get("sha256", "") or ""
                hash_suffix = f"({lockfile_hash[-6:]})" if lockfile_hash else ""
                console.print(
                    f"Installing dependencies from {lockfile_type} "
                    f"[{lockfile_category}]{hash_suffix}...",
                    style="bold",
                )
        if policy.skip_lock:
            deps_list = []
            for req_name, pipfile_entry in pipfile.items():
                install_req, markers, req_line = install_req_from_pipfile(
                    req_name, pipfile_entry
                )
                deps_list.append(
                    (
                        install_req,
                        req_line,
                    )
                )
        else:
            lockfile_category = get_lockfile_section_using_pipfile_category(
                pipfile_category
            )
            deps_list = list(
                lockfile.get_requirements(
                    dev=sel.dev, only=False, categories=[lockfile_category]
                )
            )
        editable_or_vcs_deps = [
            (dep, pip_line) for dep, pip_line in deps_list if (dep.link and dep.editable)
        ]
        normal_deps = [
            (dep, pip_line)
            for dep, pip_line in deps_list
            if not (dep.link and dep.editable)
        ]

        # Fold the call-site overrides (sequential_deps, effective
        # ignore_hashes, no_deps derived from policy.skip_lock) back into
        # a per-iteration ctx for batch_install.
        iter_ctx = replace(
            ctx,
            install_policy=replace(policy, skip_lock=policy.skip_lock),
            execution_options=replace(
                exec_opts,
                ignore_hashes=effective_ignore_hashes,
                no_deps=not policy.skip_lock,
            ),
        )

        if policy.skip_lock:
            lockfile_section = pipfile
        else:
            lockfile_category = get_lockfile_section_using_pipfile_category(
                pipfile_category
            )
            lockfile_section = lockfile[lockfile_category]
        batch_install(
            project,
            iter_ctx,
            normal_deps,
            lockfile_section,
            procs,
            requirements_dir,
            sequential_deps=editable_or_vcs_deps,
        )

        if not procs.empty():
            _cleanup_procs(project, procs)


def batch_install_iteration(
    project,
    ctx: RoutineContext,
    deps_to_install,
    sources,
    procs,
    requirements_dir,
):
    """Run a single pip-install iteration for a batch of deps.

    Per T_C.7: consumes :class:`RoutineContext` for the install flags
    (``allow_global`` / ``no_deps`` / ``ignore_hashes`` / ``extra_pip_args``).
    The data-flow args (``deps_to_install``, ``sources``, ``procs``,
    ``requirements_dir``) are call-state, not user-facing inputs, so they
    stay as positional params (design doc section 3, "other" group).

    TODO(swarm): Design doc section 3 names a future ``BatchInstall``
    object to bundle these call-state args. Out of scope for T_C.7
    (T_C.4 sign-off deferred richer per-routine operation types).
    """
    target = ctx.target_env
    exec_opts = ctx.execution_options

    with temp_environ():
        if not target.allow_global:
            os.environ["PIP_USER"] = "0"
            if "PYTHONHOME" in os.environ:
                del os.environ["PYTHONHOME"]
        if "GIT_CONFIG" in os.environ:
            del os.environ["GIT_CONFIG"]
        cmds = pip_install_deps(
            project,
            deps=deps_to_install,
            sources=sources,
            allow_global=target.allow_global,
            ignore_hashes=exec_opts.ignore_hashes,
            no_deps=exec_opts.no_deps,
            requirements_dir=requirements_dir,
            use_pep517=True,
            extra_pip_args=list(exec_opts.extra_pip_args)
            if exec_opts.extra_pip_args
            else None,
        )

        for c in cmds:
            procs.put(c)
            _cleanup_procs(project, procs)


def batch_install(
    project,
    ctx: RoutineContext,
    deps_list,
    lockfile_section,
    procs,
    requirements_dir,
    *,
    sequential_deps=None,
):
    """Install a batch of deps, sharding by index where appropriate.

    Per T_C.7: consumes :class:`RoutineContext` for the install flags
    (``allow_global`` / ``no_deps`` / ``ignore_hashes`` / ``extra_pip_args`` /
    ``pypi_mirror``). The data-flow args (``deps_list``, ``lockfile_section``,
    ``procs``, ``requirements_dir``) and the per-batch ``sequential_deps``
    intent stay as direct params (design doc section 3, "other" group).
    """
    target = ctx.target_env
    exec_opts = ctx.execution_options

    if sequential_deps is None:
        sequential_deps = []

    # Collect packages that require --no-binary from the lockfile / pipfile section.
    # This ensures that packages installed via "pipenv install" from an existing
    # Pipfile/lockfile honour the no_binary flag that was recorded at install time.
    no_binary_packages = [
        pkg_name
        for pkg_name, entry in lockfile_section.items()
        if isinstance(entry, dict) and entry.get("no_binary")
    ]
    extra_pip_args = (
        list(exec_opts.extra_pip_args) if exec_opts.extra_pip_args else []
    )
    if no_binary_packages:
        extra_pip_args = list(extra_pip_args)
        extra_pip_args += ["--no-binary", ",".join(no_binary_packages)]

    deps_to_install = deps_list[:]
    deps_to_install.extend(sequential_deps)
    # Evaluate markers against the target venv's Python version rather than
    # the interpreter pipenv itself runs under.  See #6647.
    marker_env = _target_marker_environment(project, allow_global=target.allow_global)
    filtered_deps = []
    for dep, pip_line in deps_to_install:
        # Skip packages whose environment markers don't match the target
        # venv's Python environment (e.g. python_version < '3.11' when
        # targeting Python 3.11).  This keeps pipenv install -r and pipenv
        # sync consistent and avoids false-positive "Ignoring …" warnings
        # when the host python differs from the venv python.
        # KeyError can occur for pylock.toml markers that use non-PEP-508
        # variables like 'dependency_groups'; those are already filtered at
        # the lockfile level so we simply include the package here.
        try:
            markers_match = not dep.markers or dep.markers.evaluate(
                environment=marker_env
            )
        except KeyError:
            markers_match = True
        if not markers_match:
            err.print(
                f"Ignoring [bold]{dep.name}[/bold]: markers "
                f"[yellow]{dep.markers!r}[/yellow] don't match your environment",
                style="dim",
            )
            continue
        if not project.environment.is_satisfied(dep):
            filtered_deps.append((dep, pip_line))
    deps_to_install = filtered_deps
    search_all_sources = project.settings.get("install_search_all_sources", False)
    sources = get_source_list(
        project,
        index=None,
        extra_indexes=None,
        trusted_hosts=get_trusted_hosts(),
        pypi_mirror=target.pypi_mirror,
    )
    # Build a per-call ctx that carries the (possibly-augmented)
    # ``extra_pip_args`` down to ``batch_install_iteration``.
    iter_ctx = replace(
        ctx,
        execution_options=replace(exec_opts, extra_pip_args=tuple(extra_pip_args)),
    )

    if search_all_sources:
        dependencies = [pip_line for _, pip_line in deps_to_install]
        batch_install_iteration(
            project,
            iter_ctx,
            dependencies,
            sources,
            procs,
            requirements_dir,
        )
    else:
        # Sort the dependencies out by index -- include editable/vcs in the default group
        deps_by_index = defaultdict(list)
        for dependency, pip_line in deps_to_install:
            index = project.sources.default["name"]
            if dependency.name and dependency.name in lockfile_section:
                entry = lockfile_section[dependency.name]
                if isinstance(entry, dict) and "index" in entry:
                    index = entry["index"]
            deps_by_index[index].append(pip_line)
        # Treat each index as its own pip install phase
        for index_name, dependencies in deps_by_index.items():
            try:
                install_source = next(filter(lambda s: s["name"] == index_name, sources))
                batch_install_iteration(
                    project,
                    iter_ctx,
                    dependencies,
                    [install_source],
                    procs,
                    requirements_dir,
                )
            except StopIteration:  # noqa: PERF203
                console.print(
                    f"Unable to find {index_name} in sources, please check dependencies: {dependencies}",
                    style="bold red",
                )
                sys.exit(1)


def _cleanup_procs(project, procs):
    while not procs.empty():
        c = procs.get()
        try:
            out, err = c.communicate()
        except AttributeError:
            out, err = c.stdout, c.stderr
        failed = c.returncode != 0
        if project.s.is_verbose():
            console.print(out.strip() or err.strip(), style="yellow")
        # The Installation failed...
        if failed:
            # The Installation failed...
            # We echo both c.stdout and c.stderr because pip returns error details on out.
            err = err.strip().splitlines() if err else []
            out = out.strip().splitlines() if out else []
            err_lines = [line for message in [out, err] for line in message]
            deps = getattr(c, "deps", {}).copy()
            # Return the subprocess' return code.
            raise exceptions.InstallError(deps, extra=err_lines)


def do_init(project, ctx: RoutineContext):
    """Initialize the project, ensuring that the Pipfile and Pipfile.lock are in place.

    Per T_C.7: consumes :class:`RoutineContext`. This collapses the
    inline ``RoutineContext.from_cli(...)`` bridge that T_C.6 left at
    ``do_init``'s call to ``handle_lockfile``.
    """
    target = ctx.target_env
    policy = ctx.install_policy

    if not policy.deploy and not policy.ignore_pipfile:
        ensure_pipfile(project, system=target.system)

    handle_lockfile(project, ctx)

    if (
        not target.allow_global
        and not policy.deploy
        and "PIPENV_ACTIVE" not in os.environ
        and not project.s.is_quiet()
    ):
        console.print(
            "To activate this project's virtualenv, run [yellow]pipenv shell[/yellow].\n"
            "Alternatively, run a command inside the virtualenv with [yellow]pipenv run[/yellow]."
        )
