import os
import queue
import sys
import warnings
from collections import defaultdict
from tempfile import NamedTemporaryFile

from pipenv import environments, exceptions
from pipenv.patched.pip._internal.exceptions import PipError
from pipenv.routines.lock import do_lock
from pipenv.utils import console, err, fileutils
from pipenv.utils.dependencies import (
    expansive_install_req_from_line,
    get_lockfile_section_using_pipfile_category,
    install_req_from_pipfile,
)
from pipenv.utils.indexes import get_source_list
from pipenv.utils.internet import download_file, is_valid_url
from pipenv.utils.pip import (
    get_trusted_hosts,
    pip_install_deps,
)
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import add_index_to_pipfile, import_requirements
from pipenv.utils.shell import temp_environ
from pipenv.utils.virtualenv import cleanup_virtualenv, do_create_virtualenv


def do_install(
    project,
    packages=False,
    editable_packages=False,
    index=False,
    dev=False,
    python=False,
    pypi_mirror=None,
    system=False,
    ignore_pipfile=False,
    requirementstxt=False,
    pre=False,
    deploy=False,
    site_packages=None,
    extra_pip_args=None,
    categories=None,
    skip_lock=False,
):
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("default", category=ResourceWarning)
    packages = packages if packages else []
    editable_packages = editable_packages if editable_packages else []
    package_args = [p for p in packages if p] + [p for p in editable_packages if p]
    skip_requirements = False
    # Don't search for requirements.txt files if the user provides one
    if requirementstxt or package_args or project.pipfile_exists:
        skip_requirements = True
    # Ensure that virtualenv is available and pipfile are available
    ensure_project(
        project,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=skip_requirements,
        pypi_mirror=pypi_mirror,
        site_packages=site_packages,
        categories=categories,
    )
    # Don't attempt to install develop and default packages if Pipfile is missing
    if not project.pipfile_exists and not (package_args or dev):
        if not (ignore_pipfile or deploy):
            raise exceptions.PipfileNotFound(project.path_to("Pipfile"))
        elif ((skip_lock and deploy) or ignore_pipfile) and not project.lockfile_exists:
            raise exceptions.LockfileNotFound(project.path_to("Pipfile.lock"))
    # Load the --pre settings from the Pipfile.
    if not pre:
        pre = project.settings.get("allow_prereleases")
    remote = requirementstxt and is_valid_url(requirementstxt)
    if "default" in categories:
        raise exceptions.PipenvUsageError(
            message="Cannot install to category `default`-- did you mean `packages`?"
        )
    if "develop" in categories:
        raise exceptions.PipenvUsageError(
            message="Cannot install to category `develop`-- did you mean `dev-packages`?"
        )
    # Warn and exit if --system is used without a pipfile.
    if (system and package_args) and not project.s.PIPENV_VIRTUALENV:
        raise exceptions.SystemUsageError
    # Automatically use an activated virtualenv.
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
                dev=dev,
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

    # Allow more than one package to be provided.
    package_args = list(packages) + [f"-e {pkg}" for pkg in editable_packages]
    # Install all dependencies, if none was provided.
    # This basically ensures that we have a pipfile and lockfile, then it locks and
    # installs from the lockfile
    new_packages = []
    if not packages and not editable_packages:
        # Update project settings with prerelease preference.
        if pre:
            project.update_settings({"allow_prereleases": pre})
        do_init(
            project,
            dev=dev,
            allow_global=system,
            ignore_pipfile=ignore_pipfile,
            system=system,
            deploy=deploy,
            pre=pre,
            requirements_dir=requirements_directory,
            pypi_mirror=pypi_mirror,
            extra_pip_args=extra_pip_args,
            categories=categories,
            skip_lock=skip_lock,
        )

    # This is for if the user passed in dependencies, then we want to make sure we
    else:
        # make a tuple of (display_name, entry)
        pkg_list = packages + [f"-e {pkg}" for pkg in editable_packages]
        if not system and not project.virtualenv_exists:
            do_init(
                project,
                dev=dev,
                system=system,
                allow_global=system,
                requirements_dir=requirements_directory,
                deploy=deploy,
                pypi_mirror=pypi_mirror,
                extra_pip_args=extra_pip_args,
                categories=categories,
                skip_lock=skip_lock,
            )

        for pkg_line in pkg_list:
            console.print(
                f"Installing {pkg_line}...",
                style="bold green",
            )
            # pip install:
            with temp_environ(), console.status(
                "Installing...", spinner=project.s.PIPENV_SPINNER
            ) as st:
                if not system:
                    os.environ["PIP_USER"] = "0"
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]
                st.console.print(f"Resolving {pkg_line}...", markup=False)
                try:
                    pkg_requirement, _ = expansive_install_req_from_line(
                        pkg_line, expand_env=True
                    )
                except ValueError as e:
                    err.print(f"[red]WARNING[/red]: {e}")
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Installation Failed"
                        )
                    )
                    sys.exit(1)
                st.update(f"Installing {pkg_requirement.name}...")
                if categories:
                    pipfile_sections = ""
                    for c in categories:
                        pipfile_sections += f"[{c}]"
                elif dev:
                    pipfile_sections = "[dev-packages]"
                else:
                    pipfile_sections = "[packages]"
                # Add the package to the Pipfile.
                if index:
                    source = project.get_index_by_name(index)
                    default_index = project.get_default_index()["name"]
                    if not source:
                        index_name = add_index_to_pipfile(project, index)
                        if index_name != default_index:
                            pkg_requirement.index = index_name
                    elif source["name"] != default_index:
                        pkg_requirement.index = source["name"]
                try:
                    if categories:
                        for category in categories:
                            added, cat, normalized_name = project.add_package_to_pipfile(
                                pkg_requirement, pkg_line, dev, category
                            )
                            if added:
                                new_packages.append((normalized_name, cat))
                                st.console.print(
                                    f"[bold]Added [green]{normalized_name}[/green][/bold] to Pipfile's "
                                    f"[yellow]\\{pipfile_sections}[/yellow] ..."
                                )
                    else:
                        added, cat, normalized_name = project.add_package_to_pipfile(
                            pkg_requirement, pkg_line, dev
                        )
                        if added:
                            new_packages.append((normalized_name, cat))
                            st.console.print(
                                f"[bold]Added [green]{normalized_name}[/green][/bold] to Pipfile's "
                                f"[yellow]\\{pipfile_sections}[/yellow] ..."
                            )
                except ValueError:
                    import traceback

                    err.print(f"[bold][red]Error:[/red][/bold] {traceback.format_exc()}")
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Failed adding package to Pipfile"
                        )
                    )
                # ok has a nice v in front, should do something similar with rich
                st.console.print(
                    environments.PIPENV_SPINNER_OK_TEXT.format("Installation Succeeded")
                )
            # Update project settings with pre-release preference.
            if pre:
                project.update_settings({"allow_prereleases": pre})
        try:
            do_init(
                project,
                dev=dev,
                system=system,
                allow_global=system,
                requirements_dir=requirements_directory,
                deploy=deploy,
                pypi_mirror=pypi_mirror,
                extra_pip_args=extra_pip_args,
                categories=categories,
                skip_lock=skip_lock,
            )
        except Exception as e:
            # If we fail to install, remove the package from the Pipfile.
            for pkg_name, category in new_packages:
                project.remove_package_from_pipfile(pkg_name, category)
            raise e
    sys.exit(0)


