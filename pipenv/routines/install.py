import os
import queue
import sys
import warnings
from collections import defaultdict
from tempfile import NamedTemporaryFile

from pipenv import environments, exceptions
from pipenv.patched.pip._internal.exceptions import PipError
from pipenv.patched.pip._vendor import rich
from pipenv.routines.lock import do_lock
from pipenv.utils.dependencies import convert_deps_to_pip, is_star
from pipenv.utils.indexes import get_source_list
from pipenv.utils.internet import download_file, is_valid_url
from pipenv.utils.pip import (
    get_trusted_hosts,
    pip_install_deps,
)
from pipenv.utils.pipfile import ensure_pipfile
from pipenv.utils.project import ensure_project
from pipenv.utils.requirements import add_index_to_pipfile, import_requirements
from pipenv.utils.virtualenv import cleanup_virtualenv, do_create_virtualenv
from pipenv.vendor import click
from pipenv.vendor.requirementslib import fileutils
from pipenv.vendor.requirementslib.models.requirements import Requirement
from pipenv.vendor.requirementslib.utils import temp_environ

console = rich.console.Console()
err = rich.console.Console(stderr=True)


def do_install(
    project,
    packages=False,
    editable_packages=False,
    index_url=False,
    dev=False,
    python=False,
    pypi_mirror=None,
    system=False,
    ignore_pipfile=False,
    skip_lock=False,
    requirementstxt=False,
    pre=False,
    deploy=False,
    keep_outdated=False,
    selective_upgrade=False,
    site_packages=None,
    extra_pip_args=None,
    categories=None,
):
    requirements_directory = fileutils.create_tracked_tempdir(
        suffix="-requirements", prefix="pipenv-"
    )
    warnings.filterwarnings("default", category=ResourceWarning)
    if selective_upgrade:
        keep_outdated = True
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
    if not keep_outdated:
        keep_outdated = project.settings.get("keep_outdated")
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
        click.secho(
            "Remote requirements file provided! Downloading...",
            bold=True,
            err=True,
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
            click.secho(
                f"Unable to find requirements file at {requirements_url}.",
                fg="red",
                err=True,
            )
            sys.exit(1)
        finally:
            fd.close()
        # Replace the url with the temporary requirements file
        requirementstxt = temp_reqs
        remote = True
    if requirementstxt:
        error, traceback = None, None
        click.secho(
            "Requirements file provided! Importing into Pipfile...",
            bold=True,
            err=True,
        )
        try:
            import_requirements(project, r=project.path_to(requirementstxt), dev=dev)
        except (UnicodeDecodeError, PipError) as e:
            # Don't print the temp file path if remote since it will be deleted.
            req_path = requirements_url if remote else project.path_to(requirementstxt)
            error = (
                "Unexpected syntax in {}. Are you sure this is a "
                "requirements.txt style file?".format(req_path)
            )
            traceback = e
        except AssertionError as e:
            error = (
                "Requirements file doesn't appear to exist. Please ensure the file exists in your "
                "project directory or you provided the correct path."
            )
            traceback = e
        finally:
            # If requirements file was provided by remote url delete the temporary file
            if remote:
                fd.close()  # Close for windows to allow file cleanup.
                os.remove(temp_reqs)
            if error and traceback:
                click.secho(error, fg="red")
                click.secho(str(traceback), fg="yellow", err=True)
                sys.exit(1)

    # Allow more than one package to be provided.
    package_args = [p for p in packages] + [f"-e {pkg}" for pkg in editable_packages]
    # Support for --selective-upgrade.
    # We should do this part first to make sure that we actually do selectively upgrade
    # the items specified
    if selective_upgrade:
        from pipenv.vendor.requirementslib.models.requirements import Requirement

        for i, package in enumerate(package_args[:]):
            section = project.packages if not dev else project.dev_packages
            package = Requirement.from_line(package)
            package__name, package__val = package.pipfile_entry
            try:
                if not is_star(section[package__name]) and is_star(package__val):
                    # Support for VCS dependencies.
                    package_args[i] = convert_deps_to_pip(
                        {package__name: section[package__name]}, project=project
                    )[0]
            except KeyError:
                pass
    # Install all dependencies, if none was provided.
    # This basically ensures that we have a pipfile and lockfile, then it locks and
    # installs from the lockfile
    new_packages = []
    if not packages and not editable_packages:
        # Update project settings with pre preference.
        if pre:
            project.update_settings({"allow_prereleases": pre})
        do_init(
            project,
            dev=dev,
            allow_global=system,
            ignore_pipfile=ignore_pipfile,
            system=system,
            skip_lock=skip_lock,
            deploy=deploy,
            pre=pre,
            requirements_dir=requirements_directory,
            pypi_mirror=pypi_mirror,
            keep_outdated=keep_outdated,
            extra_pip_args=extra_pip_args,
            categories=categories,
        )

    # This is for if the user passed in dependencies, then we want to make sure we
    else:
        from pipenv.vendor.requirementslib.models.requirements import Requirement

        # make a tuple of (display_name, entry)
        pkg_list = packages + [f"-e {pkg}" for pkg in editable_packages]
        if not system and not project.virtualenv_exists:
            do_init(
                project,
                dev=dev,
                system=system,
                allow_global=system,
                keep_outdated=keep_outdated,
                requirements_dir=requirements_directory,
                deploy=deploy,
                pypi_mirror=pypi_mirror,
                skip_lock=skip_lock,
                extra_pip_args=extra_pip_args,
                categories=categories,
            )

        for pkg_line in pkg_list:
            click.secho(
                f"Installing {pkg_line}...",
                fg="green",
                bold=True,
            )
            # pip install:
            with temp_environ(), console.status(
                "Installing...", spinner=project.s.PIPENV_SPINNER
            ) as st:
                if not system:
                    os.environ["PIP_USER"] = "0"
                    if "PYTHONHOME" in os.environ:
                        del os.environ["PYTHONHOME"]
                st.console.print(f"Resolving {pkg_line}...")
                try:
                    pkg_requirement = Requirement.from_line(pkg_line)
                except ValueError as e:
                    err.print("{}: {}".format(click.style("WARNING", fg="red"), e))
                    err.print(
                        environments.PIPENV_SPINNER_FAIL_TEXT.format(
                            "Installation Failed"
                        )
                    )
                    sys.exit(1)
                st.update(f"Installing {pkg_requirement.name}...")
                # Warn if --editable wasn't passed.
                if (
                    pkg_requirement.is_vcs
                    and not pkg_requirement.editable
                    and not project.s.PIPENV_RESOLVE_VCS
                ):
                    err.print(
                        "{}: You installed a VCS dependency in non-editable mode. "
                        "This will work fine, but sub-dependencies will not be resolved by {}."
                        "\n  To enable this sub-dependency functionality, specify that this dependency is editable."
                        "".format(
                            click.style("Warning", fg="red", bold=True),
                            click.style("$ pipenv lock", fg="yellow"),
                        )
                    )
                if categories:
                    pipfile_sections = ""
                    for c in categories:
                        pipfile_sections += f"[{c}]"
                elif dev:
                    pipfile_sections = "[dev-packages]"
                else:
                    pipfile_sections = "[packages]"
                st.console.print(
                    f"[bold]Adding [green]{pkg_requirement.name}[/green][/bold] to Pipfile's [yellow]\\{pipfile_sections}[/yellow] ..."
                )
                # Add the package to the Pipfile.
                if index_url:
                    index_name = add_index_to_pipfile(project, index_url)
                    pkg_requirement.index = index_name
                try:
                    if categories:
                        for category in categories:
                            added, cat = project.add_package_to_pipfile(
                                pkg_requirement, dev, category
                            )
                            if added:
                                new_packages.append((pkg_requirement.name, cat))
                    else:
                        added, cat = project.add_package_to_pipfile(pkg_requirement, dev)
                        if added:
                            new_packages.append((pkg_requirement.name, cat))
                except ValueError:
                    import traceback

                    err.print(
                        "{} {}".format(
                            click.style("Error:", fg="red", bold=True),
                            traceback.format_exc(),
                        )
                    )
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
                keep_outdated=keep_outdated,
                requirements_dir=requirements_directory,
                deploy=deploy,
                pypi_mirror=pypi_mirror,
                skip_lock=skip_lock,
                extra_pip_args=extra_pip_args,
                categories=categories,
            )
        except RuntimeError:
            # If we fail to install, remove the package from the Pipfile.
            for pkg_name, category in new_packages:
                project.remove_package_from_pipfile(pkg_name, category)
            sys.exit(1)
    sys.exit(0)


