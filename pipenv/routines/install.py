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


def handle_new_packages(
    project,
    packages,
    editable_packages,
    dev,
    pre,
    system,
    pypi_mirror,
    extra_pip_args,
    pipfile_categories,
    perform_upgrades=True,
    index=None,
):
    from pipenv.routines.update import do_update

    new_packages = []
    if packages or editable_packages:

        pkg_list = packages + [f"-e {pkg}" for pkg in editable_packages]

        for pkg_line in pkg_list:
            console.print(f"Installing {pkg_line}...", style="bold green")
            with temp_environ():
                if not system:
                    os.environ["PIP_USER"] = "0"
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]

                try:
                    pkg_requirement, _ = expansive_install_req_from_line(
                        pkg_line, expand_env=True
                    )
                    if index:
                        source = project.get_index_by_name(index)
                        default_index = project.get_default_index()["name"]
                        if not source:
                            index_name = add_index_to_pipfile(project, index)
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
                    if pipfile_categories:
                        for category in pipfile_categories:
                            added, cat, normalized_name = project.add_package_to_pipfile(
                                pkg_requirement, pkg_line, dev, category
                            )
                            if added:
                                new_packages.append((normalized_name, cat))
                    else:
                        added, cat, normalized_name = project.add_package_to_pipfile(
                            pkg_requirement, pkg_line, dev
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
        if pre:
            project.update_settings({"allow_prereleases": pre})

    # Use the update routine for new packages
    if perform_upgrades and (packages or editable_packages):
        try:
            do_update(
                project,
                dev=dev,
                pre=pre,
                packages=packages,
                editable_packages=editable_packages,
                pypi_mirror=pypi_mirror,
                index_url=index,
                extra_pip_args=extra_pip_args,
                categories=pipfile_categories,
            )
            return new_packages, True
        except Exception:
            for pkg_name, category in new_packages:
                project.remove_package_from_pipfile(pkg_name, category)
            raise

    return new_packages, False


def handle_lockfile(
    project,
    packages,
    ignore_pipfile,
    skip_lock,
    system,
    allow_global,
    deploy,
    pre,
    pypi_mirror,
    categories,
):
    """Handle the lockfile, updating if necessary.  Returns True if package updates were applied."""
    if (
        (project.lockfile_exists and not ignore_pipfile)
        and not skip_lock
        and not packages
    ):
        old_hash = project.get_lockfile_hash()
        new_hash = project.calculate_pipfile_hash()
        if new_hash != old_hash:
            if deploy:
                console.print(
                    f"Your Pipfile.lock ({old_hash}) is out of date. Expected: ({new_hash}).",
                    style="red",
                )
                raise exceptions.DeployException
            elif not system:
                handle_outdated_lockfile(
                    project,
                    packages,
                    old_hash=old_hash,
                    new_hash=new_hash,
                    system=system,
                    allow_global=allow_global,
                    skip_lock=skip_lock,
                    pre=pre,
                    pypi_mirror=pypi_mirror,
                    categories=categories,
                )
    elif not project.lockfile_exists and not skip_lock:
        handle_missing_lockfile(project, system, allow_global, pre, pypi_mirror)


def handle_outdated_lockfile(
    project,
    packages,
    old_hash,
    new_hash,
    system,
    allow_global,
    skip_lock,
    pre,
    pypi_mirror,
    categories,
):
    """Handle an outdated lockfile returning True if package updates were applied."""
    if (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
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
        if not skip_lock:
            do_lock(
                project,
                system=system,
                pre=pre,
                write=True,
                pypi_mirror=pypi_mirror,
                categories=None,
            )


def handle_missing_lockfile(project, system, allow_global, pre, pypi_mirror):
    if (system or allow_global) and not project.s.PIPENV_VIRTUALENV:
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
        )


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
    pipfile_categories=None,
    skip_lock=False,
):
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("ignore", category=ResourceWarning)
    packages = packages if packages else []
    editable_packages = editable_packages if editable_packages else []
    package_args = [p for p in packages if p] + [p for p in editable_packages if p]
    new_packages = []
    if dev and not pipfile_categories:
        pipfile_categories = ["dev-packages"]
    elif not pipfile_categories:
        pipfile_categories = ["packages"]

    ensure_project(
        project,
        python=python,
        system=system,
        warn=True,
        deploy=deploy,
        skip_requirements=False,
        pypi_mirror=pypi_mirror,
        site_packages=site_packages,
        pipfile_categories=pipfile_categories,
    )

    do_init(
        project,
        package_args,
        system=system,
        allow_global=system,
        deploy=deploy,
        pypi_mirror=pypi_mirror,
        skip_lock=skip_lock,
        categories=pipfile_categories,
    )

    do_install_validations(
        project,
        package_args,
        requirements_directory,
        dev=dev,
        system=system,
        ignore_pipfile=ignore_pipfile,
        requirementstxt=requirementstxt,
        pre=pre,
        deploy=deploy,
        categories=pipfile_categories,
        skip_lock=skip_lock,
    )
    if not (deploy or system):
        new_packages, _ = handle_new_packages(
            project,
            packages,
            editable_packages,
            dev=dev,
            pre=pre,
            system=system,
            pypi_mirror=pypi_mirror,
            extra_pip_args=extra_pip_args,
            pipfile_categories=pipfile_categories,
            perform_upgrades=not skip_lock,
            index=index,
        )

    try:
        if dev:  # Install both develop and default package categories from Pipfile.
            pipfile_categories = ["packages", "dev-packages"]
        do_install_dependencies(
            project,
            dev=dev,
            allow_global=system,
            requirements_dir=requirements_directory,
            pypi_mirror=pypi_mirror,
            extra_pip_args=extra_pip_args,
            categories=pipfile_categories,
            skip_lock=skip_lock,
        )
    except Exception as e:
        # If we fail to install, remove the package from the Pipfile.
        for pkg_name, category in new_packages:
            project.remove_package_from_pipfile(pkg_name, category)
        raise e

    sys.exit(0)