def do_sync(
    project,
    dev=False,
    python=None,
    bare=False,
    user=False,
    clear=False,
    unused=False,
    pypi_mirror=None,
    system=False,
    deploy=False,
    extra_pip_args=None,
    categories=None,
    site_packages=False,
):
    # The lock file needs to exist because sync won't write to it.
    if not project.lockfile_exists:
        raise exceptions.LockfileNotFound("Pipfile.lock")

    # Ensure that virtualenv is available if not system.
    ensure_project(
        project,
        python=python,
        validate=False,
        system=system,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
        clear=clear,
        site_packages=site_packages,
    )

    # Install everything.
    requirements_dir = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    if system:
        project.s.PIPENV_USE_SYSTEM = True
        os.environ["PIPENV_USE_SYSTEM"] = "1"
    do_init(
        project,
        dev=dev,
        allow_global=system,
        requirements_dir=requirements_dir,
        ignore_pipfile=True,  # Don't check if Pipfile and lock match.
        pypi_mirror=pypi_mirror,
        deploy=deploy,
        system=system,
        extra_pip_args=extra_pip_args,
        categories=categories,
    )
    if not bare:
        console.print("[green]All dependencies are now up-to-date![/green]")


def do_install_dependencies(
    project,
    dev=False,
    dev_only=False,
    bare=False,
    allow_global=False,
    ignore_hashes=False,
    requirements_dir=None,
    pypi_mirror=None,
    extra_pip_args=None,
    categories=None,
    skip_lock=False,
):
    """
    Executes the installation functionality.

    """
    procs = queue.Queue(maxsize=1)
    if not categories:
        if dev and dev_only:
            categories = ["dev-packages"]
        elif dev:
            categories = ["packages", "dev-packages"]
        else:
            categories = ["packages"]

    for category in categories:
        # Load the lockfile if it exists, or if dev_only is being used.
        lockfile = None
        pipfile = None
        if skip_lock:
            ignore_hashes = True
            if not bare:
                console.print("Installing dependencies from Pipfile...", style="bold")
            pipfile = project.get_pipfile_section(category)
        else:
            lockfile = project.get_or_create_lockfile(categories=categories)
            if not bare:
                console.print(
                    f"Installing dependencies from Pipfile.lock "
                    f"({lockfile['_meta'].get('hash', {}).get('sha256')[-6:]})...",
                    style="bold",
                )
        dev = dev or dev_only
        if skip_lock:
            deps_list = []
            for req_name, pipfile_entry in pipfile.items():
                install_req, markers, req_line = install_req_from_pipfile(
                    req_name, pipfile_entry
                )
                req_line = f"{req_line}; {markers}" if markers else f"{req_line}"
                deps_list.append(
                    (
                        install_req,
                        req_line,
                    )
                )
        else:
            deps_list = list(
                lockfile.get_requirements(dev=dev, only=dev_only, categories=[category])
            )
        editable_or_vcs_deps = [
            (dep, pip_line) for dep, pip_line in deps_list if (dep.link and dep.editable)
        ]
        normal_deps = [
            (dep, pip_line)
            for dep, pip_line in deps_list
            if not (dep.link and dep.editable)
        ]

        install_kwargs = {
            "no_deps": not skip_lock,
            "ignore_hashes": ignore_hashes,
            "allow_global": allow_global,
            "pypi_mirror": pypi_mirror,
            "sequential_deps": editable_or_vcs_deps,
            "extra_pip_args": extra_pip_args,
        }
        if skip_lock:
            lockfile_section = pipfile
        else:
            lockfile_category = get_lockfile_section_using_pipfile_category(category)
            lockfile_section = lockfile[lockfile_category]
        batch_install(
            project,
            normal_deps,
            lockfile_section,
            procs,
            requirements_dir,
            **install_kwargs,
        )

        if not procs.empty():
            _cleanup_procs(project, procs)