def do_sync(
    project,
    dev=False,
    python=None,
    bare=False,
    dont_upgrade=False,
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
        click.echo(click.style("All dependencies are now up-to-date!", fg="green"))


def do_install_dependencies(
    project,
    dev=False,
    dev_only=False,
    bare=False,
    allow_global=False,
    ignore_hashes=False,
    skip_lock=False,
    requirements_dir=None,
    pypi_mirror=None,
    extra_pip_args=None,
    categories=None,
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

    lockfile = None
    pipfile = None
    for category in categories:
        # Load the lockfile if it exists, or if dev_only is being used.
        if skip_lock:
            if not bare:
                click.secho("Installing dependencies from Pipfile...", bold=True)
            pipfile = project.get_pipfile_section(category)
        else:
            lockfile = project.get_or_create_lockfile(categories=categories)
            if not bare:
                click.secho(
                    "Installing dependencies from Pipfile.lock ({})...".format(
                        lockfile["_meta"].get("hash", {}).get("sha256")[-6:]
                    ),
                    bold=True,
                )
        dev = dev or dev_only
        if lockfile:
            deps_list = list(
                lockfile.get_requirements(dev=dev, only=dev_only, categories=[category])
            )
        else:
            deps_list = []
            for req_name, specifier in pipfile.items():
                deps_list.append(Requirement.from_pipfile(req_name, specifier))
        failed_deps_queue = queue.Queue()
        if skip_lock:
            ignore_hashes = True
        editable_or_vcs_deps = [dep for dep in deps_list if (dep.editable or dep.vcs)]
        normal_deps = [dep for dep in deps_list if not (dep.editable or dep.vcs)]
        install_kwargs = {
            "no_deps": not skip_lock,
            "ignore_hashes": ignore_hashes,
            "allow_global": allow_global,
            "pypi_mirror": pypi_mirror,
            "sequential_deps": editable_or_vcs_deps,
            "extra_pip_args": extra_pip_args,
        }

        batch_install(
            project,
            normal_deps,
            procs,
            failed_deps_queue,
            requirements_dir,
            **install_kwargs,
        )

        if not procs.empty():
            _cleanup_procs(project, procs, failed_deps_queue)

        # Iterate over the hopefully-poorly-packaged dependencies...
        if not failed_deps_queue.empty():
            click.secho("Installing initially failed dependencies...", bold=True)
            retry_list = []
            while not failed_deps_queue.empty():
                failed_dep = failed_deps_queue.get()
                retry_list.append(failed_dep)
            install_kwargs.update({"retry": False})
            batch_install(
                project,
                retry_list,
                procs,
                failed_deps_queue,
                requirements_dir,
                **install_kwargs,
            )
        if not procs.empty():
            _cleanup_procs(project, procs, failed_deps_queue, retry=False)
        if not failed_deps_queue.empty():
            failed_list = []
            while not failed_deps_queue.empty():
                failed_dep = failed_deps_queue.get()
                failed_list.append(failed_dep)
            click.echo(
                click.style(
                    f"Failed to install some dependency or packages.  "
                    f"The following have failed installation and attempted retry: {failed_list}",
                    fg="red",
                ),
                err=True,
            )
            sys.exit(1)


def batch_install_iteration(
    project,
    deps_to_install,
    sources,
    procs,
    failed_deps_queue,
    requirements_dir,
    no_deps=True,
    ignore_hashes=False,
    allow_global=False,
    retry=True,
    extra_pip_args=None,
):
    from pipenv.vendor.requirementslib.models.utils import (
        strip_extras_markers_from_requirement,
    )

    is_artifact = False
    for dep in deps_to_install:
        if dep.req.req:
            dep.req.req = strip_extras_markers_from_requirement(dep.req.req)
        if dep.markers:
            dep.markers = str(strip_extras_markers_from_requirement(dep.get_markers))
        # Install the module.
        if dep.is_file_or_url and (
            dep.is_direct_url
            or any(dep.req.uri.endswith(ext) for ext in ["zip", "tar.gz"])
        ):
            is_artifact = True
        elif dep.is_vcs:
            is_artifact = True

    with temp_environ():
        if not allow_global:
            os.environ["PIP_USER"] = "0"
            if "PYTHONHOME" in os.environ:
                del os.environ["PYTHONHOME"]
        if "GIT_CONFIG" in os.environ:
            del os.environ["GIT_CONFIG"]
        use_pep517 = True
        if not retry and not is_artifact:
            use_pep517 = False

        cmds = pip_install_deps(
            project,
            deps=deps_to_install,
            sources=sources,
            allow_global=allow_global,
            ignore_hashes=ignore_hashes,
            no_deps=no_deps,
            requirements_dir=requirements_dir,
            use_pep517=use_pep517,
            extra_pip_args=extra_pip_args,
        )

        for c in cmds:
            procs.put(c)
            _cleanup_procs(project, procs, failed_deps_queue, retry=retry)


def batch_install(
    project,
    deps_list,
    procs,
    failed_deps_queue,
    requirements_dir,
    no_deps=True,
    ignore_hashes=False,
    allow_global=False,
    pypi_mirror=None,
    retry=True,
    sequential_deps=None,
    extra_pip_args=None,
):
    if sequential_deps is None:
        sequential_deps = []
    deps_to_install = deps_list[:]
    deps_to_install.extend(sequential_deps)
    deps_to_install = [
        dep for dep in deps_to_install if not project.environment.is_satisfied(dep)
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
        batch_install_iteration(
            project,
            deps_to_install,
            sources,
            procs,
            failed_deps_queue,
            requirements_dir,
            no_deps=no_deps,
            ignore_hashes=ignore_hashes,
            allow_global=allow_global,
            retry=retry,
            extra_pip_args=extra_pip_args,
        )
    else:
        # Sort the dependencies out by index -- include editable/vcs in the default group
        deps_by_index = defaultdict(list)
        for dependency in deps_to_install:
            if dependency.index:
                deps_by_index[dependency.index].append(dependency)
            else:
                deps_by_index[project.sources_default["name"]].append(dependency)
        # Treat each index as its own pip install phase
        for index_name, dependencies in deps_by_index.items():
            try:
                install_source = next(filter(lambda s: s["name"] == index_name, sources))
                batch_install_iteration(
                    project,
                    dependencies,
                    [install_source],
                    procs,
                    failed_deps_queue,
                    requirements_dir,
                    no_deps=no_deps,
                    ignore_hashes=ignore_hashes,
                    allow_global=allow_global,
                    retry=retry,
                    extra_pip_args=extra_pip_args,
                )
            except StopIteration:
                click.secho(
                    f"Unable to find {index_name} in sources, please check dependencies: {dependencies}",
                    fg="red",
                    bold=True,
                )
                sys.exit(1)


def _cleanup_procs(project, procs, failed_deps_queue, retry=True):
    while not procs.empty():
        c = procs.get()
        try:
            out, err = c.communicate()
        except AttributeError:
            out, err = c.stdout, c.stderr
        failed = c.returncode != 0
        if project.s.is_verbose():
            click.secho(out.strip() or err.strip(), fg="yellow")
        # The Installation failed...
        if failed:
            deps = getattr(c, "deps", {}).copy()
            for dep in deps:
                # If there is a mismatch in installed locations or the install fails
                # due to wrongful disabling of pep517, we should allow for
                # additional passes at installation
                if "does not match installed location" in err:
                    project.environment.expand_egg_links()
                    click.echo(
                        "{}".format(
                            click.style(
                                "Failed initial installation: Failed to overwrite existing "
                                "package, likely due to path aliasing. Expanding and trying "
                                "again!",
                                fg="yellow",
                            )
                        )
                    )
                    if dep:
                        dep.use_pep517 = True
                elif "Disabling PEP 517 processing is invalid" in err:
                    if dep:
                        dep.use_pep517 = True
                elif not retry:
                    # The Installation failed...
                    # We echo both c.stdout and c.stderr because pip returns error details on out.
                    err = err.strip().splitlines() if err else []
                    out = out.strip().splitlines() if out else []
                    err_lines = [line for message in [out, err] for line in message]
                    # Return the subprocess' return code.
                    raise exceptions.InstallError(deps, extra=err_lines)
                else:
                    # Alert the user.
                    click.echo(
                        "{} {}! Will try again.".format(
                            click.style("An error occurred while installing", fg="red"),
                            click.style(dep.as_line() if dep else "", fg="green"),
                        ),
                        err=True,
                    )
                # Save the Failed Dependency for later.
                failed_deps_queue.put(dep)


def do_init(
    project,
    dev=False,
    dev_only=False,
    allow_global=False,
    ignore_pipfile=False,
    skip_lock=False,
    system=False,
    deploy=False,
    pre=False,
    keep_outdated=False,
    requirements_dir=None,
    pypi_mirror=None,
    extra_pip_args=None,
    categories=None,
):
    """Executes the init functionality."""
    python = None
    if project.s.PIPENV_PYTHON is not None:
        python = project.s.PIPENV_PYTHON
    elif project.s.PIPENV_DEFAULT_PYTHON_VERSION is not None:
        python = project.s.PIPENV_DEFAULT_PYTHON_VERSION
    if categories is None:
        categories = []

    if not system and not project.s.PIPENV_USE_SYSTEM:
        if not project.virtualenv_exists:
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
                click.secho(
                    "Your Pipfile.lock ({}) is out of date. Expected: ({}).".format(
                        old_hash[-6:], new_hash[-6:]
                    ),
                    fg="red",
                )
                raise exceptions.DeployException
            elif (system or allow_global) and not (project.s.PIPENV_VIRTUALENV):
                click.secho(
                    "Pipfile.lock ({}) out of date, but installation "
                    "uses {} re-building lockfile must happen in "
                    "isolation. Please rebuild lockfile in a virtualenv. "
                    "Continuing anyway...".format(old_hash[-6:], "--system"),
                    fg="yellow",
                    err=True,
                )
            else:
                if old_hash:
                    msg = "Pipfile.lock ({0}) out of date, updating to ({1})..."
                else:
                    msg = "Pipfile.lock is corrupt, replaced with ({1})..."
                click.secho(
                    msg.format(old_hash[-6:], new_hash[-6:]),
                    fg="yellow",
                    bold=True,
                    err=True,
                )
                do_lock(
                    project,
                    system=system,
                    pre=pre,
                    keep_outdated=keep_outdated,
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
            click.secho(
                "Pipfile.lock not found, creating...",
                bold=True,
                err=True,
            )
            do_lock(
                project,
                system=system,
                pre=pre,
                keep_outdated=keep_outdated,
                write=True,
                pypi_mirror=pypi_mirror,
                categories=categories,
            )
    do_install_dependencies(
        project,
        dev=dev,
        dev_only=dev_only,
        allow_global=allow_global,
        skip_lock=skip_lock,
        requirements_dir=requirements_dir,
        pypi_mirror=pypi_mirror,
        extra_pip_args=extra_pip_args,
        categories=categories,
    )

    # Hint the user what to do to activate the virtualenv.
    if not allow_global and not deploy and "PIPENV_ACTIVE" not in os.environ:
        click.echo(
            "To activate this project's virtualenv, run {}.\n"
            "Alternatively, run a command "
            "inside the virtualenv with {}.".format(
                click.style("pipenv shell", fg="yellow"),
                click.style("pipenv run", fg="yellow"),
            )
        )