def do_install_validations(
    project,
    package_args,
    requirements_directory,
    dev=False,
    system=False,
    ignore_pipfile=False,
    requirementstxt=False,
    pre=False,
    deploy=False,
    categories=None,
    skip_lock=False,
):
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


def do_install_dependencies(
    project,
    dev=False,
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
        if dev:
            categories = ["packages", "dev-packages"]
        else:
            categories = ["packages"]

    for pipfile_category in categories:
        lockfile = None
        pipfile = None
        if skip_lock:
            ignore_hashes = True
            if not bare:
                console.print("Installing dependencies from Pipfile...", style="bold")
            pipfile = project.get_pipfile_section(pipfile_category)
        else:
            lockfile = project.get_or_create_lockfile(categories=categories)
            if not bare:
                lockfile_category = get_lockfile_section_using_pipfile_category(
                    pipfile_category
                )
                console.print(
                    f"Installing dependencies from Pipfile.lock [{lockfile_category}]"
                    f"({lockfile['_meta'].get('hash', {}).get('sha256')[-6:]})...",
                    style="bold",
                )
        if skip_lock:
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
                    dev=dev, only=False, categories=[lockfile_category]
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
            lockfile_category = get_lockfile_section_using_pipfile_category(
                pipfile_category
            )
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
    packages=None,
    allow_global=False,
    ignore_pipfile=False,
    system=False,
    deploy=False,
    pre=False,
    pypi_mirror=None,
    skip_lock=False,
    categories=None,
):
    """Initialize the project, ensuring that the Pipfile and Pipfile.lock are in place.
    Returns True if packages were updated + installed.
    """
    if not deploy:
        ensure_pipfile(project, system=system)

    handle_lockfile(
        project,
        packages,
        ignore_pipfile=ignore_pipfile,
        skip_lock=skip_lock,
        system=system,
        allow_global=allow_global,
        deploy=deploy,
        pre=pre,
        pypi_mirror=pypi_mirror,
        categories=categories,
    )

    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        console.print(
            "To activate this project's virtualenv, run [yellow]pipenv shell[/yellow].\n"
            "Alternatively, run a command inside the virtualenv with [yellow]pipenv run[/yellow]."
        )