def batch_install_iteration(
    project,
    deps_to_install,
    sources,
    procs,
    requirements_dir,
    no_deps=True,
    ignore_hashes=False,
    allow_global=False,
    extra_pip_args=None,
):
    with temp_environ():
        if not allow_global:
            os.environ["PIP_USER"] = "0"
            if "PYTHONHOME" in os.environ:
                del os.environ["PYTHONHOME"]
        if "GIT_CONFIG" in os.environ:
            del os.environ["GIT_CONFIG"]
        cmds = pip_install_deps(
            project,
            deps=deps_to_install,
            sources=sources,
            allow_global=allow_global,
            ignore_hashes=ignore_hashes,
            no_deps=no_deps,
            requirements_dir=requirements_dir,
            use_pep517=True,
            extra_pip_args=extra_pip_args,
        )

        for c in cmds:
            procs.put(c)
            _cleanup_procs(project, procs)


def batch_install(
    project,
    deps_list,
    lockfile_section,
    procs,
    requirements_dir,
    no_deps=True,
    ignore_hashes=False,
    allow_global=False,
    pypi_mirror=None,
    sequential_deps=None,
    extra_pip_args=None,
):
    if sequential_deps is None:
        sequential_deps = []
    deps_to_install = deps_list[:]
    deps_to_install.extend(sequential_deps)
    deps_to_install = [
        (dep, pip_line)
        for dep, pip_line in deps_to_install
        if not project.environment.is_satisfied(dep)
    ]
    search_all_sources = project.settings.get("install_search_all_sources", False)
    sources = get_source_list(
        project,
        index=None,
        extra_indexes=None,
        trusted_hosts=get_trusted_hosts(),
        pypi_mirror=pypi_mirror,
    )
    if search_all_sources:
        dependencies = [pip_line for _, pip_line in deps_to_install]
        batch_install_iteration(
            project,
            dependencies,
            sources,
            procs,
            requirements_dir,
            no_deps=no_deps,
            ignore_hashes=ignore_hashes,
            allow_global=allow_global,
            extra_pip_args=extra_pip_args,
        )
    else:
        # Sort the dependencies out by index -- include editable/vcs in the default group
        deps_by_index = defaultdict(list)
        for dependency, pip_line in deps_to_install:
            index = project.sources_default["name"]
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
                    dependencies,
                    [install_source],
                    procs,
                    requirements_dir,
                    no_deps=no_deps,
                    ignore_hashes=ignore_hashes,
                    allow_global=allow_global,
                    extra_pip_args=extra_pip_args,
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


def do_init(
    project,
    dev=False,
    dev_only=False,
    allow_global=False,
    ignore_pipfile=False,
    system=False,
    deploy=False,
    pre=False,
    requirements_dir=None,
    pypi_mirror=None,
    extra_pip_args=None,
    categories=None,
    skip_lock=False,
):
    """Executes the init functionality."""
    python = None
    if project.s.PIPENV_PYTHON is not None:
        python = project.s.PIPENV_PYTHON
    elif project.s.PIPENV_DEFAULT_PYTHON_VERSION is not None:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    if categories is None:
        categories = []

    if not system and not project.s.PIPENV_USE_SYSTEM and not project.virtualenv_exists:
        try:
            do_create_virtualenv(project, python=python, pypi_mirror=pypi_mirror)
        except KeyboardInterrupt:
            cleanup_virtualenv(project, bare=False)
            sys.exit(1)
    # Ensure the Pipfile exists.
    if not deploy:
        ensure_pipfile(project, system=system)
    if not requirements_dir:
        requirements_dir = fileutils.create_tracked_tempdir(
            suffix="-requirements", prefix="pipenv-"
        )
    # Write out the lockfile if it doesn't exist, but not if the Pipfile is being ignored
    if (project.lockfile_exists and not ignore_pipfile) and not skip_lock:
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if deploy:
                console.print(
                    f"Your Pipfile.lock ({old_hash[-6:]}) is out of date.  Expected: ({new_hash[-6:]}).",
                    style="red",
                )
                raise exceptions.DeployException
            if (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
                err.print(
                    f"Pipfile.lock ({old_hash[-6:]}) out of date, but installation uses --system so"
                    f"re-building lockfile must happen in isolation."
                    f" Please rebuild lockfile in a virtualenv.  Continuing anyway...",
                    style="yellow",
                )
            else:
                if old_hash:
                    msg = "Pipfile.lock ({0}) out of date, updating to ({1})..."
                else:
                    msg = "Pipfile.lock is corrupt, replaced with ({1})..."
                err.print(
                    msg.format(old_hash[-6:], new_hash[-6:]),
                    style="bold yellow",
                )
                do_lock(
                    project,
                    system=system,
                    pre=pre,
                    write=True,
                    pypi_mirror=pypi_mirror,
                    categories=categories,
                )
    # Write out the lockfile if it doesn't exist.
    if not project.lockfile_exists and not skip_lock:
        # Unless we're in a virtualenv not managed by pipenv, abort if we're
        # using the system's python.
        if (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
            raise exceptions.PipenvOptionsError(
                "--system",
                "--system is intended to be used for Pipfile installation, "
                "not installation of specific packages. Aborting.\n"
                "See also: --deploy flag.",
            )
        else:
            err.print(
                "Pipfile.lock not found, creating...",
                style="bold",
            )
            do_lock(
                project,
                system=system,
                pre=pre,
                write=True,
                pypi_mirror=pypi_mirror,
                categories=categories,
            )
    do_install_dependencies(
        project,
        dev=dev,
        dev_only=dev_only,
        allow_global=allow_global,
        requirements_dir=requirements_dir,
        pypi_mirror=pypi_mirror,
        extra_pip_args=extra_pip_args,
        categories=categories,
        skip_lock=skip_lock,
    )

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        console.print(
            "To activate this project's virtualenv, run [yellow]pipenv shell[/yellow].\n"
            "Alternatively, run a command inside the virtualenv with [yellow]pipenv run[/yellow]."
        )
